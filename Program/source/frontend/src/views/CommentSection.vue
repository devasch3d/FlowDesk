<script setup lang="ts">
import {onMounted,ref} from 'vue';
import {ApiError,request,type User} from '../api';

const props=defineProps<{user:User;taskId:number;canManage?:boolean}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[]}>();

type Comment={id:number;task_id:number;author_id:number;author_username:string;body:string;created_at:string;updated_at:string};

const comments=ref<Comment[]>([]);
const body=ref(''),editBody=ref('');
const loading=ref(true),saving=ref(false),error=ref(''),toast=ref('');
const editingId=ref<number|null>(null);
let toastTimer:ReturnType<typeof setTimeout>;

function notify(m:string){toast.value=m;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',4000);}
function isMine(c:Comment){return c.author_id===props.user.id;}
function canDelete(c:Comment){return isMine(c)||props.canManage===true;}
function stamp(t:string){const d=new Date(t);return isNaN(d.getTime())?t:d.toLocaleString('zh-CN',{hour12:false});}

async function api(path:string,method='GET',send?:unknown){
 try{return await request(path,method,send,{'X-FlowDesk-User':String(props.user.id)});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function load(){
 loading.value=true;error.value='';
 try{comments.value=await api(`/tasks/${props.taskId}/comments`);}
 catch(e){error.value=(e as Error).message;}
 finally{loading.value=false;}
}
async function post(){
 const text=body.value.trim();
 if(!text){notify('评论内容不能为空。');return;}
 saving.value=true;
 try{
  await api(`/tasks/${props.taskId}/comments`,'POST',{body:text});
  body.value='';await load();notify('评论已发表');
 }catch(e){notify((e as Error).message);}
 finally{saving.value=false;}
}
function startEdit(c:Comment){editingId.value=c.id;editBody.value=c.body;}
function cancelEdit(){editingId.value=null;editBody.value='';}
async function saveEdit(c:Comment){
 const text=editBody.value.trim();
 if(!text){notify('评论内容不能为空。');return;}
 saving.value=true;
 try{
  await api(`/comments/${c.id}`,'PATCH',{body:text});
  editingId.value=null;await load();notify('评论已更新');
 }catch(e){notify((e as Error).message);}
 finally{saving.value=false;}
}
async function remove(c:Comment){
 if(!confirm('确定删除这条评论吗？'))return;
 try{
  await api(`/comments/${c.id}`,'DELETE');
  comments.value=comments.value.filter(x=>x.id!==c.id);notify('评论已删除');
 }catch(e){notify((e as Error).message);}
}
onMounted(load);
</script>

<template>
 <section class="comment-section" style="margin-top:16px;border-top:1px solid #eee;padding-top:14px">
  <h3 style="margin:0 0 10px;font-size:14px">评论 <span v-if="comments.length" style="color:#888">({{comments.length}})</span></h3>
  <div v-if="loading" style="padding:12px;color:#888;font-size:13px">加载中…</div>
  <p v-else-if="error" style="color:#c00;font-size:13px">{{error}}</p>
  <template v-else>
   <ul v-if="comments.length" style="list-style:none;margin:0 0 12px;padding:0">
    <li v-for="c in comments" :key="c.id" style="padding:8px 0;border-bottom:1px dashed #eee">
     <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span style="font-size:12px;color:#888"><strong style="color:#333">{{c.author_username||('用户#'+c.author_id)}}</strong> · {{stamp(c.created_at)}}<template v-if="c.updated_at!==c.created_at"> · 已编辑</template></span>
      <span v-if="!editingId || editingId!==c.id" style="display:flex;gap:6px">
       <button v-if="isMine(c)" style="font-size:11px;padding:1px 6px" @click="startEdit(c)">编辑</button>
       <button v-if="canDelete(c)" style="font-size:11px;padding:1px 6px;color:#c00" @click="remove(c)">删除</button>
      </span>
     </div>
     <textarea v-if="editingId===c.id" v-model="editBody" rows="2" maxlength="10000" style="width:100%;box-sizing:border-box;margin-top:6px;padding:6px"></textarea>
     <p v-else style="margin:4px 0 0;white-space:pre-wrap;font-size:13px">{{c.body}}</p>
     <div v-if="editingId===c.id" style="display:flex;gap:8px;justify-content:flex-end;margin-top:6px">
      <button type="button" @click="cancelEdit">取消</button>
      <button class="primary" :disabled="saving" @click="saveEdit(c)">{{saving?'保存中…':'保存'}}</button>
     </div>
    </li>
   </ul>
   <p v-else style="color:#888;font-size:13px">还没有评论，来发表第一条。</p>
   <div style="display:flex;gap:8px;align-items:flex-end">
    <textarea v-model="body" rows="2" maxlength="10000" placeholder="写下你的评论…" style="flex:1;padding:8px;box-sizing:border-box" @keydown.ctrl.enter="post"></textarea>
    <button class="primary" :disabled="saving||!body.trim()" @click="post">{{saving?'发送中…':'发表'}}</button>
   </div>
  </template>
  <Transition name="toast"><div v-if="toast" style="position:fixed;bottom:24px;right:24px;background:#333;color:#fff;padding:8px 16px;border-radius:8px;z-index:99">{{toast}}</div></Transition>
 </section>
</template>
