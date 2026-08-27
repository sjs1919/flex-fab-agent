<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchResources, setPersonnelStatus, type ResourceCategory } from '../api/resources'

const categories: { name: ResourceCategory; label: string }[] = [
  { name: 'machines', label: '设备' },
  { name: 'customers', label: '客户' },
  { name: 'orders', label: '订单' },
  { name: 'inventory', label: '库存' },
  { name: 'batches', label: '批次' },
  { name: 'preprocess', label: '前道' },
  { name: 'personnel', label: '人员' },
]

const active = ref<ResourceCategory>('machines')
const items = ref<Record<string, unknown>[]>([])
const loading = ref(false)
const error = ref('')
const togglingId = ref('')
// 列 = 首行 key（完整展示全部字段，防字段漏展示）
const columns = ref<{ prop: string }[]>([])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const rows = await fetchResources(active.value)
    items.value = rows
    columns.value = rows.length ? Object.keys(rows[0]).map((prop) => ({ prop })) : []
  } catch (e) {
    error.value = `加载失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    loading.value = false
  }
}

async function switchTab(name: string | number) {
  active.value = name as ResourceCategory
  await load()
}

async function toggleStatus(row: Record<string, unknown>) {
  const token = localStorage.getItem('debug_admin_token') || ''
  if (!token) { ElMessage.warning('请先在调试 tab 获取 admin token'); return }
  togglingId.value = String(row.id)
  try {
    const res = await setPersonnelStatus(String(row.id), row.status === '上班' ? '请假' : '上班', token)
    if (res.ok) ElMessage.success(res.message); else ElMessage.error(res.message)
  } catch (err) {
    ElMessage.error(err instanceof Error && err.message ? err.message : '状态切换失败')
  } finally { togglingId.value = '' }
  await load()
}

onMounted(load)
</script>

<template>
  <div style="padding: 16px">
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 12px" />
    <div style="display: flex; justify-content: flex-end; margin-bottom: 8px">
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-tabs :model-value="active" lazy @tab-change="switchTab">
      <el-tab-pane v-for="c in categories" :key="c.name" :label="c.label" :name="c.name">
        <el-table :data="items" v-loading="loading" border stripe size="small" max-height="520">
          <el-table-column v-for="col in columns" :key="col.prop" :prop="col.prop" :label="col.prop"
            show-overflow-tooltip />
          <el-table-column v-if="active === 'personnel'" label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :type="row.status === '上班' ? 'warning' : 'success'"
                :loading="togglingId === row.id"
                @click="toggleStatus(row)">
                {{ row.status === '上班' ? '请假' : '回岗' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loading && !items.length" description="暂无数据" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
