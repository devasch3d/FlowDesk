<script setup lang="ts">
import {onMounted,ref} from 'vue';
import {ApiError,request,type User} from '../api';

const props=defineProps<{user:User;workspaceId:number}>();
const emit=defineEmits<{logout:[];account:[];'session-lost':[];back:[]}>();

type Activity={id:number;workspace_id:number;actor_id:number;actor_username:string;action:string;target_type:string;target_id:number;created_at:string};
const actionLabels:Record<string,string>={created:'创建了',status_changed:'更新了状态',commented:'发表了评论',file_uploaded:'上传了文件'};

const items=ref<Activity[]>([]);
const loading=ref(true),error=ref(''),hasMore=ref(true),loadingMore=ref(false);
const pageSize=30,nextOffset=ref(0);

function label(a:string){return actionLabels[a]||'执行了操作';}
function stamp(t:string){const d=new Date(t);return isNaN(d.getTime())?t:d.toLocaleString('zh-CN',{hour12:false});}

async function api(path:string,method='GET',send?:unknown){
 try{return await request(path,method,send,{'X-FlowDesk-User':String(props.user.id)});}
 catch(e){if(e instanceof ApiError&&(e.status===401||(e.status===409&&e.message.includes('账号已'))))emit('session-lost');throw e;}
}
async function load(append=false){
 const offset=append?nextOffset.value:0;
 if(append){loadingMore.value=true;}else{loading.value=true;error.value='';}
 try{
  const rows:Activity[]=await api(`/workspaces/${props.workspaceId}/activities?limit=${pageSize}&offset=${offset}`);
  items.value=append?items.value.concat(rows):rows;
  hasMore.value=rows.length===pageSize;
  nextOffset.value=offset+rows.length;
 }catch(e){if(!append)error.value=(e as Error).message;else hasMore.value=false;}
 finally{loading.value=false;loadingMore.value=false;}
}
function loadMore(){if(hasMore.value&&!loadingMore.value)void load(true);}
onMounted(load);
</script>

<template>
 <section class="activity-view" style="max-width:760px;margin:0 auto;padding:24px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">
   <button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="emit('back')">← 返回空间</button>
   <h1 style="margin:0">活动</h1>
  </div>
  <p style="color:#888;margin:0 0 16px">空间内最近的动作时间线。</p>
  <div v-if="loading" style="padding:40px;text-align:center;color:#888">加载中…</div>
  <p v-else-if="error" style="color:#c00">{{error}}</p>
  <template v-else>
   <ul v-if="items.length" style="list-style:none;margin:0;padding:0">
    <li v-for="a in items" :key="a.id" style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f0f0f0">
     <span style="flex:0 0 24px;height:24px;border-radius:50%;background:#3370ff;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px">{{(a.actor_username||'?').slice(0,1)}}</span>
     <div style="flex:1;min-width:0">
      <div style="font-size:13px"><strong>{{a.actor_username||('用户#'+a.actor_id)}}</strong> {{label(a.action)}}<template v-if="a.target_type==='task'"> 任务 #{{a.target_id}}</template><template v-else> {{a.target_type}} #{{a.target_id}}</template></div>
      <div style="font-size:12px;color:#888">{{stamp(a.created_at)}}</div>
     </div>
    </li>
   </ul>
   <p v-else style="color:#888;padding:20px;text-align:center">还没有活动记录。</p>
   <div v-if="hasMore" style="text-align:center;margin-top:14px">
    <button :disabled="loadingMore" @click="loadMore">{{loadingMore?'加载中…':'加载更多'}}</button>
   </div>
  </template>
 </section>
</template>
