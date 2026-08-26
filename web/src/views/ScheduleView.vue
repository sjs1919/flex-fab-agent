<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchVersions, approveSchedule, type ScheduleVersion } from '../api/schedule'

const versions = ref<ScheduleVersion[]>([])
const loading = ref(false)
const adminToken = ref(localStorage.getItem('admin_token') || '')

async function load() {
  loading.value = true
  try {
    versions.value = await fetchVersions()
  } finally {
    loading.value = false
  }
}

function saveToken() {
  localStorage.setItem('admin_token', adminToken.value.trim())
  ElMessage.success('admin token 已保存')
}

async function act(v: ScheduleVersion, action: '通过' | '驳回') {
  const token = adminToken.value.trim()
  if (!token) {
    ElMessage.warning('请先填写并保存 admin token')
    return
  }
  const res = await approveSchedule(v.id, action, token)
  if (res.ok) ElMessage.success(res.message)
  else ElMessage.error(res.message)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="schedule-page">
    <h2>排产版本审批</h2>
    <div class="toolbar">
      <el-input v-model="adminToken" placeholder="admin token（R-7 写端点鉴权）" style="width: 320px" />
      <el-button type="primary" @click="saveToken">保存 token</el-button>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>
    <el-table :data="versions" v-loading="loading" border stripe>
      <el-table-column prop="id" label="版本" width="80" />
      <el-table-column prop="created_at" label="生成时间" />
      <el-table-column prop="triggered_by" label="触发方式" width="120" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column prop="batch_count" label="批次数" width="100" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" type="success" :disabled="row.status !== '待审核'" @click="act(row, '通过')">通过</el-button>
          <el-button size="small" type="danger" :disabled="row.status !== '待审核'" @click="act(row, '驳回')">驳回</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.schedule-page { padding: 16px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
</style>
