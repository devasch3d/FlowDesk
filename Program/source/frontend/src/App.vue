<script setup lang="ts">
import {computed,onMounted,onUnmounted,reactive,ref} from 'vue';
import {useRouter} from 'vue-router';
import Projects from './Projects.vue';
import Workspaces from './Workspaces.vue';
import TaskView from './TaskView.vue';
import DashboardView from './views/DashboardView.vue';
import ActivityView from './views/ActivityView.vue';
import FilesView from './views/FilesView.vue';
import AIView from './views/AIView.vue';
import {ApiError,request,type User} from './api';
const router=useRouter();
const view=ref<'projects'|'workspaces'|'tasks'|'dashboard'|'activities'|'files'|'ai'>('projects');
const activityWsId=ref(0);
function openActivities(id:number){activityWsId.value=id;view.value='activities';}
const user=ref<User|null>(null),checking=ref(true),busy=ref(false),error=ref(''),bootError=ref(''),notice=ref('');
const mode=ref<'login'|'register'>('login'),showPassword=ref(false),account=ref<HTMLDialogElement>();
const setup=reactive({first_user:false,legacy_projects:0});
const form=reactive({username:'',email:'',password:'',confirm:'',remember:false,claim_legacy:false});
const registering=computed(()=>mode.value==='register');
let channel:BroadcastChannel|undefined, timer:ReturnType<typeof setInterval>, epoch=0;
function broadcast(){channel?.postMessage('auth-changed');try{localStorage.setItem('flowdesk-auth-change',String(Date.now()));}catch{}}
function switchMode(){mode.value=registering.value?'login':'register';error.value='';form.password='';form.confirm='';showPassword.value=false;}
async function refresh(initial=false){
 const requestEpoch=++epoch;
 if(initial)checking.value=true;
 try{
  const me:User=await request('/auth/me');
  if(requestEpoch!==epoch)return;
  if(user.value && user.value.id!==me.id)account.value?.close();
  user.value=me;bootError.value='';
 }catch(e){
  if(requestEpoch!==epoch)return;
  if(e instanceof ApiError&&e.status===401){
   const wasLogged=!!user.value;user.value=null;account.value?.close();
   if(wasLogged){notice.value='登录已结束，请重新登录。';form.password='';}
   try{
    const result=await request('/auth/setup');
    if(requestEpoch!==epoch)return;
    Object.assign(setup,result);if(initial&&result.first_user)mode.value='register';bootError.value='';
   }catch(err){if(requestEpoch===epoch)bootError.value=(err as Error).message;}
  }else{bootError.value=(e as Error).message;}
 }finally{if(requestEpoch===epoch)checking.value=false;}
}
async function authChanged(){epoch++;user.value=null;account.value?.close();notice.value='账号状态已更新。';await refresh(true);}
function onStorage(e:StorageEvent){if(e.key==='flowdesk-auth-change'&&!channel)void authChanged();}
function onFocus(){if(!busy.value)void refresh();}
async function submit(){
 error.value='';notice.value='';
 if(registering.value&&form.password!==form.confirm){error.value='两次输入的密码不一致。';return;}
 if(registering.value&&!form.username.trim()){error.value='请填写用户名称。';return;}
 if(registering.value&&setup.legacy_projects>0&&!form.claim_legacy){error.value='请先确认接收旧版项目。';return;}
 busy.value=true;epoch++;
 try{
  const payload=registering.value?{username:form.username,email:form.email,password:form.password,remember:form.remember,claim_legacy:form.claim_legacy}:{email:form.email,password:form.password,remember:form.remember};
  user.value=await request(registering.value?'/auth/register':'/auth/login','POST',payload);
  form.password='';form.confirm='';showPassword.value=false;bootError.value='';broadcast();
  if(registering.value)await router.replace('/');
 }catch(e){error.value=(e as Error).message;}finally{busy.value=false;}
}
async function logout(){
 busy.value=true;error.value='';epoch++;
 try{await request('/auth/logout','POST');user.value=null;account.value?.close();notice.value='已安全退出。';form.password='';form.confirm='';mode.value='login';broadcast();await router.replace('/');}
 catch(e){error.value=(e as Error).message;account.value?.showModal();}
 finally{busy.value=false;}
}
function sessionLost(){void authChanged();}
onMounted(()=>{
 void refresh(true);
 if('BroadcastChannel' in window){channel=new BroadcastChannel('flowdesk-auth');channel.onmessage=()=>void authChanged();}
 window.addEventListener('storage',onStorage);window.addEventListener('focus',onFocus);
 timer=setInterval(()=>{if(document.visibilityState==='visible'&&!busy.value)void refresh();},60000);
});
onUnmounted(()=>{clearInterval(timer);channel?.close();window.removeEventListener('storage',onStorage);window.removeEventListener('focus',onFocus);});
</script>

