<script setup lang="ts">
import {computed, nextTick, onMounted, onUnmounted, reactive, ref, watch} from 'vue';
import {useRoute, useRouter} from 'vue-router';
import {ApiError, request, type User} from './api';
const props=defineProps<{user:User;authBusy:boolean}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[];'switch-view':[];'switch-tasks':[];'switch-dashboard':[];'switch-activities':[workspaceId:number];'switch-files':[];'switch-ai':[]}>();
type Role='Owner'|'Admin'|'Member';
type Member={user_id:number;username:string;email:string;role:Role;created_at:string};
type Workspace={id:number;name:string;description:string;created_at:string;updated_at:string;role:Role};
type WorkspaceDetail=Workspace&{members:Member[]};
const roleLabels:Record<Role,string>={Owner:'所有者',Admin:'管理员',Member:'成员'};
const route=useRoute(),router=useRouter();
const spaces=ref<Workspace[]>([]),loading=ref(true),loadError=ref(''),toast=ref('');
const selected=ref<WorkspaceDetail|null>(null),detailLoading=ref(false);
const isDetail=computed(()=>route.params.id!==undefined);
const createOpen=ref(false),saving=ref(false),formError=ref('');
const createForm=reactive({name:'',description:''});
const editOpen=ref(false),editForm=reactive({name:'',description:''});
const addOpen=ref(false),addForm=reactive({email:'',role:'Member' as Role}),adding=ref(false);
const editor=ref<HTMLDialogElement>(),adder=ref<HTMLDialogElement>(),nameInput=ref<HTMLInputElement>();
const canManage=computed(()=>!!selected.value&&['Owner','Admin'].includes(selected.value.role));
const canAdjust=computed(()=>selected.value?.role==='Owner');
const wsName=computed({get:()=>createOpen.value?createForm.name:editForm.name,set:(v:string)=>{if(createOpen.value)createForm.name=v;else editForm.name=v;}});
const wsDescription=computed({get:()=>createOpen.value?createForm.description:editForm.description,set:(v:string)=>{if(createOpen.value)createForm.description=v;else editForm.description=v;}});
const ownedCount=computed(()=>spaces.value.filter(s=>s.role==='Owner').length);
const managedCount=computed(()=>spaces.value.filter(s=>s.role!=='Member').length);
let toastTimer:ReturnType<typeof setTimeout>;
function notify(message:string){toast.value=message;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4000);}
async function api(path:string,method='GET',body?:unknown){
 try{return await request(path,method,body,{'X-FlowDesk-User':String(props.user.id)});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function load(){loading.value=true;loadError.value='';try{spaces.value=await api('/workspaces');}catch(e){loadError.value=(e as Error).message;}finally{loading.value=false;}}
async function loadDetail(id:number){detailLoading.value=true;try{selected.value=await api(`/workspaces/${id}`);}catch(e){notify((e as Error).message);selected.value=null;router.push('/workspaces');}finally{detailLoading.value=false;}}
function openCreate(){createOpen.value=true;formError.value='';Object.assign(createForm,{name:'',description:''});nextTick(()=>{editor.value?.showModal();nameInput.value?.focus();});}
function closeCreate(){if(!saving.value){editor.value?.close();createOpen.value=false;}}
async function createSpace(){
 formError.value='';
 if(!createForm.name.trim()){formError.value='请填写空间名称。';nameInput.value?.focus();return;}
 saving.value=true;
 try{const ws:Workspace=await api('/workspaces','POST',{name:createForm.name.trim(),description:createForm.description.trim()});spaces.value.unshift(ws);notify('空间已创建');closeCreate();router.push(`/workspaces/${ws.id}`);}
 catch(e){formError.value=(e as Error).message;}finally{saving.value=false;}
}
function openEdit(){if(!selected.value)return;editOpen.value=true;formError.value='';Object.assign(editForm,{name:selected.value.name,description:selected.value.description});nextTick(()=>editor.value?.showModal());}
function closeEdit(){if(!saving.value){editor.value?.close();editOpen.value=false;}}
async function saveEdit(){
 if(!selected.value)return;formError.value='';
 if(!editForm.name.trim()){formError.value='空间名称不能为空。';return;}
 saving.value=true;
 try{const updated:Workspace=await api(`/workspaces/${selected.value.id}`,'PATCH',{name:editForm.name.trim(),description:editForm.description.trim()});selected.value={...selected.value,...updated};const idx=spaces.value.findIndex(s=>s.id===updated.id);if(idx>=0)spaces.value[idx]={...spaces.value[idx],...updated};notify('空间信息已保存');closeEdit();}
 catch(e){formError.value=(e as Error).message;}finally{saving.value=false;}
}
function openAdd(){addOpen.value=true;formError.value='';Object.assign(addForm,{email:'',role:'Member'});nextTick(()=>adder.value?.showModal());}
function closeAdd(){if(!adding.value){adder.value?.close();addOpen.value=false;}}
async function addMember(){
 if(!selected.value)return;formError.value='';
 if(!addForm.email.trim()){formError.value='请填写成员邮箱。';return;}
 adding.value=true;
 try{const m:Member=await api(`/workspaces/${selected.value.id}/members`,'POST',{email:addForm.email.trim(),role:addForm.role});selected.value.members.push(m);selected.value.members.sort((a,b)=>a.user_id-b.user_id);notify(`已添加成员 ${m.email}`);closeAdd();}
 catch(e){formError.value=(e as Error).message;}finally{adding.value=false;}
}
async function changeRole(m:Member,role:Role){
 if(!selected.value)return;
 try{const updated:Member=await api(`/workspaces/${selected.value.id}/members/${m.user_id}`,'PATCH',{role});Object.assign(m,updated);notify(`已调整 ${m.username} 的角色`);}
 catch(e){notify((e as Error).message);await loadDetail(selected.value.id);}
}
async function removeMember(m:Member){
 if(!selected.value)return;
 try{await api(`/workspaces/${selected.value.id}/members/${m.user_id}`,'DELETE');selected.value.members=selected.value.members.filter(x=>x.user_id!==m.user_id);notify(`已移除成员 ${m.username||m.email}`);}
 catch(e){notify((e as Error).message);}
}
function showList(){router.push('/workspaces');}
const initials=(name:string)=>Array.from(name.trim()).slice(0,2).join('').toUpperCase();
const timeLabel=(value:string)=>new Date(value.endsWith('Z')||/[+-]\d\d:\d\d$/.test(value)?value:value+'Z').toLocaleString('zh-CN',{hour12:false});
watch(()=>route.params.id,(id)=>{if(id!==undefined)void loadDetail(Number(id));else selected.value=null;});
watch(()=>route.fullPath,()=>window.scrollTo({top:0}));
onMounted(()=>{load();if(route.params.id!==undefined)void loadDetail(Number(route.params.id));});
onUnmounted(()=>{clearTimeout(toastTimer);});
</script>

<template>
 <div class="app-shell">
  <aside class="sidebar">
   <a class="brand" href="#/" @click="emit('switch-view')"><span class="brand-mark">F<span></span></span>FlowDesk<span class="version">M3</span></a>
   <div class="space"><span class="space-icon">W</span><div><strong>我的协作空间</strong><small>TEAM WORKSPACE</small></div><span class="local-dot"></span></div>
   <div class="nav-label">工作台</div>
   <button class="nav-item" @click="emit('switch-view')"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>项目</button>
   <button class="nav-item active" @click="showList"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="10" rx="2"/><path d="M8 18h8M12 14v4"/></svg>空间 <span class="nav-count">{{spaces.length}}</span></button>
   <button class="nav-item" @click="emit('switch-tasks')"><svg viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>任务</button>
   <button class="nav-item" @click="emit('switch-dashboard')"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>仪表盘</button>
   <button class="nav-item" @click="emit('switch-files')"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>文件</button>
   <button class="nav-item" @click="emit('switch-ai')"><svg viewBox="0 0 24 24"><path d="M12 2a4 4 0 0 1 4 4c0 .6-.13 1.17-.37 1.68A6 6 0 0 1 18 13c0 .8-.16 1.57-.45 2.27A5 5 0 0 1 20 19v2h-2v-2a3 3 0 0 0-6 0v2h-2v-2a3 3 0 0 0-6 0v2H2v-2a5 5 0 0 1 2.45-3.73A6.3 6.3 0 0 1 4 13a6 6 0 0 1 6.37-5.32A4 4 0 0 1 12 2z"/></svg>AI 助手</button>
   <div class="sidebar-bottom"><div class="offline"><span class="local-dot"></span> 本地运行 · 数据保存在此电脑</div><button class="profile profile-button" aria-label="查看当前账号" @click="emit('account')"><span class="avatar">{{Array.from(user.username).slice(0,1).join('')}}</span><div><strong>{{user.username}}</strong><small>{{user.email}}</small></div><span class="profile-arrow">↗</span></button></div>
  </aside>

  <div class="workspace">
   <header class="topbar"><div class="breadcrumb"><span>工作台</span><b>/</b><button @click="emit('switch-view')">项目</button><template v-if="isDetail"><b>/</b><span class="crumb-name">{{selected?.name||'空间详情'}}</span></template></div><div class="top-right"><span class="local-pill"><i class="local-dot"></i>本地版</span><button class="account-chip" aria-label="查看当前账号" @click="emit('account')"><span class="avatar small">{{Array.from(user.username).slice(0,1).join('')}}</span><span>{{user.username}}</span></button><button class="logout-link" :disabled="authBusy" @click="emit('logout')">{{authBusy?'退出中…':'退出登录'}}</button></div></header>
   <main>
    <div v-if="loading" class="state-panel" role="status"><span class="spinner"></span><h2>正在读取空间</h2><p>连接你的本地工作台…</p></div>
    <div v-else-if="loadError" class="state-panel"><h2>暂时无法加载空间</h2><p role="alert">{{loadError}}</p><button class="primary" @click="load">重新连接</button></div>
    <template v-else-if="!isDetail">
     <div class="heading"><div><div class="eyebrow">TEAM SPACES</div><h1>空间<span class="heading-count">{{spaces.length}}</span></h1><p>把成员、项目与任务组织进同一个空间。</p></div><button class="primary" @click="openCreate"><span class="plus">＋</span>新建空间</button></div>
     <section class="summary" aria-label="空间概况"><div><span class="summary-icon purple">W</span><div><small>全部空间</small><strong>{{spaces.length}}<em>个空间</em></strong></div></div><div><span class="summary-icon blue">★</span><div><small>我管理的</small><strong>{{managedCount}}<em>个空间</em></strong></div></div><div><span class="summary-icon green">♢</span><div><small>我是所有者</small><strong>{{ownedCount}}<em>个空间</em></strong></div></div><div><span class="summary-icon orange">＋</span><div><small>开始协作</small><strong>邀请<em>成员加入</em></strong></div></div></section>
     <section class="project-area">
      <div class="section-title"><h2>空间一览</h2><button class="text-action" @click="load">↻ 刷新</button></div>
      <div v-if="spaces.length===0" class="empty"><div class="empty-art"><span>W</span></div><h2>创建你的第一个协作空间</h2><p>空间是成员、项目与任务的容器——先建一个空间，再邀请伙伴加入。</p><button class="primary" @click="openCreate">＋ 创建第一个空间</button><small>创建者自动成为空间所有者（Owner）。</small></div>
      <div v-else class="projects grid">
       <article v-for="s in spaces" :key="s.id" class="project-card">
        <div class="card-top"><span class="project-icon" :class="'color-'+s.id%4">{{initials(s.name)}}</span><span class="role-badge" :class="'role-'+s.role">{{roleLabels[s.role as Role]}}</span></div>
        <div class="card-copy"><h3><a :href="`#/workspaces/${s.id}`">{{s.name}}</a></h3><p>{{s.description||'还没有空间描述。'}}</p></div>
        <div class="space-meta"><span>我的角色：{{roleLabels[s.role as Role]}}</span><span>创建于 {{timeLabel(s.created_at)}}</span></div>
        <div class="card-footer"><a :href="`#/workspaces/${s.id}`">进入空间 <span>↗</span></a></div>
       </article>
       <button class="new-card" @click="openCreate"><span>＋</span><strong>创建一个新空间</strong><small>把团队组织起来</small></button>
      </div>
      <div class="list-bottom"><span>显示 {{spaces.length}} 个空间</span><span>空间是你的团队协作的起点。</span></div>
     </section>
    </template>
    <template v-else-if="selected">
     <button class="back-link" @click="showList">← 返回空间列表</button>
     <div class="heading detail-heading"><div class="detail-title"><span class="project-icon big" :class="'color-'+selected.id%4">{{initials(selected.name)}}</span><div><span class="eyebrow">WORKSPACE OVERVIEW</span><h1>{{selected.name}}</h1></div></div><div style="display:flex;gap:8px"><button class="secondary" @click="emit('switch-activities', selected.id)">活动</button><button v-if="canManage" class="primary" @click="openEdit">编辑空间</button></div></div>
     <div class="detail-grid"><section class="detail-main"><div class="detail-tabs">空间概览</div><div class="detail-content"><h2>空间描述</h2><p class="description" :class="{muted:!selected.description}">{{selected.description||'这个空间还没有描述。点击“编辑空间”，补充目标与协作说明。'}}</p><div class="detail-note"><span>◇</span><div><strong>空间是协作的边界</strong><p>只有空间成员才能看到这里的内容；权限由角色控制。</p></div></div></div></section><aside class="detail-meta"><h2>空间信息</h2><dl><dt>我的角色</dt><dd><span class="role-badge" :class="'role-'+selected.role">{{roleLabels[selected.role as Role]}}</span></dd><dt>成员数量</dt><dd>{{selected.members.length}} 人</dd><dt>创建时间</dt><dd>{{timeLabel(selected.created_at)}}</dd><dt>最后更新</dt><dd>{{timeLabel(selected.updated_at)}}</dd><dt>空间编号</dt><dd class="mono">WS-{{String(selected.id).padStart(4,'0')}}</dd></dl></aside></div>
     <section class="project-area" style="margin-top:28px">
      <div class="section-title"><h2>成员 <span class="heading-count" style="padding:0 8px;border-radius:7px;background:#eaeaf4;color:#85829d;font-size:12px">{{selected.members.length}}</span></h2><button v-if="canManage" class="primary" @click="openAdd"><span class="plus">＋</span>添加成员</button></div>
      <div v-if="detailLoading" class="state-panel" style="min-height:120px"><span class="spinner"></span></div>
      <div v-else class="member-list">
       <div v-for="m in selected.members" :key="m.user_id" class="member-row">
        <span class="avatar">{{Array.from(m.username).slice(0,1).join('')}}</span>
        <div class="member-main"><strong>{{m.username}}{{m.user_id===user.id?'（我）':''}}</strong><small>{{m.email}}</small></div>
        <div class="member-actions">
         <span class="role-badge" :class="'role-'+m.role">{{roleLabels[m.role as Role]}}</span>
         <select v-if="canAdjust&&m.role!=='Owner'&&m.user_id!==user.id" class="role-select" :value="m.role" @change="changeRole(m,($event.target as HTMLSelectElement).value as Role)" :aria-label="`调整 ${m.username} 的角色`">
          <option value="Admin">管理员</option><option value="Member">成员</option>
         </select>
         <button v-if="canManage&&m.role!=='Owner'" class="member-remove" @click="removeMember(m)">移除</button>
        </div>
       </div>
      </div>
      <div class="list-bottom"><span>角色说明：Owner 可管理一切；Admin 可改空间与成员；Member 只读。</span></div>
     </section>
    </template>
    <div v-else class="state-panel"><h2>空间不存在</h2><p>空间可能已被删除，或链接地址不正确。</p><button class="primary" @click="showList">返回空间列表</button></div>
    <footer>FlowDesk <span>·</span> 为专注的工作，留一个清晰的空间。</footer>
   </main>
  </div>
 </div>

 <dialog ref="editor" class="editor" aria-labelledby="editor-title" @cancel.prevent="createOpen?closeCreate():closeEdit()">
  <form v-if="createOpen||editOpen" @submit.prevent="createOpen?createSpace():saveEdit()"><div class="modal-heading"><div><div class="eyebrow">WORKSPACE</div><h2 id="editor-title">{{createOpen?'新建空间':'编辑空间'}}</h2></div><button type="button" class="close" aria-label="关闭" :disabled="saving" @click="createOpen?closeCreate():closeEdit()">×</button></div><p class="modal-intro">{{createOpen?'空间是团队协作的容器——创建者自动成为所有者。':'更新空间名称与描述。'}}</p>
   <fieldset :disabled="saving"><label for="ws-name">空间名称 <span class="required">*</span></label><input id="ws-name" ref="nameInput" v-model="wsName" required maxlength="80" placeholder="例如：FlowDesk 团队" autocomplete="off"><div class="field-hint">清晰的空间名称，方便团队识别 <span>{{wsName.length}}/80</span></div>
   <label for="ws-description">空间描述 <span class="optional">选填</span></label><textarea id="ws-description" v-model="wsDescription" rows="4" maxlength="1000" placeholder="这个空间用来做什么？记录协作目标或说明…"></textarea></fieldset>
   <p v-if="formError" class="error" role="alert">{{formError}}</p><div class="modal-footer"><span>* 为必填项</span><div><button class="secondary" type="button" :disabled="saving" @click="createOpen?closeCreate():closeEdit()">取消</button><button class="primary" type="submit" :disabled="saving">{{saving?'正在保存…':createOpen?'创建空间':'保存修改'}}</button></div></div>
  </form>
 </dialog>
 <dialog ref="adder" class="editor" aria-labelledby="adder-title" @cancel.prevent="closeAdd">
  <form v-if="addOpen" @submit.prevent="addMember"><div class="modal-heading"><div><div class="eyebrow">MEMBER</div><h2 id="adder-title">添加成员</h2></div><button type="button" class="close" aria-label="关闭" :disabled="adding" @click="closeAdd">×</button></div><p class="modal-intro">按邮箱邀请成员——对方需要有 FlowDesk 账号。</p>
   <fieldset :disabled="adding"><label for="member-email">成员邮箱 <span class="required">*</span></label><input id="member-email" v-model="addForm.email" type="email" required maxlength="254" placeholder="name@example.com" spellcheck="false" autocapitalize="none">
   <label for="member-role">初始角色</label><select id="member-role" v-model="addForm.role"><option value="Member">成员 · 只读</option><option value="Admin">管理员 · 可管理空间与成员</option></select></fieldset>
   <p v-if="formError" class="error" role="alert">{{formError}}</p><div class="modal-footer"><span>角色之后可由空间所有者调整</span><div><button class="secondary" type="button" :disabled="adding" @click="closeAdd">取消</button><button class="primary" type="submit" :disabled="adding">{{adding?'正在添加…':'添加成员'}}</button></div></div>
  </form>
 </dialog>
 <Transition name="toast"><div v-if="toast" class="toast-message" role="status"><span>✓</span>{{toast}}</div></Transition>
</template>
