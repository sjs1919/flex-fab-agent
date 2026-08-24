<template>
  <div style="padding: 24px; max-width: 1200px; margin: 0 auto">
    <h1>配置</h1>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 16px" />
    <el-alert v-if="msg" type="success" :title="msg" show-icon :closable="false" style="margin-bottom: 16px" />

    <el-card v-loading="loading" shadow="never">
      <template #header>关键配置（GET /config，匿名可读）</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="数据源">{{ cfg?.data_source ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="模拟时钟 tick（秒）">{{ cfg?.sim_tick_seconds ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="求解器超时预算（秒）">{{ cfg?.solver_timeout_override ?? '—' }}</el-descriptions-item>
      </el-descriptions>

      <h3 style="margin-top: 16px">调试台开关（system_config 表，PUT /config 写）</h3>
      <div style="display: flex; flex-direction: column; gap: 16px; margin-top: 12px; max-width: 520px">
        <div class="row">
          <span class="label">case_collection_enabled（/ask 是否落 case）</span>
          <el-switch :model-value="switches.case_collection_enabled === 'on'"
            @change="(v: boolean) => switches.case_collection_enabled = v ? 'on' : 'off'" />
        </div>
        <div class="row">
          <span class="label">sample_rate（采样率 0~1，生产 0.1）</span>
          <el-input-number :model-value="Number(switches.sample_rate)" :min="0" :max="1" :step="0.1"
            @change="(v: number | undefined) => switches.sample_rate = String(v ?? 1)" />
        </div>
        <div class="row">
          <span class="label">judge_enabled（落 case 顺带打分，默认 off 省钱）</span>
          <el-switch :model-value="switches.judge_enabled === 'on'"
            @change="(v: boolean) => switches.judge_enabled = v ? 'on' : 'off'" />
        </div>
        <div class="row">
          <el-input v-model="adminToken" type="password" show-password style="width: 240px"
            placeholder="admin token（保存用）" @change="saveToken" />
          <el-button type="primary" :disabled="!adminToken" :loading="saving" @click="save">保存调试台开关</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchConfig, saveConfig, type ConfigView } from '../api/config'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const msg = ref('')
const cfg = ref<ConfigView | null>(null)
const adminToken = ref(localStorage.getItem('debug_admin_token') ?? '')
const switches = reactive({ case_collection_enabled: 'on', sample_rate: '1.0', judge_enabled: 'off' })

function saveToken() {
  localStorage.setItem('debug_admin_token', adminToken.value)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    cfg.value = await fetchConfig()
    switches.case_collection_enabled = cfg.value.调试台.case_collection_enabled
    switches.sample_rate = cfg.value.调试台.sample_rate
    switches.judge_enabled = cfg.value.调试台.judge_enabled
  } catch (e) {
    error.value = `配置加载失败：${e instanceof Error ? e.message : String(e)}（请确认 API :8000 已启动）`
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!adminToken.value) {
    ElMessage.warning('请输入 admin token')
    return
  }
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const pairs: Array<[string, string]> = [
      ['case_collection_enabled', switches.case_collection_enabled],
      ['sample_rate', switches.sample_rate],
      ['judge_enabled', switches.judge_enabled],
    ]
    for (const [key, value] of pairs) {
      await saveConfig('调试台', key, value, adminToken.value)
    }
    msg.value = '已保存（system_config 实时生效）'
  } catch (e) {
    error.value = `保存失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.label {
  color: #606266;
  font-size: 13px;
}
</style>
