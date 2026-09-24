import {createApp} from 'vue';
import {createRouter, createWebHashHistory} from 'vue-router';
import App from './App.vue';
import './style.css';
import './auth.css';
const Empty = {template:'<span />'};
const router = createRouter({history:createWebHashHistory(),routes:[{path:'/',component:Empty},{path:'/projects/:id',component:Empty},{path:'/workspaces/:id',component:Empty},{path:'/:pathMatch(.*)*',redirect:'/'}]});
createApp(App).use(router).mount('#app');
