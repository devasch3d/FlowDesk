<script setup lang="ts">
import {onMounted, reactive, ref} from 'vue';
import {ApiError, request, type User} from './api';
const props=defineProps<{user:User;projectId?:number}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[]}>();
type TaskStatus='Todo'|'In Progress'|'Review'|'Done';
type TaskPriority='Low'|'Medium'|'High'|'Urgent';
type Task={id:number;project_id:number;title:string;description:string;status:TaskStatus;priority:TaskPriority;assignee_id:number|null;creator_id:number;due_date:string|null;created_at:string;updated_at:string;completed_at:string|null;version:number};
type Project={id:number;name:string;workspace_id:number|null};
const statuses:TaskStatus[]=['Todo','In Progress','Review','Done'];
const statusLabels:Record<TaskStatus,string>={Todo:'待办','In Progress':'进行中',Review:'评审',Done:'已完成'};
const priorities:TaskPriority[]=['Low','Medium','High','Urgent'];
const priorityLabels:Record<TaskPriority,string>={Low:'低',Medium:'中',High:'高',Urgent:'紧急'};
const tasks=ref<Task[]>([]), projects=ref<Project[]>([]), loading=ref(true), error=ref(''), toast=ref('');
const selectedProject=ref<number|null>(props.projectId??null);
const modal=ref(false), saving=ref(false), formError=ref('');
const form=reactive({title:'',description:'',status:'Todo' as TaskStatus,priority:'Medium' as TaskPriority,due_date:null as string|null});
const editor=ref<HTMLDialogElement>();
let toastTimer:ReturnType<typeof setTimeout>;
function notify(m:string){toast.value=m;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4000);}
async function api(path:string,method='GET',body?:unknown,version?:number){
 try{return await request(path,method,body,{'X-FlowDesk-User':String(props.user.id),...(version?{'If-Match':String(version)}:{})});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function load(){
 loading.value=true;error.value='';
 try{
  projects.value=await api('/projects');
  if(selectedProject.value){
   tasks.value=await api(`/projects/${selectedProject.value}/tasks`);
  }
 }catch(e){error.value=(e as Error).message;}finally{loading.value=false;}
}
async function chooseProject(id:number){
 selectedProject.value=id;
 if(id){tasks.value=await api(`/projects/${id}/tasks`);}else{tasks.value=[];}
}
function openCreate(){Object.assign(form,{title:'',description:'',status:'Todo',priority:'Medium',due_date:null});modal.value=true;editor.value?.showModal();}
function closeEditor(){if(!saving.value){editor.value?.close();modal.value=false;}}
async function save(){
 formError.value='';
 if(!form.title.trim()){formError.value='请填写任务标题。';return;}
 if(!selectedProject.value){formError.value='请先选择一个项目。';return;}
 saving.value=true;
 try{
  await api(`/projects/${selectedProject.value}/tasks`,'POST',{title:form.title.trim(),description:form.description.trim(),status:form.status,priority:form.priority,due_date:form.due_date||null});
  tasks.value=await api(`/projects/${selectedProject.value}/tasks`);
  notify('任务已创建');closeEditor();
 }catch(e){formError.value=(e as Error).message;}finally{saving.value=false;}
}
async function cycleStatus(t:Task){
 const idx=statuses.indexOf(t.status);
 const next=statuses[(idx+1)%statuses.length];
 try{await api(`/tasks/${t.id}`,'PATCH',{status:next},t.version);await load();}
 catch(e){notify((e as Error).message);}
}
async function remove(t:Task){
 try{await api(`/tasks/${t.id}`,'DELETE',undefined,t.version);tasks.value=tasks.value.filter(x=>x.id!==t.id);notify('任务已删除');}
 catch(e){notify((e as Error).message);}
}
onMounted(load);
</script>

<template>
 <div class="task-view" style="padding:24px;max-width:1200px;margin:0 auto">
  <h1>任务</h1>
  <p style="color:#888">在项目下拆解任务，跟踪状态与优先级。</p>
  <div style="margin:16px 0;display:flex;gap:8px;align-items:center">
   <select :value="selectedProject??''" @change="chooseProject(Number(($event.target as HTMLSelectElement).value))">
    <option value="">选择项目…</option>
    <option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}}</option>
   </select>
   <button v-if="selectedProject" class="primary" style="margin-left:auto" @click="openCreate">＋ 新建任务</button>
  </div>
  <div v-if="loading" style="padding:40px;text-align:center;color:#888">加载中…</div>
  <div v-else-if="error" style="color:#c00">{{error}}</div>
  <div v-else-if="!selectedProject" style="padding:40px;text-align:center;color:#888">请先选择一个项目查看任务</div>
  <div v-else style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">
   <div v-for="s in statuses" :key="s" style="background:#f4f4f8;border-radius:8px;padding:12px">
    <h3 style="margin:0 0 8px;font-size:14px">{{statusLabels[s]}} <span style="color:#888">({{tasks.filter(t=>t.status===s).length}})</span></h3>
    <div v-for="t in tasks.filter(t=>t.status===s)" :key="t.id" style="background:#fff;border-radius:6px;padding:10px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,.08)">
     <div style="display:flex;justify-content:space-between;align-items:start">
      <strong style="font-size:13px">{{t.title}}</strong>
      <button style="border:none;background:none;cursor:pointer;color:#c00" @click="remove(t)">×</button>
     </div>
     <div style="font-size:12px;color:#888;margin:4px 0">{{t.description||'—'}}</div>
     <div style="display:flex;gap:4px;flex-wrap:wrap">
      <span :style="{fontSize:11,padding:'2px 6px',borderRadius:4,background:t.priority==='Urgent'?'#fdd':t.priority==='High'?'#fee':'#eef'}">{{priorityLabels[t.priority]}}</span>
      <span v-if="t.due_date" style="fontSize:11,padding:'2px 6px',borderRadius:4,background:#eee">◷ {{t.due_date}}</span>
     </div>
     <button style="margin-top:6px;font-size:11px;padding:2px 8px" @click="cycleStatus(t)">推进 →</button>
    </div>
   </div>
  </div>
  <dialog ref="editor" style="border:none;border-radius:12px;padding:24px;min-width:360px" @cancel.prevent="closeEditor">
   <h2 style="margin:0 0 12px">新建任务</h2>
   <form @submit.prevent="save">
    <label style="display:block;font-size:13px;margin-bottom:4px">标题 *</label>
    <input v-model="form.title" required maxlength="200" style="width:100%;margin-bottom:12px;padding:6px" placeholder="任务标题">
    <label style="display:block;font-size:13px;margin-bottom:4px">描述</label>
    <textarea v-model="form.description" rows="3" style="width:100%;margin-bottom:12px;padding:6px"></textarea>
    <div style="display:flex;gap:12px;margin-bottom:12px">
     <label style="flex:1;font-size:13px">状态<select v-model="form.status" style="width:100%;margin-top:4px"><option v-for="s in statuses" :key="s" :value="s">{{statusLabels[s]}}</option></select></label>
     <label style="flex:1;font-size:13px">优先级<select v-model="form.priority" style="width:100%;margin-top:4px"><option v-for="p in priorities" :key="p" :value="p">{{priorityLabels[p]}}</option></select></label>
    </div>
    <label style="display:block;font-size:13px;margin-bottom:12px">截止日期<input type="date" v-model="form.due_date" style="width:100%;margin-top:4px;padding:6px"></label>
    <p v-if="formError" style="color:#c00;font-size:13px">{{formError}}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end">
     <button type="button" @click="closeEditor">取消</button>
     <button class="primary" type="submit" :disabled="saving">{{saving?'保存中…':'创建'}}</button>
    </div>
   </form>
  </dialog>
  <Transition name="toast"><div v-if="toast" style="position:fixed;bottom:24px;right:24px;background:#333;color:#fff;padding:8px 16px;border-radius:8px">{{toast}}</div></Transition>
 </div>
</template>
