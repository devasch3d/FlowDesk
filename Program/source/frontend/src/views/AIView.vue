<script setup lang="ts">
import {onMounted, reactive, ref} from 'vue';
import {ApiError, request, type User} from '../api';

const props = defineProps<{user: User}>();
const emit = defineEmits<{logout: []; account: []; 'session-lost': []}>();

type AiMessage = {id: number; conversation_id: number; role: 'user' | 'assistant'; content: string; created_at: string};
type AiConversation = {id: number; user_id: number; workspace_id: number | null; project_id: number | null; title: string; created_at: string; updated_at: string};
type Proposal = {title: string; description: string; priority: string; status: string; due_date: string | null};
type Bubble = {role: 'user' | 'assistant' | 'error'; content: string};
type Project = {id: number; name: string; workspace_id: number | null};

const conversations = ref<AiConversation[]>([]);
const currentId = ref<number | null>(null);
const bubbles = ref<Bubble[]>([]);
const input = ref('');
const sending = ref(false);
const loading = ref(false);
const error = ref('');
const toast = ref('');
const projects = ref<Project[]>([]);
const proposalProject = ref<number | null>(null);
const proposalInstruction = ref('');
const generating = ref(false);
const proposals = ref<(Proposal & {checked: boolean})[]>([]);
const creating = ref(false);
const settingsOpen = ref(false);
const settings = reactive({base_url: '', model: '', api_key: '', enabled: false});
let toastTimer: ReturnType<typeof setTimeout>;

function notify(m: string) {toast.value = m; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 4000);}

async function api(path: string, method = 'GET', body?: unknown) {
  try {
    return await request(path, method, body, {'X-FlowDesk-User': String(props.user.id)});
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || (e.status === 409 && e.message.includes('账号已')))) emit('session-lost');
    throw e;
  }
}

async function loadConversations() {
  loading.value = true; error.value = '';
  try {conversations.value = await api('/ai/conversations');}
  catch (e) {error.value = (e as Error).message;}
  finally {loading.value = false;}
}

async function selectConversation(id: number) {
  currentId.value = id;
  try {
    const detail = await api(`/ai/conversations/${id}`);
    bubbles.value = (detail.messages as AiMessage[]).map(m => ({role: m.role, content: m.content}));
    error.value = '';
  } catch (e) {error.value = (e as Error).message;}
}

async function createConversation() {
  try {
    const conv = await api('/ai/conversations', 'POST', {});
    await loadConversations();
    await selectConversation(conv.id);
  } catch (e) {error.value = (e as Error).message;}
}

async function removeConversation(id: number) {
  try {
    await api(`/ai/conversations/${id}`, 'DELETE');
    if (currentId.value === id) {currentId.value = null; bubbles.value = [];}
    await loadConversations();
  } catch (e) {error.value = (e as Error).message;}
}

async function send() {
  const text = input.value.trim();
  if (!text || sending.value || currentId.value === null) return;
  input.value = '';
  bubbles.value.push({role: 'user', content: text});
  sending.value = true;
  try {
    const r = await api(`/ai/conversations/${currentId.value}/messages`, 'POST', {content: text});
    if (r.assistant_message) bubbles.value.push({role: 'assistant', content: r.assistant_message.content});
    else if (r.reply_error) bubbles.value.push({role: 'error', content: r.reply_error});
  } catch (e) {
    bubbles.value.push({role: 'error', content: (e as Error).message});
  } finally {sending.value = false;}
}

async function openSettings() {
  settingsOpen.value = true;
  try {
    const s = await api('/ai/settings');
    settings.base_url = s.base_url || '';
    settings.model = s.model || '';
    settings.api_key = '';
    settings.enabled = !!s.enabled;
  } catch (e) {notify((e as Error).message);}
}

async function saveSettings() {
  try {
    const payload: Record<string, unknown> = {base_url: settings.base_url, model: settings.model, enabled: settings.enabled};
    if (settings.api_key.trim()) payload.api_key = settings.api_key.trim();
    await api('/ai/settings', 'PUT', payload);
    settingsOpen.value = false;
    notify('AI 设置已保存');
  } catch (e) {notify((e as Error).message);}
}

