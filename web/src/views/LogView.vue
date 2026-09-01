<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchLogs, type LogPage, type OperationCategory } from '../api/log'

const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const items = ref<LogPage['items']>([])
const loading = ref(false)

const category = ref<'' | OperationCategory>('')
const dateRange = ref<[string, string] | null>(null)
const keyword = ref('')

function fmtTime(v: string | null): string {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '-'
}

async function load() {
  loading.value = true
  try {
    const [start, end] = dateRange.value
      ? [`${dateRange.value[0]} 00:00:00`, `${dateRange.value[1]} 23:59:59`]
      : [undefined, undefined]
    const data = await fetchLogs({
      category: category.value || undefined,
      start,
      end,
      keyword: keyword.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载操作日志失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

function onReset() {
  category.value = ''
  dateRange.value = null
  keyword.value = ''
  page.value = 1
  load()
}

const categoryTag: Record<string, 'warning' | 'primary' | 'success' | 'danger'> = {
  auto: 'warning',
  simulator: 'primary',
  manual: 'success',
  debug: 'danger',
}
const categoryLabel: Record<string, string> = {
  auto: '自动',
  simulator: '模拟器',
  manual: '手工',
  debug: '调试',
}

onMounted(load)
</script>

<template>
  <div>
    <div style="margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap">
      <el-select v-model="category" placeholder="全部类别" clearable style="width: 120px">
        <el-option label="自动" value="auto" />
        <el-option label="模拟器" value="simulator" />
        <el-option label="手工" value="manual" />
        <el-option label="调试" value="debug" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
      />
      <el-input
        v-model="keyword"
        placeholder="搜索动作/摘要/trace_id"
        clearable
        style="width: 240px"
        @keyup.enter="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column label="现实时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.real_time) }}</template>
      </el-table-column>
      <el-table-column label="类别" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.category === 'debug'" size="small" color="#f3e8ff"
                  style="color:#7c3aed; border-color:#e9d5ff">调试</el-tag>
          <el-tag v-else :type="categoryTag[row.category]" size="small">
            {{ categoryLabel[row.category] ?? row.category }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="action" label="动作" width="150" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ok' ? 'success' : 'danger'" size="small">
            {{ row.status === 'ok' ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
      <el-table-column label="模拟时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.sim_time) }}</template>
      </el-table-column>
      <el-table-column prop="trace_id" label="trace_id" width="130" show-overflow-tooltip />
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      style="margin-top: 12px"
      @current-change="load"
      @size-change="onSearch"
    />
  </div>
</template>
