<script setup lang="ts">
import {computed, onMounted, ref} from 'vue';
import {ApiError, request, type User} from '../api';

const props = defineProps<{user: User; authBusy?: boolean}>();
const emit = defineEmits<{logout: []; account: []; 'session-lost': []; back: []}>();

type Completion = {completed: number; total: number; percent: number};
type ProjectStats = {total: number; by_status: Record<string, number>; active: number; completion: Completion};
type Daily = {date: string; count: number};
type TaskStats = {total: number; by_status: Record<string, number>; overdue: number; completion: Completion; daily_completed: Daily[]};
type Upcoming = {task_id: number; title: string; due_date: string; project_id: number; project_name: string};
type Overview = {workspace_id: number; projects: ProjectStats; tasks: TaskStats; upcoming_due: Upcoming[]; recent_activity: unknown[]};
type Workspace = {id: number; name: string; role: string};

const spaces = ref<Workspace[]>([]);
const selected = ref<number | null>(null);
const data = ref<Overview | null>(null);
const loading = ref(true);
const error = ref('');
const usingMock = ref(false);

const projectStatusLabels: Record<string, string> = {Planning: '计划中', Active: '进行中', Paused: '已暂停', Completed: '已完成', Archived: '已归档'};
const taskStatusLabels: Record<string, string> = {Todo: '待办', 'In Progress': '进行中', Review: '评审', Done: '已完成'};

const trendMax = computed(() => Math.max(1, ...(data.value?.tasks.daily_completed ?? []).map(d => d.count)));
const CIRCUMFERENCE = 2 * Math.PI * 42;

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** 占位数据：接口未就绪时用于展示图表形态（接口就绪后自动切换为真实数据）。 */
function mockOverview(wid: number): Overview {
  const today = new Date();
  const counts = [0, 1, 0, 2, 1, 0, 1, 2, 0, 1, 1, 0, 2, 1];
  const daily: Daily[] = counts.map((count, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - (counts.length - 1 - i));
    return {date: iso(d), count};
  });
  return {
    workspace_id: wid,
    projects: {
      total: 3, active: 1,
      by_status: {Planning: 1, Active: 1, Paused: 0, Completed: 1, Archived: 0},
      completion: {completed: 1, total: 3, percent: 33.3},
    },
    tasks: {
      total: 8, overdue: 2,
      by_status: {Todo: 3, 'In Progress': 2, Review: 1, Done: 2},
      completion: {completed: 2, total: 8, percent: 25},
      daily_completed: daily,
    },
    upcoming_due: [
      {task_id: 101, title: '整理需求文档', due_date: (() => {const d = new Date(today); d.setDate(d.getDate() + 2); return iso(d);})(), project_id: 1, project_name: '示例项目'},
      {task_id: 102, title: '评审设计稿', due_date: (() => {const d = new Date(today); d.setDate(d.getDate() + 5); return iso(d);})(), project_id: 2, project_name: '示例项目二'},
    ],
    recent_activity: [
      {type: 'task', action: '创建任务「整理需求文档」', at: iso(today)},
      {type: 'task', action: '「评审设计稿」状态变为 In Progress', at: iso(today)},
    ],
  };
}

async function api(path: string, method = 'GET', body?: unknown) {
  try {
    return await request(path, method, body, {'X-FlowDesk-User': String(props.user.id)});
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || (e.status === 409 && e.message.includes('账号已')))) emit('session-lost');
    throw e;
  }
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    spaces.value = await api('/workspaces') as Workspace[];
    if (spaces.value.length) await chooseSpace(spaces.value[0].id);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

async function chooseSpace(id: number) {
  selected.value = id;
  try {
    data.value = await api(`/dashboard/overview?workspace_id=${id}`) as Overview;
    usingMock.value = false;
    error.value = '';
  } catch (e) {
    // 接口未就绪（尚未合入 main 等场景）→ 回退占位数据，保证图表页可用
    data.value = mockOverview(id);
    usingMock.value = true;
    error.value = '';
  }
}

function barPercent(count: number, max: number): number {
  return max > 0 ? Math.round((count / max) * 100) : 0;
}

onMounted(load);
</script>

