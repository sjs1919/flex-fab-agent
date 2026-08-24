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
        <el-input v-model="adminToken" type="password" show-password style="width: 280px"
          placeholder="admin token（judge / 重跑用）" @change="saveToken" />
        <span style="color: #909399; font-size: 12px">token 仅存本机 localStorage</span>
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
            <div class="tree-node">
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
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { askTrace, judgeCase, type AskResponse, type JudgeResult, type SpanItem } from '../api/debug'

const query = ref('')
const loading = ref(false)
const error = ref('')
const result = ref<AskResponse | null>(null)
const adminToken = ref(localStorage.getItem('debug_admin_token') ?? '')
const judging = ref(false)
const judgeError = ref('')
const judge = ref<JudgeResult | null>(null)

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
</style>