async function generateProposals() {
  if (currentId.value === null || proposalProject.value === null || generating.value) return;
  const instruction = proposalInstruction.value.trim();
  if (!instruction) {notify('请先输入任务目标描述'); return;}
  generating.value = true;
  try {
    const r = await api(`/ai/conversations/${currentId.value}/proposals`, 'POST', {instruction, project_id: proposalProject.value});
    if (r.reply_error) bubbles.value.push({role: 'error', content: r.reply_error});
    proposals.value = (r.proposals || []).map((p: Proposal) => ({...p, checked: true}));
    if (r.skipped > 0) notify(`已忽略 ${r.skipped} 条不合规的提案`);
    proposalInstruction.value = '';
  } catch (e) {
    bubbles.value.push({role: 'error', content: (e as Error).message});
  } finally {generating.value = false;}
}

async function confirmProposals() {
  const selected = proposals.value.filter(p => p.checked);
  if (!selected.length || proposalProject.value === null || creating.value) return;
  creating.value = true;
  let created = 0;
  try {
    for (const p of selected) {
      await api(`/projects/${proposalProject.value}/tasks`, 'POST', {
        title: p.title, description: p.description || '', priority: p.priority, status: p.status, due_date: p.due_date || null,
      });
      created++;
    }
    proposals.value = [];
    notify(`已创建 ${created} 个任务`);
  } catch (e) {notify((e as Error).message);}
  finally {creating.value = false;}
}

onMounted(async () => {
  await loadConversations();
  try {projects.value = await api('/projects');} catch {/* 无项目时提案区自动不可用 */}
});
</script>

