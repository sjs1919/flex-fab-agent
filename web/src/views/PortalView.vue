<script setup lang="ts">
import { nextTick, ref } from 'vue'
import DashboardView from './DashboardView.vue'
import DebugView from './DebugView.vue'
import ScheduleView from './ScheduleView.vue'
import CasesView from './CasesView.vue'
import ResourcesView from './ResourcesView.vue'
import ConfigView from './ConfigView.vue'
import OverviewView from './OverviewView.vue'
import DemoCasesView from './DemoCasesView.vue'
import LogView from './LogView.vue'

// 单页聚合：首页/看板/调试/审批/案例/资源/配置/演示/操作日志 全部 tab 化，lazy 首激活渲染避免并发请求
const activeTab = ref('overview')
const dashboardRef = ref<InstanceType<typeof DashboardView> | null>(null)

async function onTabChange(name: string | number) {
  // 看板 tab 从 display:none 恢复时 echarts 容器尺寸需重算（否则 0 宽或旧尺寸）
  if (name === 'dashboard') {
    await nextTick()
    dashboardRef.value?.resizeCharts()
  }
}

function onSwitchTab(name: string) {
  activeTab.value = name
}
</script>

<template>
  <el-tabs v-model="activeTab" type="border-card" lazy @tab-change="onTabChange" style="margin: 16px">
    <el-tab-pane label="首页" name="overview">
      <OverviewView @switch-tab="onSwitchTab" />
    </el-tab-pane>
    <el-tab-pane label="看板" name="dashboard">
      <DashboardView ref="dashboardRef" />
    </el-tab-pane>
    <el-tab-pane label="调试" name="debug">
      <DebugView @switch-tab="onSwitchTab" />
    </el-tab-pane>
    <el-tab-pane label="审批" name="schedule">
      <ScheduleView />
    </el-tab-pane>
    <el-tab-pane label="案例" name="cases">
      <CasesView />
    </el-tab-pane>
    <el-tab-pane label="资源" name="resources">
      <ResourcesView />
    </el-tab-pane>
    <el-tab-pane label="配置" name="config">
      <ConfigView />
    </el-tab-pane>
    <el-tab-pane label="演示" name="manual">
      <DemoCasesView @switch-tab="onSwitchTab" />
    </el-tab-pane>
    <el-tab-pane label="操作日志" name="logs">
      <LogView />
    </el-tab-pane>
  </el-tabs>
</template>
