"""Dashboard REST API router (M6). 维护人：机器 D。

GET /api/dashboard/overview?workspace_id=<id> —— 空间维度统计概览。

数据全部来自现有表的 SQL 聚合（GROUP BY / COUNT / SUM / JOIN），**不新建表**：
- 项目数：总数 / 按状态分布 / Active 求和（SUM CASE）/ 完成占比
- 任务：按状态分布 / 逾期数 / 完成进度 / 每日完成任务趋势（最近 14 天，缺日补 0）
- 即将到期：未来 7 天内未完成任务，按截止日升序，上限 10
- 近期活动：依赖 M7 Activity 表（机器 E 的 collaboration 模块），合入前返回空列表

权限：仅空间成员可见。空间不存在 / 非成员统一返回 404（与 tasks 路由口径一致）。
数据为空时返回全 0 的空结构（兼容 Task / Activity 未合入的过渡期）。
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Membership, Project, User, Workspace
from ..models.task import Task  # 直接从子模块导入，触发 Task 表注册；models/__init__.py 由 A 统一导出

PROJECT_STATUSES = ['Planning', 'Active', 'Paused', 'Completed', 'Archived']
TASK_STATUSES = ['Todo', 'In Progress', 'Review', 'Done']
TREND_DAYS = 14          # 每日完成任务趋势窗口（含今天）
UPCOMING_DAYS = 7        # 即将到期窗口（未来 N 天）
UPCOMING_LIMIT = 10      # 即将到期列表上限


class CompletionStats(BaseModel):
    completed: int
    total: int
    percent: float


class ProjectStats(BaseModel):
    total: int
    by_status: dict[str, int]
    active: int
    completion: CompletionStats


class DailyCompleted(BaseModel):
    date: str
    count: int


class TaskStats(BaseModel):
    total: int
    by_status: dict[str, int]
    overdue: int
    completion: CompletionStats
    daily_completed: list[DailyCompleted]


class UpcomingDue(BaseModel):
    task_id: int
    title: str
    due_date: date
    project_id: int
    project_name: str


class DashboardOverview(BaseModel):
    workspace_id: int
    projects: ProjectStats
    tasks: TaskStats
    upcoming_due: list[UpcomingDue]
    recent_activity: list  # M7 Activity 表合入后改为结构化条目


def build_dashboard_router(engine, current_user):
    router = APIRouter(prefix='/api')

    def member_workspace_or_404(db, workspace_id, user_id):
        """校验空间存在且当前用户是其成员。非成员与不存在统一 404。"""
        ws = db.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(404, '空间不存在或你不是该空间的成员')
        if not db.get(Membership, (user_id, workspace_id)):
            raise HTTPException(404, '空间不存在或你不是该空间的成员')
        return ws

    def completion(done, total):
        return CompletionStats(completed=done, total=total,
                               percent=round(done / total * 100, 1) if total else 0.0)

    @router.get('/dashboard/overview', response_model=DashboardOverview)
    def overview(workspace_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            member_workspace_or_404(db, workspace_id, user.id)
            today = date.today()

            # ---- 项目：总数 + 状态分布（GROUP BY）+ Active 求和（SUM CASE）----
            project_rows = db.execute(
                select(Project.status, func.count(Project.id))
                .where(Project.workspace_id == workspace_id)
                .group_by(Project.status)
            ).all()
            projects_by_status = {status: 0 for status in PROJECT_STATUSES}
            for status, count in project_rows:
                projects_by_status[status] = count
            project_total = sum(projects_by_status.values())
            project_active = db.scalar(
                select(func.sum(case((Project.status == 'Active', 1), else_=0)))
                .where(Project.workspace_id == workspace_id)
            ) or 0

            # ---- 任务：状态分布 / 逾期 / 完成进度（JOIN projects 限定空间）----
            task_status_rows = db.execute(
                select(Task.status, func.count(Task.id))
                .join(Project, Task.project_id == Project.id)
                .where(Project.workspace_id == workspace_id)
                .group_by(Task.status)
            ).all()
            tasks_by_status = {status: 0 for status in TASK_STATUSES}
            for status, count in task_status_rows:
                tasks_by_status[status] = count
            task_total = sum(tasks_by_status.values())
            task_done = tasks_by_status['Done']
            overdue = db.scalar(
                select(func.count(Task.id))
                .join(Project, Task.project_id == Project.id)
                .where(Project.workspace_id == workspace_id,
                       Task.due_date.is_not(None),
                       Task.due_date < today,
                       Task.status != 'Done')
            ) or 0

            # ---- 每日完成任务趋势：GROUP BY date(completed_at)，最近 TREND_DAYS 天缺日补 0 ----
            # completed_at 存 naive UTC，日期按 UTC 口径对齐（与 func.date 截取一致）
            utc_today = datetime.now(timezone.utc).date()
            since = datetime.combine(utc_today - timedelta(days=TREND_DAYS - 1), time.min)
            trend_rows = db.execute(
                select(func.date(Task.completed_at).label('d'), func.count(Task.id))
                .join(Project, Task.project_id == Project.id)
                .where(Project.workspace_id == workspace_id,
                       Task.completed_at.is_not(None),
                       Task.completed_at >= since)
                .group_by(func.date(Task.completed_at))
            ).all()
            trend_map = {day: count for day, count in trend_rows}
            daily_completed = [
                DailyCompleted(date=(since.date() + timedelta(days=i)).isoformat(),
                               count=trend_map.get((since.date() + timedelta(days=i)).isoformat(), 0))
                for i in range(TREND_DAYS)
            ]

            # ---- 即将到期：未来 UPCOMING_DAYS 天内未完成任务 ----
            deadline = today + timedelta(days=UPCOMING_DAYS)
            upcoming_rows = db.execute(
                select(Task, Project.name)
                .join(Project, Task.project_id == Project.id)
                .where(Project.workspace_id == workspace_id,
                       Task.due_date.is_not(None),
                       Task.due_date >= today,
                       Task.due_date <= deadline,
                       Task.status != 'Done')
                .order_by(Task.due_date, Task.id)
                .limit(UPCOMING_LIMIT)
            ).all()
            upcoming_due = [
                UpcomingDue(task_id=t.id, title=t.title, due_date=t.due_date,
                            project_id=t.project_id, project_name=name)
                for t, name in upcoming_rows
            ]

            return DashboardOverview(
                workspace_id=workspace_id,
                projects=ProjectStats(total=project_total,
                                      by_status=projects_by_status,
                                      active=project_active,
                                      completion=completion(projects_by_status['Completed'], project_total)),
                tasks=TaskStats(total=task_total,
                                by_status=tasks_by_status,
                                overdue=overdue,
                                completion=completion(task_done, task_total),
                                daily_completed=daily_completed),
                upcoming_due=upcoming_due,
                recent_activity=[],  # M7 Activity 表合入后接入
            )

    return router
