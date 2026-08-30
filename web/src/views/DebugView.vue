<template>
  <div style="padding: 24px; max-width: 1200px; margin: 0 auto">
    <h1>排产调试台</h1>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 16px" />

    <el-card shadow="never">
      <template #header>提问</template>
      <el-input v-model="query" type="textarea" :rows="3"
        placeholder="输入排产问题，例如：帮我检查今天的设备负载风险，看看有哪些订单可能延期" />
      <div style="margin-top: 12px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
        <el-button type="primary" :loading="loading" @click="submit">执行提问</el-button>
        <el-input v-model="adminToken" type="text" style="width: 300px"
          placeholder="admin token（judge / 重跑用，已自动签发）" @change="saveToken" />
        <el-button size="small" :disabled="!adminToken" @click="copyToken">复制 token</el-button>
        <span style="color: #909399; font-size: 12px">token 自动签发，仅存本机 localStorage，1h 有效</span>
      </div>
      <div style="margin-top: 8px">
        <el-button link type="primary" @click="goDemo">查看演示脚本（测试用例提问，可一键复制）→</el-button>
      </div>
    </el-card>

    <el-skeleton v-if="loading" :rows="6" animated style="margin-top: 16px" />

    <template v-else-if="result">
      <el-card shadow="never" style="margin-top: 16px">
        <template #header>
          <span>答案</span>
          <el-tag size="small" style="margin-left: 8px">{{ result.trace_id }}</el-tag>
        </template>
        <p style="white-space: pre-wrap">{{ result.answer }}</p>
        <div style="margin-top: 12px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
          <el-button size="small" type="warning" :loading="judging" :disabled="!adminToken" @click="runJudge">
            judge 打分{{ judge ? '（重新）' : '' }}
          </el-button>
          <span v-if="!adminToken" style="color: #909399; font-size: 12px">输入 admin token 后启用 judge</span>
          <el-alert v-if="judgeError" type="error" :title="judgeError" show-icon :closable="false" style="flex-basis: 100%" />
        </div>
        <div v-if="judge" style="margin-top: 12px">
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="答案相关度">
              <el-tag :type="(judge.answer_relevancy ?? 0) >= 0.5 ? 'success' : 'danger'">
                {{ judge.answer_relevancy ?? '—' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-for="[k, v] in judgeEntries" :key="k" :label="k">{{ String(v) }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-card>

      <el-card shadow="never" style="margin-top: 16px">
        <template #header>
          <span>链路（{{ result.trace.total_ms }} ms / {{ result.trace.span_count }} span）</span>
          <el-tag v-for="(n, k) in result.trace.by_kind" :key="k" size="small" style="margin-left: 6px">
            {{ k }}×{{ n }}
          </el-tag>
        </template>
        <el-empty v-if="!traceTree.length" description="本轮无 span" />
        <el-tree v-else :data="traceTree" node-key="id" :props="{ label: 'name', children: 'children' }"
          :expand-on-click-node="false">
          <template #default="{ data }">
            <div class="tree-node" @click.stop="openDetail(data)" title="点击查看完整详情">
              <el-tag size="small" effect="plain"
                :type="data.attrs?.tool_success === false ? 'danger' : 'info'"
                style="margin-right: 6px">{{ data.name }}</el-tag>
              <span class="node-ms">{{ data.ms == null ? '—' : data.ms.toFixed(1) + ' ms' }}</span>
              <span v-if="data.attrs?.tool_success === false" class="node-fail">执行失败</span>
              <span v-if="data.attrs?.arguments != null" class="node-attr" :title="String(data.attrs?.arguments)">
                入参 {{ String(data.attrs?.arguments) }}
              </span>
              <span v-if="data.attrs?.result != null" class="node-attr" :title="String(data.attrs?.result)">
                出参 {{ String(data.attrs?.result) }}
              </span>
            </div>
          </template>
        </el-tree>
      </el-card>
    </template>

    <el-empty v-else description="输入问题后点击「执行提问」，查看两级链路与 judge 打分" style="margin-top: 32px" />

    <el-dialog v-model="detailVisible" :title="detail ? detail.name : 'Span 详情'" width="720px">
      <template v-if="detail">
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item label="耗时">{{ detail.ms == null ? '—' : detail.ms.toFixed(1) + ' ms' }}</el-descriptions-item>
          <el-descriptions-item label="父节点">{{ detail.parent ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="执行结果">
            <el-tag :type="detail.attrs?.tool_success === false ? 'danger' : 'success'">
              {{ detail.attrs?.tool_success === false ? '失败' : '成功' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.attrs?.arguments != null" label="入参">
            <pre class="detail-pre">{{ pretty(detail.attrs.arguments) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.attrs?.result != null" label="出参">
            <pre class="detail-pre">{{ pretty(detail.attrs.result) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="完整 attrs">
            <pre class="detail-pre">{{ detailJson }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { askTrace, fetchAdminToken, judgeCase, type AskResponse, type JudgeResult, type SpanItem } from '../api/debug'

const emit = defineEmits<{ switchTab: [name: string] }>()
const instance = getCurrentInstance()
const router = useRouter()

// 作为 tab（PortalView 内，onSwitchTab 事件监听在 props 上）→ 切到「演示」tab；深链直访 → 整页跳
function goDemo() {
  if (instance?.props?.onSwitchTab) emit('switchTab', 'manual')
  else router.push('/portal/manual')
}

const query = ref('')
const loading = ref(false)
const error = ref('')
const result = ref<AskResponse | null>(null)
const adminToken = ref(localStorage.getItem('debug_admin_token') ?? '')
const judging = ref(false)
const judgeError = ref('')
const judge = ref<JudgeResult | null>(null)
// span 详情弹窗（点击链路节点展开完整入参/出参/元数据）
const detail = ref<SpanItem | null>(null)
const detailVisible = ref(false)
const detailJson = computed(() => (detail.value ? JSON.stringify(detail.value, null, 2) : ''))

function pretty(v: unknown): string {
  if (typeof v === 'string') {
    try { return JSON.stringify(JSON.parse(v), null, 2) } catch { return v }
  }
  return JSON.stringify(v, null, 2)
}

function openDetail(data: SpanItem) {
  detail.value = data
  detailVisible.value = true
}

interface TreeNode extends SpanItem {
  id: number
  children: TreeNode[]
}

// spans 是前序遍历平铺（父先入栈后出栈），按 parent 名 + 栈重建树，
// 同名 span（如两次 tool:query_orders）靠「最近未闭合的匹配父」归位
function buildTree(spans: SpanItem[]): TreeNode[] {
  const roots: TreeNode[] = []
  const stack: TreeNode[] = []
  let seq = 0
  for (const sp of spans) {
    while (stack.length && stack[stack.length - 1].name !== sp.parent) stack.pop()
    const node: TreeNode = { ...sp, id: seq++, children: [] }
    if (stack.length) stack[stack.length - 1].children.push(node)
    else roots.push(node)
    stack.push(node)
  }
  return roots
}

const traceTree = computed<TreeNode[]>(() => buildTree(result.value?.trace.spans ?? []))

const judgeEntries = computed(() => {
  const j = judge.value
  if (!j) return []
  return Object.entries(j).filter(([k]) => k !== 'answer_relevancy' && k !== 'judged_answer')
})

function saveToken() {
  localStorage.setItem('debug_admin_token', adminToken.value)
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(adminToken.value)
    ElMessage.success('admin token 已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中输入框内容复制')
  }
}

onMounted(async () => {
  // 本地 flex-fab-agent 便利：每次进页面签发新 admin token（R-7 写端点需要；token 1h 过期，
  // 旧缓存直接覆盖，避免 localStorage 里存过期 token 导致 judge 持续 401）
  try {
    const { token } = await fetchAdminToken()
    adminToken.value = token
    saveToken()
  } catch {
    /* 端点不可用时忽略，可手动输入 */
  }
})

async function submit() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  judge.value = null
  judgeError.value = ''
  try {
    result.value = await askTrace(q)
  } catch (e) {
    error.value = `提问失败：${e instanceof Error ? e.message : String(e)}（请确认 API :8000 已启动）`
  } finally {
    loading.value = false
  }
}

async function runJudge() {
  if (!result.value || !adminToken.value) return
  judging.value = true
  judgeError.value = ''
  try {
    const { judge: j } = await judgeCase(result.value.trace_id, adminToken.value)
    judge.value = j
  } catch (e) {
    judgeError.value = `judge 失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    judging.value = false
  }
}
</script>

<style scoped>
.tree-node {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  cursor: pointer;
}
.node-ms {
  color: #909399;
  font-size: 12px;
}
.node-fail {
  color: #f56c6c;
  font-size: 12px;
}
.node-attr {
  color: #c0c4cc;
  font-size: 12px;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-pre {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  font-size: 12px;
  background: #f5f7fa;
  border-radius: 4px;
  padding: 8px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
