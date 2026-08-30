<script setup lang="ts">
import { getCurrentInstance } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

// 数据来源：docs/demo/08-test/调试台测试用例提示词-v1-2026-08-29.md 第五节（正式测试提示词，已核对 seed 数据）

// 15 分钟演示主线（推荐顺序，A→L）
const demoSteps: { id: string; title: string; ask: string; action?: string; write?: boolean }[] = [
  { id: 'A1', title: '查订单', ask: '帮我查一下所有还在排队的订单' },
  { id: 'A4', title: '订单详情', ask: '查一下订单 ORD001 的完整信息' },
  { id: 'B1', title: '设备负载', ask: '现在哪些设备在运行、哪些空闲、预计什么时候释放' },
  { id: 'D1', title: '库存', ask: '钛合金材料库存还剩多少' },
  { id: 'E1', title: '客户信息', ask: '查一下 C001 这个客户的信息' },
  { id: 'C1', title: '前道人池', ask: '前道人员池现在什么情况，排队多少，会不会成瓶颈' },
  { id: 'H2', title: '交期承诺', ask: '客户要 SLA 工艺 10 件、零件高 100mm，最快什么时候能交付' },
  { id: 'G1', title: '跑排产', ask: '请执行排产工具，帮我跑一轮排产并返回新版本号', write: true },
  { id: 'I1', title: '审批', ask: '请调用审批工具 approve_schedule，审批通过排产版本 ［G1 返回的版本号，如 50］', write: true },
  { id: 'F1', title: '批次排布', ask: '最新排产版本的批次排布是什么' },
  { id: 'J1', title: '产能负载', ask: '帮我评估一下当前产能负载' },
  { id: 'K1', title: '合同条款', ask: '广州航天精工的合同有什么特殊条款' },
  { id: 'L2', title: 'judge 打分', ask: '', action: '在调试台提问结果卡片点「judge 打分」按钮' },
]

// A-L 全部用例（仅调试台提问项；HTTP/UI 操作项标注方式）
const groups: { group: string; title: string; items: { id: string; ask: string; action?: string; write?: boolean }[] }[] = [
  {
    group: 'A',
    title: '查订单',
    items: [
      { id: 'A1', ask: '帮我查一下所有还在排队的订单' },
      { id: 'A2', ask: '交期在 2026-09-10 之前、A 级客户、SLA 工艺的订单有哪些，按优先级排序' },
      { id: 'A3', ask: '哪些订单最紧急，排前 5 个' },
      { id: 'A4', ask: '查一下订单 ORD001 的完整信息' },
      { id: 'A5', ask: 'ORD001 现在生产到哪个环节了' },
      { id: 'A6', ask: '帮我跟踪 ORD001，它前面还有多少单在等，预计什么时候能打' },
    ],
  },
  {
    group: 'B',
    title: '查设备',
    items: [
      { id: 'B1', ask: '现在哪些设备在运行、哪些空闲、预计什么时候释放' },
      { id: 'B2', ask: '帮我检查今天的设备负载风险，看看有没有订单可能延期' },
    ],
  },
  {
    group: 'C',
    title: '前道人员',
    items: [
      { id: 'C1', ask: '前道人员池现在什么情况，排队多少，会不会成瓶颈' },
      { id: 'C2', ask: '现在整体产能负载怎么样，前道人员够不够' },
      { id: 'C3', ask: '', action: 'HTTP：GET /resources/personnel（人员列表，非提问）' },
      { id: 'C4', ask: '', action: 'HTTP：PUT /resources/personnel/{pid}/status（状态切换，需 admin token）' },
    ],
  },
  {
    group: 'D',
    title: '查库存',
    items: [
      { id: 'D1', ask: '钛合金材料库存还剩多少' },
      { id: 'D2', ask: '哪些材料库存告急（低于 50）' },
    ],
  },
  {
    group: 'E',
    title: '查客户',
    items: [
      { id: 'E1', ask: '查一下 C001 这个客户的信息' },
      { id: 'E2', ask: 'S 级客户都有哪些' },
    ],
  },
  {
    group: 'F',
    title: '查批次 / 排产表',
    items: [
      { id: 'F1', ask: '最新排产版本的批次排布是什么' },
      { id: 'F2', ask: '看一下版本 5 的历史排产' },
      { id: 'F3', ask: '', action: 'HTTP：GET /schedule/latest（最新版本 + 批次）' },
      { id: 'F4', ask: '', action: 'HTTP：GET /resources/batches（批次列表）' },
    ],
  },
  {
    group: 'G',
    title: '排产（写）+ 插单',
    items: [
      { id: 'G1', ask: '请执行排产工具，帮我跑一轮排产并返回新版本号', write: true },
      { id: 'G2', ask: '插单之后帮我重新排一次产', write: true },
      { id: 'G4', ask: '最近有没有新订单插进来' },
      { id: 'G5', ask: '查一下有没有设备故障事件' },
    ],
  },
  {
    group: 'H',
    title: '预测 / 交期承诺',
    items: [
      { id: 'H1', ask: '未来 5 天各材料的订单量预测是多少' },
      { id: 'H2', ask: '客户要 SLA 工艺 10 件、零件高 100mm，最快什么时候能交付' },
      { id: 'H3', ask: '这笔 SLA 10 件能赶在 9 月 5 号前交吗' },
      { id: 'H4', ask: '客户要下 8 万的大单，SLA 20 件，报个交期' },
    ],
  },
  {
    group: 'I',
    title: '审批（写）',
    items: [
      { id: 'I1', ask: '请调用审批工具 approve_schedule，审批通过排产版本 ［G1 返回的版本号，如 50］', write: true },
      { id: 'I2', ask: '驳回最新版本，理由：交期太赶', write: true },
    ],
  },
  {
    group: 'J',
    title: '负载 / KPI / 良率',
    items: [
      { id: 'J1', ask: '帮我评估一下当前产能负载' },
      { id: 'J2', ask: '当前排产的准交率、延期金额、良率是多少' },
      { id: 'J3', ask: '最近打印良率怎么样，哪台设备最低' },
    ],
  },
  {
    group: 'K',
    title: '知识库（RAG）',
    items: [
      { id: 'K1', ask: '广州航天精工的合同有什么特殊条款' },
      { id: 'K2', ask: '深圳精密五金的延期记录有没有' },
    ],
  },
  {
    group: 'L',
    title: '仿真 + 调试台自身',
    items: [
      { id: 'L2', ask: '', action: '调试台：提问后点「judge 打分」按钮，看 answer_relevancy 分数' },
      { id: 'L3', ask: '', action: 'Case 台：标注 bad → 重跑 → 看 bad→good 转化率' },
      { id: 'L4', ask: '', action: '配置页：读写数据源 / 时钟速率 / 求解器预算 / 调试台三开关' },
    ],
  },
]

