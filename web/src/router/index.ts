import { createRouter, createWebHistory } from 'vue-router'
import PortalView from '../views/PortalView.vue'
import DebugView from '../views/DebugView.vue'
import CasesView from '../views/CasesView.vue'
import ConfigView from '../views/ConfigView.vue'
import ScheduleView from '../views/ScheduleView.vue'
import DemoCasesView from '../views/DemoCasesView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    // 单页聚合入口：看板/调试/审批/案例/配置 tab 切换
    { path: '/', name: 'portal', component: PortalView },
    // 深链路由保留：直访进对应页面（不经聚合 tab）
    { path: '/portal/debug', name: 'debug', component: DebugView },
    { path: '/portal/cases', name: 'cases', component: CasesView },
    { path: '/portal/config', name: 'config', component: ConfigView },
    { path: '/portal/schedule', name: 'schedule', component: ScheduleView },
    { path: '/portal/manual', name: 'manual', component: DemoCasesView },
  ],
})
