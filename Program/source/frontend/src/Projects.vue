<script setup lang="ts">
import {computed, nextTick, onMounted, onUnmounted, reactive, ref, watch} from 'vue';
import {useRoute, useRouter} from 'vue-router';
import {ApiError,request,type User} from './api';
const props=defineProps<{user:User;authBusy:boolean}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[];'switch-view':[]}>();
type Status = 'Planning'|'Active'|'Paused'|'Completed'|'Archived';
type Input = {workspace_id:number|null;name:string;description:string;status:Status;start_date:string|null;deadline:string|null};
type Project = Input & {id:number;owner_id:number|null;created_at:string;updated_at:string;version:number};
type Workspace = {id:number;name:string;description:string;role:string};
const labels:Record<Status,string>={Planning:'计划中',Active:'进行中',Paused:'已暂停',Completed:'已完成',Archived:'已归档'};
const statuses=Object.keys(labels) as Status[];
const route=useRoute(), router=useRouter();
const projects=ref<Project[]>([]), loading=ref(true), loadError=ref(''), toast=ref('');
const workspaces=ref<Workspace[]>([]);
const search=ref(''), filter=ref('all'), sort=ref('updated'), layout=ref('grid');
const modal=ref(false), saving=ref(false), deleting=ref(false), formError=ref(''), deleteError=ref(''), editing=ref<Project|null>(null), deleteTarget=ref<Project|null>(null);
const form=reactive<Input>({workspace_id:null,name:'',description:'',status:'Planning',start_date:null,deadline:null});
const editor=ref<HTMLDialogElement>(), confirmer=ref<HTMLDialogElement>(), nameInput=ref<HTMLInputElement>();
const selected=computed(()=>projects.value.find(p=>p.id===Number(route.params.id)));
const isDetail=computed(()=>route.params.id!==undefined);
const filtered=computed(()=>{
 const term=search.value.trim().toLocaleLowerCase();
 let items=projects.value.filter(p=>(filter.value==='all'||p.status===filter.value)&&(!term||`${p.name} ${p.description}`.toLocaleLowerCase().includes(term)));
 return items.sort((a,b)=>sort.value==='name'?a.name.localeCompare(b.name,'zh-CN'):sort.value==='deadline'?(a.deadline||'9999').localeCompare(b.deadline||'9999'):b.updated_at.localeCompare(a.updated_at)||b.id-a.id);
});
const counts=computed(()=>Object.fromEntries(statuses.map(s=>[s,projects.value.filter(p=>p.status===s).length])));
const countActive=computed(()=>projects.value.filter(p=>p.status==='Active').length);
const dayNow=ref(new Date().toLocaleDateString('en-CA'));
const updateDay=()=>{ const d=new Date(); dayNow.value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const overdue=(p:Input)=>!!p.deadline&&p.deadline<dayNow.value&&!['Completed','Archived'].includes(p.status);
const dateLabel=(value:string|null)=>value?value.replaceAll('-','.'): '未设置';
const timeLabel=(value:string)=>new Date(value.endsWith('Z')||/[+-]\d\d:\d\d$/.test(value)?value:value+'Z').toLocaleString('zh-CN',{hour12:false});
const initials=(name:string)=>Array.from(name.trim()).slice(0,2).join('').toUpperCase();
let toastTimer:ReturnType<typeof setTimeout>, clockTimer:ReturnType<typeof setInterval>;
function notify(message:string){toast.value=message;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4000);}
async function api(path:string,method='GET',body?:unknown,version?:number){
 try{return await request(path,method,body,{'X-FlowDesk-User':String(props.user.id),...(version?{'If-Match':String(version)}:{})});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function exportProjects(){
 try{const data=await api('/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='FlowDesk-projects.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 catch(e){notify((e as Error).message);}
}
async function load(){loading.value=true;loadError.value='';try{[projects.value,workspaces.value]=await Promise.all([api('/projects'),api('/workspaces')]);}catch(e){loadError.value=(e as Error).message;}finally{loading.value=false;}}
function openCreate(){editing.value=null;Object.assign(form,{workspace_id:workspaces.value[0]?.id??null,name:'',description:'',status:'Planning',start_date:null,deadline:null});showEditor();}
function openEdit(p:Project){editing.value={...p};Object.assign(form,{workspace_id:p.workspace_id,name:p.name,description:p.description,status:p.status,start_date:p.start_date,deadline:p.deadline});showEditor();}
function showEditor(){formError.value='';modal.value=true;nextTick(()=>{editor.value?.showModal();nameInput.value?.focus();});}
function closeEditor(){if(!saving.value){editor.value?.close();modal.value=false;}}
async function save(){
 formError.value='';
 if(!form.name.trim()){formError.value='请填写项目名称，不能只包含空格。';nameInput.value?.focus();return;}
 if(form.start_date&&form.deadline&&form.deadline<form.start_date){formError.value='截止日期不能早于开始日期。';return;}
 saving.value=true;
 try{
  const payload={...form,name:form.name.trim(),description:form.description.trim(),start_date:form.start_date||null,deadline:form.deadline||null};
  const result:Project=await api(editing.value?`/projects/${editing.value.id}`:'/projects',editing.value?'PATCH':'POST',payload,editing.value?.version);
  const idx=projects.value.findIndex(p=>p.id===result.id);if(idx<0)projects.value.unshift(result);else projects.value[idx]=result;
  notify(editing.value?'项目修改已保存':'项目已创建');saving.value=false;closeEditor();
  if(!editing.value){filter.value='all';search.value='';router.push(`/projects/${result.id}`);}
 }catch(e){formError.value=(e as Error).message;}finally{saving.value=false;}
}
function askDelete(p:Project){deleteTarget.value=p;deleteError.value='';nextTick(()=>confirmer.value?.showModal());}
function closeDelete(){if(!deleting.value){confirmer.value?.close();deleteTarget.value=null;}}
async function remove(){if(!deleteTarget.value)return;deleting.value=true;try{const id=deleteTarget.value.id;await api(`/projects/${id}`,'DELETE',undefined,deleteTarget.value.version);projects.value=projects.value.filter(p=>p.id!==id);deleting.value=false;closeDelete();if(isDetail.value)router.push('/');notify('项目已删除');}catch(e){deleteError.value=(e as Error).message;}finally{deleting.value=false;}}
function showAll(){filter.value='all';search.value='';router.push('/');}
function chooseStatus(s:string){filter.value=s;router.push('/');}
watch(()=>route.fullPath,()=>window.scrollTo({top:0}));
onMounted(()=>{load();updateDay();clockTimer=setInterval(updateDay,60000);});
onUnmounted(()=>{clearInterval(clockTimer);clearTimeout(toastTimer);});
</script>

<template>
 <div class="app-shell">
  <aside class="sidebar">
   <a class="brand" href="#/" @click="showAll"><span class="brand-mark">F<span></span></span>FlowDesk<span class="version">M2</span></a>
   <div class="space"><span class="space-icon">P</span><div><strong>我的项目空间</strong><small>LOCAL WORKSPACE</small></div><span class="local-dot"></span></div>
   <div class="nav-label">工作台</div>
   <button class="nav-item active" @click="showAll"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>项目 <span class="nav-count">{{projects.length}}</span></button>
   <button class="nav-item" @click="emit('switch-view')"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="10" rx="2"/><path d="M8 18h8M12 14v4"/></svg>空间</button>
   <div class="nav-label status-label">项目状态</div>
   <button v-for="s in statuses" :key="s" class="status-nav" :class="{chosen:filter===s&&!isDetail}" @click="chooseStatus(s)"><i class="dot" :class="s"></i>{{labels[s]}}<span>{{counts[s]}}</span></button>
   <div class="sidebar-bottom"><div class="offline"><span class="local-dot"></span> 本地运行 · 数据保存在此电脑</div><button class="profile profile-button" aria-label="查看当前账号" @click="emit('account')"><span class="avatar">{{Array.from(user.username).slice(0,1).join('')}}</span><div><strong>{{user.username}}</strong><small>{{user.email}}</small></div><span class="profile-arrow">↗</span></button></div>
  </aside>

  <div class="workspace">
   <header class="topbar"><div class="breadcrumb"><span>工作台</span><b>/</b><button @click="showAll">项目</button><template v-if="isDetail"><b>/</b><span class="crumb-name">{{selected?.name||'项目详情'}}</span></template></div><div class="top-right"><span class="local-pill"><i class="local-dot"></i>本地版</span><button class="account-chip" aria-label="查看当前账号" @click="emit('account')"><span class="avatar small">{{Array.from(user.username).slice(0,1).join('')}}</span><span>{{user.username}}</span></button><button class="logout-link" :disabled="authBusy" @click="emit('logout')">{{authBusy?'退出中…':'退出登录'}}</button></div></header>
   <main>
    <div v-if="loading" class="state-panel" role="status"><span class="spinner"></span><h2>正在读取项目</h2><p>连接你的本地工作台…</p></div>
    <div v-else-if="loadError" class="state-panel"><h2>暂时无法加载项目</h2><p role="alert">{{loadError}}</p><button class="primary" @click="load">重新连接</button></div>
    <template v-else-if="!isDetail">
     <div class="heading"><div><div class="eyebrow">YOUR WORK, IN FOCUS</div><h1>项目<span class="heading-count">{{projects.length}}</span></h1><p>从一个想法开始，让每个项目都有清晰的下一步。</p></div><button class="primary" @click="openCreate"><span class="plus">＋</span>新建项目</button></div>
     <section class="summary" aria-label="项目概况"><div><span class="summary-icon purple">▦</span><div><small>全部项目</small><strong>{{projects.length}}<em>个项目</em></strong></div></div><div><span class="summary-icon blue">↗</span><div><small>正在推进</small><strong>{{countActive}}<em>进行中</em></strong></div></div><div><span class="summary-icon green">✓</span><div><small>已经完成</small><strong>{{counts.Completed}}<em>已完成</em></strong></div></div><div><span class="summary-icon orange">◷</span><div><small>需要关注</small><strong>{{projects.filter(overdue).length}}<em>已逾期</em></strong></div></div></section>
     <section class="project-area">
      <div class="section-title"><h2>项目一览</h2><button class="text-action" @click="exportProjects">↓ 导出项目</button></div>
      <div class="toolbar"><div class="filters"><button :class="{selected:filter==='all'}" @click="filter='all'">全部 <span>{{projects.length}}</span></button><button v-for="s in statuses" :key="s" :class="{selected:filter===s}" @click="filter=s">{{labels[s]}}</button></div><button class="icon-button refresh" title="刷新项目" aria-label="刷新项目" @click="load">↻</button></div>
      <div class="search-row"><div class="search-wrap"><svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input v-model="search" type="search" placeholder="搜索项目名称或描述…" aria-label="搜索项目"></div><div class="view-controls"><select v-model="sort" aria-label="项目排序"><option value="updated">最近更新</option><option value="deadline">截止日期优先</option><option value="name">名称排序</option></select><div class="view-toggle"><button :class="{on:layout==='grid'}" aria-label="卡片视图" title="卡片视图" @click="layout='grid'">▦</button><button :class="{on:layout==='list'}" aria-label="列表视图" title="列表视图" @click="layout='list'">☰</button></div></div></div>
      <div v-if="projects.length===0" class="empty"><div class="empty-art"><span>＋</span></div><h2>你的下一个项目，从这里开始</h2><p>创建第一个项目，记录目标、安排日期、跟踪状态。</p><button class="primary" @click="openCreate">＋ 创建第一个项目</button><small>所有数据保存在本机，关闭后也不会丢失。</small></div>
      <div v-else-if="filtered.length===0" class="empty compact"><h2>没有找到匹配的项目</h2><p>试试其他关键词或状态。</p><button class="secondary" @click="filter='all';search=''">清除筛选</button></div>
      <div v-else class="projects" :class="layout">
       <article v-for="p in filtered" :key="p.id" class="project-card">
        <div class="card-top"><span class="project-icon" :class="'color-'+p.id%4">{{initials(p.name)}}</span><span class="badge" :class="p.status"><i></i>{{labels[p.status]}}</span></div>
        <div class="card-copy"><h3><a :href="`#/projects/${p.id}`">{{p.name}}</a></h3><p>{{p.description||'还没有项目描述，添加一些目标和计划吧。'}}</p></div>
        <div class="card-dates"><span>◷ {{p.start_date?dateLabel(p.start_date):'开始日期待定'}}</span><span>→</span><span :class="{late:overdue(p)}">{{p.deadline?dateLabel(p.deadline):'截止日期待定'}}</span><span v-if="overdue(p)" class="late-label">逾期</span></div>
        <div class="card-footer"><a :href="`#/projects/${p.id}`">查看项目 <span>↗</span></a><div><button @click="openEdit(p)">编辑</button><button class="delete-action" @click="askDelete(p)">删除</button></div></div>
       </article>
       <button v-if="layout==='grid'" class="new-card" @click="openCreate"><span>＋</span><strong>开始一个新项目</strong><small>把想法变成计划</small></button>
      </div>
      <div class="list-bottom"><span>显示 {{filtered.length}} 个项目</span><span>每一小步，都在向前。</span></div>
     </section>
    </template>
    <template v-else-if="selected">
     <button class="back-link" @click="showAll">← 返回项目列表</button>
     <div class="heading detail-heading"><div class="detail-title"><span class="project-icon big" :class="'color-'+selected.id%4">{{initials(selected.name)}}</span><div><span class="eyebrow">PROJECT OVERVIEW</span><h1>{{selected.name}}</h1></div></div><button class="primary" @click="openEdit(selected)">编辑项目</button></div>
     <div class="detail-grid"><section class="detail-main"><div class="detail-tabs">项目概览</div><div class="detail-content"><h2>项目描述</h2><p class="description" :class="{muted:!selected.description}">{{selected.description||'这个项目还没有描述。点击“编辑项目”，补充项目目标与计划。'}}</p><div class="detail-note"><span>◇</span><div><strong>让目标保持清晰</strong><p>在这里记录项目的背景、预期成果和关键计划，方便下次继续推进。</p></div></div></div></section><aside class="detail-meta"><h2>项目信息</h2><dl><dt>当前状态</dt><dd><span class="badge" :class="selected.status"><i></i>{{labels[selected.status]}}</span></dd><dt>开始日期</dt><dd>{{dateLabel(selected.start_date)}}</dd><dt>截止日期</dt><dd :class="{late:overdue(selected)}">{{dateLabel(selected.deadline)}} <small v-if="overdue(selected)">已逾期</small></dd><dt>创建时间</dt><dd>{{timeLabel(selected.created_at)}}</dd><dt>最后更新</dt><dd>{{timeLabel(selected.updated_at)}}</dd><dt>项目编号</dt><dd class="mono">PRJ-{{String(selected.id).padStart(4,'0')}}</dd></dl></aside></div>
     <section class="danger-zone"><div><strong>删除项目</strong><p>永久删除此项目及其基本信息，此操作不可撤销。</p></div><button class="danger-outline" @click="askDelete(selected)">删除项目</button></section>
    </template>
    <div v-else class="state-panel"><h2>项目不存在</h2><p>项目可能已经被删除，或链接地址不正确。</p><button class="primary" @click="showAll">返回项目列表</button></div>
    <footer>FlowDesk <span>·</span> 为专注的工作，留一个清晰的空间。</footer>
   </main>
  </div>
 </div>

 <dialog ref="editor" class="editor" aria-labelledby="editor-title" @cancel.prevent="closeEditor">
  <form v-if="modal" @submit.prevent="save"><div class="modal-heading"><div><div class="eyebrow">PROJECT</div><h2 id="editor-title">{{editing?'编辑项目':'新建项目'}}</h2></div><button type="button" class="close" aria-label="关闭" :disabled="saving" @click="closeEditor">×</button></div><p class="modal-intro">{{editing?'更新计划，让项目始终保持清晰。':'为你的下一个想法，建立一个起点。'}}</p>
   <fieldset :disabled="saving"><label for="ws">所属空间 <span class="required">*</span></label><select id="ws" v-model.number="form.workspace_id"><option :value="null">个人项目（不挂靠空间）</option><option v-for="w in workspaces" :key="w.id" :value="w.id">{{w.name}}</option></select>
   <label for="name">项目名称 <span class="required">*</span></label><input id="name" ref="nameInput" v-model="form.name" required maxlength="120" placeholder="例如：FlowDesk 第一版开发" autocomplete="off"><div class="field-hint">清晰的名称，让项目更容易被找到 <span>{{form.name.length}}/120</span></div>
   <label for="description">项目描述 <span class="optional">选填</span></label><textarea id="description" v-model="form.description" rows="4" maxlength="10000" placeholder="这个项目要实现什么？记录背景、目标或计划…"></textarea>
   <label for="status">项目状态</label><select id="status" v-model="form.status"><option v-for="s in statuses" :key="s" :value="s">{{labels[s]}} · {{s}}</option></select>
   <div class="date-fields"><div><label for="start">开始日期 <span class="optional">选填</span></label><input id="start" v-model="form.start_date" type="date" min="0001-01-01" max="9999-12-31"></div><div><label for="deadline">截止日期 <span class="optional">选填</span></label><input id="deadline" v-model="form.deadline" type="date" min="0001-01-01" max="9999-12-31"></div></div></fieldset>
   <p v-if="formError" class="error" role="alert">{{formError}}</p><div class="modal-footer"><span>* 为必填项</span><div><button class="secondary" type="button" :disabled="saving" @click="closeEditor">取消</button><button class="primary" type="submit" :disabled="saving">{{saving?'正在保存…':editing?'保存修改':'创建项目'}}</button></div></div>
  </form>
 </dialog>
 <dialog ref="confirmer" class="confirm-dialog" aria-labelledby="delete-title" @cancel.prevent="closeDelete"><template v-if="deleteTarget"><div class="delete-symbol">!</div><h2 id="delete-title">确认删除这个项目？</h2><p>“<strong>{{deleteTarget.name}}</strong>”将被永久删除，无法撤销。你也可以取消后将状态改为“已归档”。</p><p v-if="deleteError" class="error" role="alert">{{deleteError}}</p><div class="confirm-buttons"><button class="secondary" :disabled="deleting" @click="closeDelete">保留项目</button><button class="danger" :disabled="deleting" @click="remove">{{deleting?'正在删除…':'确认删除'}}</button></div></template></dialog>
 <Transition name="toast"><div v-if="toast" class="toast-message" role="status"><span>✓</span>{{toast}}</div></Transition>
</template>
