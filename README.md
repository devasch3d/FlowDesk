# FlowDesk

本地单机项目管理桌面应用：浏览器界面（Web UI）+ FastAPI + SQLite，全部离线运行。

## 功能范围

- **M1 Project（已完成）**：项目增删改查、搜索筛选、日期校验、乐观锁、JSON 导出。
- **M2 Account（已完成）**：注册/登录/退出/保持登录、会话管理、scrypt 密码哈希、按 owner_id 的项目权限隔离、登录限流、数据库迁移与备份。
- **路线图**：Account → Workspace → Task → Collaboration → Files → Dashboard → AI Copilot。

> 代码位置：`Program/source/`（详见其中 README.md）。可执行成品：`Program/FlowDesk.exe`。
> 需求文档：`References/`（FlowDesk.pdf、Account Section、Project Section）。

## 多机协作

- 协作模型：单仓库 + `main` 保护分支 + 每人 `feat/机器编号` 分支 + PR 合入（详见 `01-协作规范.md`）。
- 机器与目录归属：见 `02-任务切分表.md`（当前 A–G 共 7 台机器）。
- 成员操作手册：见 `多机协作成员操作手册.pdf`（仓库外，与规范配套）。
- Agent 提示词模板：`prompts/`（通用边界 + Codex Plus + 豆包工作版）。
- 新机器接入：`powershell -ExecutionPolicy Bypass -File scripts/setup-machine.ps1 -Machine X`（X 为你的机器编号）。

## 仓库内文件导航

| 文件/目录 | 作用 |
| --- | --- |
| `01-协作规范.md` | 分支/所有权/提交/PR/冲突规则，唯一维护人：机器 A |
| `02-任务切分表.md` | 机器 → 分支 → 目录归属，新增机器由负责人（A）维护 |
| `prompts/` | 各工具 Agent 的边界指令与提示词模板 |
| `scripts/setup-machine.ps1` | 每台机器一次性初始化脚本 |
| `Program/source/` | 项目源码（backend / frontend / tests） |
| `References/` | 需求文档 |

## 给开发者的快速开始

```powershell
cd Program\source
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe launcher.py
```

测试：`.\.venv\Scripts\python.exe -m pytest tests/ -q`；前端构建：`cd frontend; npm ci; npm run build`。
