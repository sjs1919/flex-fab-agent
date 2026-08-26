import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import DebugView from '../views/DebugView.vue'
import CasesView from '../views/CasesView.vue'
import ConfigView from '../views/ConfigView.vue'
import ScheduleView from '../views/ScheduleView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    // 页面路由放 /portal/ 下，与 API 代理前缀（/debug /config /ask）错开，避免直连冲突
    { path: '/portal/debug', name: 'debug', component: DebugView },
    { path: '/portal/cases', name: 'cases', component: CasesView },
    { path: '/portal/config', name: 'config', component: ConfigView },
    { path: '/portal/schedule', name: 'schedule', component: ScheduleView },
  ],
})
