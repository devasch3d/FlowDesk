<script setup lang="ts">
import {onMounted, ref} from 'vue';
import {ApiError, request, type User} from '../api';
const props=defineProps<{user:User;workspaceId?:number;projectId?:number;taskId?:number}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[];'switch-view':[];'switch-tasks':[]}>();
type FileItem={id:number;workspace_id:number|null;project_id:number|null;task_id:number|null;filename:string;mime_type:string;size:number;uploaded_by:number;created_at:string};
type Workspace={id:number;name:string;role:string};
type Project={id:number;name:string;workspace_id:number|null};
type Scope='workspace'|'project';
const workspaces=ref<Workspace[]>([]), projects=ref<Project[]>([]);
const scope=ref<Scope>(props.workspaceId?'workspace':props.projectId?'project':'workspace');
const scopeId=ref<number|null>(props.workspaceId??props.projectId??null);
const files=ref<FileItem[]>([]);
const loading=ref(true), error=ref(''), toast=ref('');
const uploading=ref(false), uploadError=ref('');
const fileInput=ref<HTMLInputElement>();
let toastTimer:ReturnType<typeof setTimeout>;
function notify(m:string){toast.value=m;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4000);}
async function api(path:string,method='GET',body?:unknown){
 try{return await request(path,method,body,{'X-FlowDesk-User':String(props.user.id)});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function loadScopes(){
 try{
  const [ws,pr]=await Promise.all([api('/workspaces'),api('/projects')]);
  workspaces.value=ws as Workspace[];projects.value=pr as Project[];
  if(!scopeId.value){scopeId.value=(scope.value==='workspace'?workspaces.value[0]?.id:projects.value[0]?.id)??null;}
 }catch(e){error.value=(e as Error).message;}
}
async function loadFiles(){
 if(!scopeId.value){files.value=[];return;}
 loading.value=true;error.value='';
 try{files.value=await api(scope.value==='workspace'?`/workspaces/${scopeId.value}/files`:`/projects/${scopeId.value}/files`) as FileItem[];}
 catch(e){error.value=(e as Error).message;}finally{loading.value=false;}
}
function chooseScope(kind:Scope){scope.value=kind;scopeId.value=(kind==='workspace'?workspaces.value[0]?.id:projects.value[0]?.id)??null;void loadFiles();}
async function upload(){
 const input=fileInput.value;
 if(!input?.files?.length){uploadError.value='请先选择要上传的文件。';return;}
 if(!scopeId.value){uploadError.value='请先选择空间或项目。';return;}
 uploadError.value='';uploading.value=true;
 const fd=new FormData();
 fd.append('file',input.files[0]);
 fd.append(scope.value==='workspace'?'workspace_id':'project_id',String(scopeId.value));
 const meta=document.querySelector<HTMLMetaElement>('meta[name=flowdesk-token]')?.content||'';
 try{
  const res=await fetch('/api/files',{method:'POST',credentials:'same-origin',headers:{'X-FlowDesk-Token':meta,'X-FlowDesk-User':String(props.user.id)},body:fd});
  if(!res.ok){let data:{detail?:string}|null=null;try{data=await res.json() as {detail?:string};}catch{}throw new ApiError(res.status,data?.detail||`上传失败（${res.status}）`);}
  notify('文件已上传');await loadFiles();input.value='';
 }catch(e){uploadError.value=(e as Error).message;}finally{uploading.value=false;}
}
async function remove(f:FileItem){
 if(!window.confirm(`确定删除「${f.filename}」吗？删除后不可恢复。`))return;
 try{await api(`/files/${f.id}`,'DELETE');files.value=files.value.filter(x=>x.id!==f.id);notify('文件已删除');}
 catch(e){notify((e as Error).message);}
}
function fmtSize(n:number){if(n<1024)return `${n} B`;if(n<1024*1024)return `${(n/1024).toFixed(1)} KB`;return `${(n/1024/1024).toFixed(1)} MB`;}
function fmtTime(s:string){return new Date(s).toLocaleString('zh-CN',{hour12:false});}
onMounted(async()=>{await loadScopes();await loadFiles();});
</script>

<template>
 <div class="files-view" style="padding:24px;max-width:1200px;margin:0 auto">
  <h1>文件</h1>
  <p style="color:#888">把附件挂到空间或项目下，成员可上传与下载，Owner/Admin 可删除。</p>
  <div style="margin:16px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
   <select :value="scope" @change="chooseScope(($event.target as HTMLSelectElement).value as Scope)">
    <option value="workspace">按空间</option>
    <option value="project">按项目</option>
   </select>
   <select :value="scopeId??''" @change="scopeId=Number(($event.target as HTMLSelectElement).value)||null;loadFiles()" style="min-width:180px">
    <option value="">选择{{scope==='workspace'?'空间':'项目'}}…</option>
    <option v-for="w in scope==='workspace'?workspaces:projects" :key="w.id" :value="w.id">{{w.name}}</option>
   </select>
   <label style="margin-left:auto;display:flex;gap:8px;align-items:center">
    <input ref="fileInput" type="file" style="max-width:220px">
    <button class="primary" :disabled="uploading" @click="upload">{{uploading?'上传中…':'＋ 上传文件'}}</button>
   </label>
  </div>
  <p v-if="uploadError" style="color:#c00;font-size:13px">{{uploadError}}</p>
  <div v-if="loading" style="padding:40px;text-align:center;color:#888">加载中…</div>
  <div v-else-if="error" style="color:#c00">{{error}}</div>
  <div v-else-if="!scopeId" style="padding:40px;text-align:center;color:#888">请先选择空间或项目查看文件</div>
  <div v-else-if="files.length===0" style="padding:40px;text-align:center;color:#888">这里还没有文件，点击右上角上传第一个附件</div>
  <table v-else style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden">
   <thead>
    <tr style="background:#f4f4f8;text-align:left">
     <th style="padding:10px 14px;font-size:13px">文件名</th>
     <th style="padding:10px 14px;font-size:13px">类型</th>
     <th style="padding:10px 14px;font-size:13px">大小</th>
     <th style="padding:10px 14px;font-size:13px">上传时间</th>
     <th style="padding:10px 14px;font-size:13px;text-align:right">操作</th>
    </tr>
   </thead>
   <tbody>
    <tr v-for="f in files" :key="f.id" style="border-top:1px solid #eee">
     <td style="padding:10px 14px;font-size:13px;word-break:break-all">{{f.filename}}</td>
     <td style="padding:10px 14px;font-size:12px;color:#888">{{f.mime_type}}</td>
     <td style="padding:10px 14px;font-size:12px;color:#888">{{fmtSize(f.size)}}</td>
     <td style="padding:10px 14px;font-size:12px;color:#888">{{fmtTime(f.created_at)}}</td>
     <td style="padding:10px 14px;text-align:right;white-space:nowrap">
      <a :href="`/api/files/${f.id}`" :download="f.filename" style="margin-right:10px;font-size:13px">下载</a>
      <button style="border:none;background:none;cursor:pointer;color:#c00;font-size:13px" @click="remove(f)">删除</button>
     </td>
    </tr>
   </tbody>
  </table>
  <Transition name="toast"><div v-if="toast" style="position:fixed;bottom:24px;right:24px;background:#333;color:#fff;padding:8px 16px;border-radius:8px">{{toast}}</div></Transition>
 </div>
</template>