<template>
  <div class="dash">
    <div class="dash-top">
      <button class="dash-back" @click="emit('back')">← 返回</button>
      <strong class="dash-title">FlowDesk · 仪表盘</strong>
      <select class="dash-space" :value="selected ?? ''" :disabled="loading" @change="chooseSpace(Number(($event.target as HTMLSelectElement).value))">
        <option value="" disabled>选择空间…</option>
        <option v-for="s in spaces" :key="s.id" :value="s.id">{{s.name}}</option>
      </select>
    </div>

    <div class="dash-body">
      <div v-if="loading" class="dash-hint">加载中…</div>
      <div v-else-if="error && !data" class="dash-hint dash-error">{{error}}</div>
      <div v-else-if="!data" class="dash-hint">请先选择空间查看统计</div>
      <template v-else>
        <p v-if="usingMock" class="dash-mock-tip">接口未就绪，当前展示占位数据。</p>

        <!-- 指标卡 -->
        <div class="stat-grid">
          <div class="stat-card"><span class="stat-label">项目总数</span><span class="stat-value">{{data.projects.total}}</span><span class="stat-sub">进行中 {{data.projects.active}}</span></div>
          <div class="stat-card"><span class="stat-label">任务总数</span><span class="stat-value">{{data.tasks.total}}</span><span class="stat-sub">已完成 {{data.tasks.completion.completed}}</span></div>
          <div class="stat-card" :class="{warn: data.tasks.overdue > 0}"><span class="stat-label">逾期任务</span><span class="stat-value">{{data.tasks.overdue}}</span><span class="stat-sub">{{data.tasks.overdue > 0 ? '需要跟进' : '暂无逾期'}}</span></div>
          <div class="stat-card"><span class="stat-label">任务完成进度</span><span class="stat-value">{{data.tasks.completion.percent}}%</span><span class="stat-sub">{{data.tasks.completion.completed}} / {{data.tasks.completion.total}}</span></div>
        </div>

        <div class="chart-grid">
          <!-- 项目状态分布 -->
          <section class="panel">
            <h3>项目状态分布</h3>
            <div class="bar-list">
              <div v-for="(count, status) in data.projects.by_status" :key="status" class="bar-row">
                <span class="bar-label">{{projectStatusLabels[status] ?? status}}</span>
                <div class="bar-track"><div class="bar-fill project" :style="{width: barPercent(count, data.projects.total) + '%'}"></div></div>
                <span class="bar-count">{{count}}</span>
              </div>
            </div>
            <div class="ring-wrap">
              <svg viewBox="0 0 100 100" class="ring" role="img" :aria-label="`项目完成率 ${data.projects.completion.percent}%`">
                <circle cx="50" cy="50" r="42" class="ring-track"/>
                <circle cx="50" cy="50" r="42" class="ring-fill" :stroke-dasharray="`${data.projects.completion.percent / 100 * CIRCUMFERENCE} ${CIRCUMFERENCE}`"/>
                <text x="50" y="48" class="ring-text">{{data.projects.completion.percent}}%</text>
                <text x="50" y="62" class="ring-caption">项目完成率</text>
              </svg>
            </div>
          </section>

          <!-- 任务状态分布 -->
          <section class="panel">
            <h3>任务状态分布</h3>
            <div class="bar-list">
              <div v-for="(count, status) in data.tasks.by_status" :key="status" class="bar-row">
                <span class="bar-label">{{taskStatusLabels[status] ?? status}}</span>
                <div class="bar-track"><div class="bar-fill task" :style="{width: barPercent(count, data.tasks.total) + '%'}"></div></div>
                <span class="bar-count">{{count}}</span>
              </div>
            </div>
          </section>

          <!-- 每日完成任务趋势 -->
          <section class="panel wide">
            <h3>每日完成任务趋势 <span class="panel-hint">最近 14 天</span></h3>
            <svg viewBox="0 0 560 150" class="trend" role="img" aria-label="每日完成任务趋势柱状图">
              <template v-for="(d, i) in data.tasks.daily_completed" :key="d.date">
                <rect :x="20 + i * 38" :y="130 - (d.count / trendMax) * 100" :width="20" :height="(d.count / trendMax) * 100"
                      rx="3" class="trend-bar" :class="{zero: d.count === 0}">
                  <title>{{d.date}}：{{d.count}} 个任务完成</title>
                </rect>
                <text :x="20 + i * 38 + 10" y="144" class="trend-axis">{{d.date.slice(5).replace('-', '/')}}</text>
              </template>
            </svg>
          </section>

          <!-- 即将到期 -->
          <section class="panel">
            <h3>即将到期 <span class="panel-hint">未来 7 天</span></h3>
            <ul class="due-list">
              <li v-for="u in data.upcoming_due" :key="u.task_id" class="due-item">
                <span class="due-date">{{u.due_date}}</span>
                <span class="due-title">{{u.title}}</span>
                <span class="due-project">{{u.project_name}}</span>
              </li>
              <li v-if="data.upcoming_due.length === 0" class="due-empty">未来 7 天暂无到期任务</li>
            </ul>
          </section>

          <!-- 近期活动 -->
          <section class="panel">
            <h3>近期活动</h3>
            <ul class="activity-list">
              <li v-for="(a, i) in data.recent_activity" :key="i" class="activity-item">
                <span class="activity-dot"></span><span>{{(a as {action: string}).action}}</span>
              </li>
              <li v-if="data.recent_activity.length === 0" class="due-empty">暂无活动（协作模块合入后展示）</li>
            </ul>
          </section>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dash {min-height: 100vh; background: #fafafa;}
.dash-top {position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 12px; padding: 10px 24px; background: #fff; border-bottom: 1px solid #eee;}
.dash-back {cursor: pointer; border: 1px solid #ddd; background: #fff; border-radius: 6px; padding: 6px 12px;}
.dash-title {color: #333;}
.dash-space {margin-left: auto; padding: 6px 10px; border: 1px solid #ddd; border-radius: 6px; background: #fff;}
.dash-body {max-width: 1100px; margin: 0 auto; padding: 20px 24px 40px;}
.dash-hint {padding: 60px 0; text-align: center; color: #888;}
.dash-error {color: #c00;}
.dash-mock-tip {margin: 0 0 12px; padding: 8px 12px; background: #fff8e1; border: 1px solid #f0e0a0; border-radius: 6px; color: #8a6d00; font-size: 13px;}
.stat-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px;}
.stat-card {background: #fff; border: 1px solid #eee; border-radius: 10px; padding: 16px; display: flex; flex-direction: column;}
.stat-label {color: #888; font-size: 13px;}
.stat-value {font-size: 30px; font-weight: 700; color: #253052; margin: 4px 0;}
.stat-card.warn .stat-value {color: #c0392b;}
.stat-sub {color: #aaa; font-size: 12px;}
.chart-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px;}
.panel {background: #fff; border: 1px solid #eee; border-radius: 10px; padding: 16px;}
.panel.wide {grid-column: 1 / -1;}
.panel h3 {margin: 0 0 12px; font-size: 14px; color: #333;}
.panel-hint {color: #bbb; font-size: 12px; font-weight: 400;}
.bar-list {display: flex; flex-direction: column; gap: 8px;}
.bar-row {display: flex; align-items: center; gap: 8px; font-size: 13px;}
.bar-label {width: 56px; color: #555; flex-shrink: 0;}
.bar-track {flex: 1; height: 14px; background: #f0f1f6; border-radius: 7px; overflow: hidden;}
.bar-fill {height: 100%; border-radius: 7px; transition: width .3s;}
.bar-fill.project {background: #5454df;}
.bar-fill.task {background: #37a66c;}
.bar-count {width: 24px; text-align: right; color: #333; font-weight: 600;}
.ring-wrap {display: flex; justify-content: center; margin-top: 8px;}
.ring {width: 130px; height: 130px;}
.ring-track {fill: none; stroke: #f0f1f6; stroke-width: 8;}
.ring-fill {fill: none; stroke: #5454df; stroke-width: 8; stroke-linecap: round; transform: rotate(-90deg); transform-origin: 50% 50%;}
.ring-text {text-anchor: middle; font-size: 16px; font-weight: 700; fill: #253052;}
.ring-caption {text-anchor: middle; font-size: 8px; fill: #999;}
.trend {width: 100%; height: auto;}
.trend-bar {fill: #37a66c;}
.trend-bar.zero {fill: #e4e6ee;}
.trend-axis {text-anchor: middle; font-size: 8px; fill: #999;}
.due-list, .activity-list {list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px;}
.due-item {display: flex; align-items: baseline; gap: 8px; font-size: 13px;}
.due-date {color: #c0392b; font-variant-numeric: tabular-nums; flex-shrink: 0;}
.due-title {color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.due-project {margin-left: auto; color: #999; font-size: 12px; flex-shrink: 0;}
.due-empty {color: #999; font-size: 13px; padding: 8px 0;}
.activity-item {display: flex; align-items: center; gap: 8px; font-size: 13px; color: #444;}
.activity-dot {width: 8px; height: 8px; border-radius: 50%; background: #37a66c; flex-shrink: 0;}
</style>