<template>
 <div v-if="checking" class="auth-loading" role="status"><div class="brand"><span class="brand-mark">F<span></span></span>FlowDesk</div><span class="spinner"></span><p>正在确认登录状态…</p></div>
 <div v-else-if="bootError&&!user" class="auth-loading"><h2>暂时无法连接 FlowDesk</h2><p role="alert">{{bootError}}</p><button class="primary" @click="refresh(true)">重新连接</button></div>
 <Projects v-else-if="user&&view==='projects'" :key="user.id" :user="user" :auth-busy="busy" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" @switch-view="view='workspaces'" @switch-tasks="view='tasks'" @switch-dashboard="view='dashboard'" @switch-files="view='files'" @switch-ai="view='ai'" />
 <Workspaces v-else-if="user&&view==='workspaces'" :key="user.id" :user="user" :auth-busy="busy" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" @switch-view="view='projects'" @switch-tasks="view='tasks'" @switch-dashboard="view='dashboard'" @switch-activities="openActivities" @switch-files="view='files'" @switch-ai="view='ai'" />
 <div v-else-if="user&&view==='tasks'" style="min-height:100vh;background:#fafafa"><div style="position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:8px;padding:10px 24px;background:#fff;border-bottom:1px solid #eee"><button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="view='projects'">← 返回项目</button><strong style="color:#333">FlowDesk · 任务</strong></div><TaskView :key="user.id" :user="user" :auth-busy="busy" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" /></div>
 <div v-else-if="user&&view==='files'" style="min-height:100vh;background:#fafafa"><div style="position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:8px;padding:10px 24px;background:#fff;border-bottom:1px solid #eee"><button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="view='projects'">← 返回项目</button><strong style="color:#333">FlowDesk · 文件</strong></div><FilesView :key="user.id" :user="user" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" /></div>
 <div v-else-if="user&&view==='ai'" style="min-height:100vh;background:#fafafa"><div style="position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:8px;padding:10px 24px;background:#fff;border-bottom:1px solid #eee"><button style="cursor:pointer;border:1px solid #ddd;background:#fff;border-radius:6px;padding:6px 12px" @click="view='projects'">← 返回项目</button><strong style="color:#333">FlowDesk · AI 助手</strong></div><AIView :key="user.id" :user="user" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" /></div>
 <DashboardView v-else-if="user&&view==='dashboard'" :key="user.id" :user="user" :auth-busy="busy" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" @back="view='projects'" />
 <ActivityView v-else-if="user&&view==='activities'" :key="user.id" :user="user" :workspace-id="activityWsId" @back="view='workspaces'" @logout="logout" @account="error='';account?.showModal()" @session-lost="sessionLost" />
 <div v-else class="auth-shell">
  <section class="auth-story">
   <div class="brand"><span class="brand-mark">F<span></span></span>FlowDesk</div>
   <div class="story-main"><div class="story-kicker"><i></i> A SPACE FOR YOUR NEXT IDEA</div><h1>每一个想法，<br>都有自己的起点。</h1><p>把项目、计划与进展留在你的工作台。<br>登录自己的账号，继续专注于重要的事。</p>
    <div class="story-board" aria-hidden="true"><div class="board-head"><span class="board-mark">F</span><span>我的项目空间</span><span class="board-dots">···</span></div><div class="board-line"><i class="board-check">✓</i><div><strong>让想法成为一个项目</strong><span>记录目标，开始第一步</span></div><b>已完成</b></div><div class="board-line"><i class="board-progress"></i><div><strong>给每一步一个方向</strong><span>安排日期，清晰推进</span></div><b class="in-progress">进行中</b></div><div class="board-progressbar"><span></span></div><div class="board-bottom"><span>一点一滴，都在向前</span><span>↗</span></div></div>
    <div class="story-features"><span><i>✓</i> 专属项目空间</span><span><i>✓</i> 数据保存在本机</span></div>
   </div><div class="story-footer">为专注的工作，留一个清晰的空间。<span>FLOWDESK / 0.2</span></div>
  </section>
  <section class="auth-form-side"><div class="auth-side-top"><span class="local-pill"><i class="local-dot"></i>本地一体版</span><span class="auth-help">账号仅在此项目库中使用</span></div>
   <div class="auth-form-content"><div class="eyebrow">{{registering?'START SOMETHING NEW':'WELCOME BACK'}}</div><h2>{{registering?'创建你的 FlowDesk 账号':'欢迎回到 FlowDesk'}}</h2><p class="auth-subtitle">{{registering?'建立自己的工作台，让每个项目各归其位。':'登录后，继续推进属于你的项目。'}}</p>
    <div class="auth-tabs" role="tablist" aria-label="账号操作"><button role="tab" :aria-selected="!registering" :class="{selected:!registering}" :disabled="busy" @click="registering&&switchMode()">登录</button><button role="tab" :aria-selected="registering" :class="{selected:registering}" :disabled="busy" @click="!registering&&switchMode()">注册</button></div>
    <p v-if="notice" class="auth-notice" role="status">{{notice}}</p>
    <form @submit.prevent="submit"><fieldset :disabled="busy">
     <template v-if="registering"><label for="username">用户名称</label><input id="username" v-model="form.username" required maxlength="40" autocomplete="nickname"></template>
     <label for="email">邮箱地址</label><input id="email" v-model="form.email" type="email" required maxlength="254" autocomplete="username" spellcheck="false" autocapitalize="none">
     <label for="password">密码</label><div class="password-field"><input id="password" v-model="form.password" :type="showPassword?'text':'password'" required :minlength="registering?10:1" maxlength="128" :autocomplete="registering?'new-password':'current-password'"><button type="button" :aria-label="showPassword?'隐藏密码':'显示密码'" :aria-pressed="showPassword" @click="showPassword=!showPassword">{{showPassword?'隐藏':'显示'}}</button></div>
     <template v-if="registering"><label for="confirm">确认密码</label><input id="confirm" v-model="form.confirm" :type="showPassword?'text':'password'" required minlength="10" maxlength="128" autocomplete="new-password"><p class="password-hint">建议使用多个词组成的长密码；支持空格与中文。</p></template>
     <label class="check-row"><input v-model="form.remember" type="checkbox"><span>保持登录 30 天</span></label>
     <div v-if="registering&&setup.legacy_projects>0" class="legacy-message"><strong>检测到 {{setup.legacy_projects}} 个旧版项目</strong><p>数据库已在升级前自动备份。首次创建的账号将接收这些项目，之后其他账号无法访问。</p><label class="check-row"><input v-model="form.claim_legacy" type="checkbox" required><span>我确认将这些旧项目归属到此账号</span></label></div>
    </fieldset><p v-if="error" class="error" role="alert">{{error}}</p><button class="primary auth-submit" type="submit" :disabled="busy">{{busy?'正在处理…':registering?'创建账号并进入工作台':'登录 FlowDesk'}}<span v-if="!busy">→</span></button></form>
    <p class="auth-switch">{{registering?'已经有账号？':'还没有账号？'}}<button :disabled="busy" @click="switchMode">{{registering?'去登录':'创建一个账号'}}</button></p>
    <div class="auth-footnote"><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg><span>你的项目只向自己的账号开放。<br>本版不发送验证邮件，请妥善保存密码。</span></div>
   </div><footer class="auth-footer">FlowDesk · Account & Project <span>v0.2.0</span></footer>
  </section>
 </div>
 <dialog ref="account" class="account-dialog" aria-labelledby="account-title"><template v-if="user"><div class="modal-heading"><h2 id="account-title">当前账号</h2><button class="close" aria-label="关闭账号信息" @click="account?.close()">×</button></div><div class="account-avatar">{{Array.from(user.username).slice(0,1).join('')}}</div><h3>{{user.username}}</h3><p class="account-email">{{user.email}}</p><dl><dt>账号编号</dt><dd>USER-{{String(user.id).padStart(4,'0')}}</dd><dt>账号范围</dt><dd>当前电脑上的 FlowDesk 项目库</dd></dl><p class="account-tip">当前版本支持注册、登录与项目隔离。资料编辑、修改密码和找回密码尚未开放。</p><p v-if="error" class="error" role="alert">{{error}}</p><button class="secondary account-logout" :disabled="busy" @click="logout">{{busy?'正在退出…':'退出登录'}}</button></template></dialog>
</template>