<template>
 <div class="ai-view" style="display:flex;min-height:100vh;background:#fafafa">
  <aside style="width:260px;min-width:260px;background:#fff;border-right:1px solid #eee;display:flex;flex-direction:column">
   <div style="padding:14px 16px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #eee">
    <strong style="color:#333">AI 助手</strong>
    <button class="primary" style="margin-left:auto;padding:4px 10px;font-size:12px" @click="createConversation">＋ 新建会话</button>
   </div>
   <div style="flex:1;overflow:auto">
    <div v-if="loading" style="padding:24px;text-align:center;color:#888">加载中…</div>
    <div v-else-if="error" style="padding:16px;color:#c00;font-size:13px">{{error}}</div>
    <div v-else-if="!conversations.length" style="padding:24px;text-align:center;color:#888">还没有会话，点击左上角新建</div>
    <div v-for="conv in conversations" :key="conv.id" :style="{padding:'10px 16px',cursor:'pointer',borderBottom:'1px solid #f2f2f2',background:conv.id===currentId?'#eef2ff':'#fff'}" @click="selectConversation(conv.id)">
     <div style="display:flex;align-items:center;gap:6px">
      <span style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{conv.title}}</span>
      <button style="border:none;background:none;color:#c00;cursor:pointer;font-size:12px" @click.stop="removeConversation(conv.id)">×</button>
     </div>
    </div>
   </div>
  </aside>
  <main style="flex:1;display:flex;flex-direction:column;min-width:0">
   <header style="display:flex;align-items:center;gap:8px;padding:10px 20px;background:#fff;border-bottom:1px solid #eee">
    <button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="emit('logout')">退出</button>
    <span style="color:#888;font-size:13px;margin-left:auto">{{currentId ? '会话中' : '选择一个会话开始'}}</span>
    <button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="openSettings">设置</button>
   </header>
   <div style="flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:10px">
    <div v-if="!currentId" style="padding:60px;text-align:center;color:#888">新建或选择一个会话，开始与 AI 对话</div>
    <template v-else>
     <div v-for="(b, i) in bubbles" :key="i" :style="{maxWidth:'72%',alignSelf:b.role==='user'?'flex-end':'flex-start',padding:'8px 12px',borderRadius:'10px',whiteSpace:'pre-wrap',wordBreak:'break-word',fontSize:'14px',background:b.role==='user'?'#dbeafe':b.role==='error'?'#f3f4f6':'#fff',border:b.role==='error'?'1px solid #e5e7eb':'1px solid #e5e7eb',color:b.role==='error'?'#6b7280':'#1f2937'}">{{b.content}}</div>
    </template>
   </div>
   <div style="padding:14px 20px;border-top:1px solid #eee;background:#fff">
    <div v-if="currentId" style="margin-bottom:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
     <span style="font-size:13px;color:#666">任务提案：</span>
     <select :value="proposalProject ?? ''" @change="proposalProject = Number(($event.target as HTMLSelectElement).value) || null" style="padding:4px">
      <option value="">选择项目…</option>
      <option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}}</option>
     </select>
     <input v-model="proposalInstruction" style="flex:1;min-width:200px;padding:6px" maxlength="2000" placeholder="描述目标，例如：为项目做发布前准备">
     <button :disabled="generating" style="padding:6px 12px" @click="generateProposals">{{generating ? '生成中…' : '生成提案'}}</button>
    </div>
    <div v-if="proposals.length" style="margin-bottom:10px;border:1px solid #e5e7eb;border-radius:8px;padding:10px;background:#f9fafb">
     <div style="font-size:13px;font-weight:700;margin-bottom:8px">任务提案（勾选后确认创建）</div>
     <div v-for="(p, i) in proposals" :key="i" style="display:flex;gap:8px;align-items:start;padding:6px 0;border-bottom:1px solid #f2f2f2">
      <input v-model="p.checked" type="checkbox">
      <div style="flex:1;font-size:13px">
       <strong>{{p.title}}</strong>
       <div style="color:#888;font-size:12px">{{p.description || '—'}}</div>
       <div style="color:#888;font-size:12px">优先级 {{p.priority}} · 状态 {{p.status}}<span v-if="p.due_date"> · 截止 {{p.due_date}}</span></div>
      </div>
     </div>
     <button class="primary" :disabled="creating" style="margin-top:8px" @click="confirmProposals">{{creating ? '创建中…' : '确认创建选中任务'}}</button>
    </div>
    <div style="display:flex;gap:8px">
     <input v-model="input" :disabled="sending || !currentId" style="flex:1;padding:8px" maxlength="10000" placeholder="输入消息，回车发送" @keydown.enter="send">
     <button class="primary" :disabled="sending || !currentId" @click="send">{{sending ? '回复中…' : '发送'}}</button>
    </div>
   </div>
  </main>
  <dialog v-if="settingsOpen" style="border:none;border-radius:12px;padding:24px;min-width:420px" @cancel="settingsOpen=false">
   <div style="display:flex;align-items:center;margin-bottom:12px"><h2 style="margin:0">AI 设置</h2><button style="margin-left:auto;border:none;background:none;font-size:16px;cursor:pointer" @click="settingsOpen=false">×</button></div>
   <form @submit.prevent="saveSettings">
    <label style="display:block;font-size:13px;margin-bottom:4px">API Base URL</label>
    <input v-model="settings.base_url" style="width:100%;margin-bottom:10px;padding:6px" placeholder="https://api.openai.com/v1">
    <label style="display:block;font-size:13px;margin-bottom:4px">模型</label>
    <input v-model="settings.model" style="width:100%;margin-bottom:10px;padding:6px" placeholder="gpt-4o-mini">
    <label style="display:block;font-size:13px;margin-bottom:4px">API Key（留空表示保留原值，不回显）</label>
    <input v-model="settings.api_key" type="password" style="width:100%;margin-bottom:10px;padding:6px" placeholder="sk-…">
    <label style="display:flex;gap:6px;align-items:center;font-size:13px;margin-bottom:12px"><input v-model="settings.enabled" type="checkbox"><span>启用 AI 对话</span></label>
    <div style="display:flex;gap:8px;justify-content:flex-end">
     <button type="button" @click="settingsOpen=false">取消</button>
     <button class="primary" type="submit">保存</button>
    </div>
   </form>
  </dialog>
  <Transition name="toast"><div v-if="toast" style="position:fixed;bottom:24px;right:24px;background:#333;color:#fff;padding:8px 16px;border-radius:8px;z-index:20">{{toast}}</div></Transition>
 </div>
</template>