const emit = defineEmits<{ switchTab: [name: string] }>()
const instance = getCurrentInstance()
const router = useRouter()

// 作为 tab（PortalView 内，onSwitchTab 事件监听在 props 上）→ 切 tab；深链直访 → 整页跳对应路由
function goTab(name: string) {
  if (instance?.props?.onSwitchTab) emit('switchTab', name)
  else if (name === 'overview') router.push('/')
  else router.push(`/portal/${name}`)
}

async function copyAsk(ask: string) {
  try {
    await navigator.clipboard.writeText(ask)
    ElMessage.success('已复制，去调试台粘贴执行')
  } catch {
    // clipboard API 不可用（http 非安全上下文）时降级：临时 textarea 复制
    const ta = document.createElement('textarea')
    ta.value = ask
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('已复制（降级方式），去调试台粘贴执行')
  }
}
</script>

<template>
  <div class="manual">
    <div class="manual-header">
      <h1>调试台测试用例 · 现场演示脚本</h1>
      <p class="manual-sub">把提问复制到「调试」tab 输入框执行；写操作（跑排产/审批）需 admin token，调试台打开时自动签发。</p>
      <div class="manual-actions">
        <el-button type="primary" @click="goTab('overview')">← 返回首页</el-button>
        <el-button @click="goTab('debug')">去调试台</el-button>
      </div>
    </div>

    <!-- 15 分钟演示主线 -->
    <h2 class="section-title">15 分钟演示主线（推荐顺序）</h2>
    <div class="demo-steps">
      <div v-for="(s, i) in demoSteps" :key="s.id" class="demo-step">
        <div class="step-no">{{ i + 1 }}</div>
        <el-tag :type="s.write ? 'danger' : 'info'" size="small" class="step-id">{{ s.id }}</el-tag>
        <div class="step-body">
          <div class="step-title">{{ s.title }}<span v-if="s.write" class="step-write">写操作</span></div>
          <code class="step-ask">{{ s.ask || s.action }}</code>
        </div>
        <el-button size="small" type="primary" plain :disabled="!s.ask" @click="copyAsk(s.ask)">复制</el-button>
      </div>
    </div>

    <!-- 全部用例 -->
    <el-collapse style="margin-top: 24px">
      <el-collapse-item title="查看 A-L 全部用例（含 HTTP / UI 操作项）">
        <div v-for="g in groups" :key="g.group" class="group">
          <h3 class="group-title">{{ g.group }}. {{ g.title }}</h3>
          <div v-for="item in g.items" :key="item.id" class="group-item">
            <el-tag :type="item.write ? 'danger' : 'info'" size="small">{{ item.id }}</el-tag>
            <span class="group-item-text">{{ item.ask || item.action }}</span>
            <el-button size="small" plain :disabled="!item.ask" @click="copyAsk(item.ask)">复制</el-button>
          </div>
        </div>
        <p class="manual-note">来源：调试台测试用例提示词 v1（docs/demo/08-test/）。演示前建议：清缓存 → seed --reset → 起后端 → 冒烟通过。</p>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.manual {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}

.manual-header h1 {
  font-size: 24px;
  margin: 0 0 8px;
}

.manual-sub {
  color: #909399;
  font-size: 14px;
  margin: 0 0 16px;
  max-width: 760px;
  line-height: 1.6;
}

.manual-actions {
  display: flex;
  gap: 12px;
}

.section-title {
  font-size: 20px;
  margin: 32px 0 16px;
}

/* 15 分钟主线步骤 */
.demo-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.demo-step {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 8px;
}

.step-no {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-id {
  flex-shrink: 0;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 2px;
}

.step-write {
  margin-left: 6px;
  font-size: 11px;
  color: #f56c6c;
  border: 1px solid #fbc4c4;
  border-radius: 3px;
  padding: 0 4px;
}

.step-ask {
  display: block;
  font-size: 13px;
  color: #303133;
  background: #fff;
  border-radius: 4px;
  padding: 5px 8px;
  word-break: break-all;
  white-space: pre-wrap;
}

/* 全部用例 */
.group {
  margin-bottom: 16px;
}

.group-title {
  font-size: 15px;
  font-weight: 600;
  margin: 12px 0 8px;
}

.group-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-bottom: 1px solid #f0f2f5;
}

.group-item-text {
  flex: 1;
  font-size: 13px;
  color: #606266;
  min-width: 0;
}

.manual-note {
  color: #909399;
  font-size: 12px;
  margin-top: 12px;
}
</style>
