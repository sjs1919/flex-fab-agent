<template>
  <div style="padding: 24px; max-width: 1200px; margin: 0 auto">
    <h1>案例台</h1>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 16px" />

    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6"><el-card shadow="never"><el-statistic title="总 case" :value="stats?.total ?? 0" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="good" :value="stats?.good_count ?? 0" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="bad" :value="stats?.bad_count ?? 0" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="bad→good 转化率" :value="rateText" /></el-card></el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
          <span>Case 列表（{{ cases.length }}）</span>
          <el-select v-model="typeFilter" style="width: 140px" @change="load">
            <el-option label="全部类型" value="" />
            <el-option label="normal" value="normal" />
            <el-option label="chitchat" value="chitchat" />
            <el-option label="empty" value="empty" />
          </el-select>
          <el-select v-model="goodFilter" style="width: 140px" @change="load">
            <el-option label="全部标注" value="" />
            <el-option label="good" value="true" />
            <el-option label="bad" value="false" />
            <el-option label="未标注" value="null" />
          </el-select>
          <el-input v-model="adminToken" type="password" show-password style="width: 240px"
            placeholder="admin token（标注 / 重跑用）" @change="saveToken" />
          <el-button :loading="loading" @click="load">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="cases" size="small">
        <el-table-column prop="trace_id" label="trace_id" width="120" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="query" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.query }}</template>
        </el-table-column>
        <el-table-column label="type" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.type)">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标注" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.good !== null" size="small" :type="row.good ? 'success' : 'danger'">
              {{ row.good ? 'good' : 'bad' }}
            </el-tag>
            <span v-else style="color: #c0c4cc">—</span>
          </template>
        </el-table-column>
        <el-table-column label="tools" width="70">
          <template #default="{ row }">{{ (row.tools || []).length }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-dropdown v-if="row.type === 'normal'" @command="(c: string) => mark(row, c === 'good')">
              <el-button size="small">标注</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="good">good</el-dropdown-item>
                  <el-dropdown-item command="bad">bad</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button size="small" style="margin-left: 6px" @click="openReplay(row)">回放</el-button>
            <el-button size="small" type="primary" :disabled="!adminToken" @click="rerun(row)">重跑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" size="520px" :title="`回放 ${replayId}`">
      <div v-loading="replayLoading">
        <template v-if="replay">
          <h4>case</h4>
          <p style="margin: 4px 0"><b>query：</b>{{ replay.case?.query ?? '（无 case 记录）' }}</p>
          <p style="margin: 4px 0"><b>answer：</b></p>
          <p style="margin: 4px 0; white-space: pre-wrap">{{ replay.case?.answer ?? '—' }}</p>
          <h4 style="margin-top: 16px">trace（{{ replay.trace.total_ms }} ms / {{ replay.trace.span_count }} span）</h4>
          <el-tag v-for="(n, k) in replay.trace.by_kind" :key="k" size="small" style="margin-right: 4px">
            {{ k }}×{{ n }}
          </el-tag>
          <ul style="margin-top: 12px; padding-left: 16px">
            <li v-for="(s, i) in replay.trace.spans" :key="i">
              {{ s.name }} · {{ s.ms }} ms
              <div v-if="s.attrs.arguments != null" class="attr">入参 {{ String(s.attrs.arguments) }}</div>
              <div v-if="s.attrs.result != null" class="attr">出参 {{ String(s.attrs.result) }}</div>
            </li>
          </ul>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchCases, fetchStats, fetchTrace, labelCase, rerunCase, type CaseRecord, type DebugStats, type SpanItem } from '../api/debug'

const loading = ref(false)
const error = ref('')
const cases = ref<CaseRecord[]>([])
const stats = ref<DebugStats | null>(null)
const typeFilter = ref('')
const goodFilter = ref('')
const adminToken = ref(localStorage.getItem('debug_admin_token') ?? '')
const drawer = ref(false)
const replayLoading = ref(false)
const replayId = ref('')
const replay = ref<{ trace: { total_ms: number; span_count: number; by_kind: Record<string, number>; spans: SpanItem[] }; case: CaseRecord | null } | null>(null)

const rateText = computed(() =>
  stats.value?.bad_to_good_rate == null ? '—' : `${(stats.value.bad_to_good_rate * 100).toFixed(0)}%`)

function saveToken() {
  localStorage.setItem('debug_admin_token', adminToken.value)
}

function typeTag(t: string) {
  return t === 'normal' ? 'primary' : t === 'chitchat' ? 'warning' : 'info'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [items, s] = await Promise.all([
      fetchCases(typeFilter.value || undefined, goodFilter.value || undefined),
      fetchStats(),
    ])
    cases.value = items
    stats.value = s
  } catch (e) {
    error.value = `加载失败：${e instanceof Error ? e.message : String(e)}（请确认 API :8000 已启动）`
  } finally {
    loading.value = false
  }
}

async function mark(row: CaseRecord, good: boolean) {
  if (!adminToken.value) {
    ElMessage.warning('请输入 admin token')
    return
  }
  try {
    await labelCase(row.trace_id, good, adminToken.value)
    ElMessage.success(`已标注 ${good ? 'good' : 'bad'}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function rerun(row: CaseRecord) {
  if (!adminToken.value) {
    ElMessage.warning('请输入 admin token')
    return
  }
  try {
    const r = await rerunCase(row.trace_id, adminToken.value)
    ElMessage.success(`重跑完成，新 trace：${r.new_trace_id}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function openReplay(row: CaseRecord) {
  replayId.value = row.trace_id
  drawer.value = true
  replayLoading.value = true
  try {
    replay.value = await fetchTrace(row.trace_id)
  } catch (e) {
    replay.value = null
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    replayLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.attr {
  color: #c0c4cc;
  font-size: 12px;
  max-width: 440px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
