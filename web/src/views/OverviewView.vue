<script setup lang="ts">
// 系统介绍页（首页 tab）——纯静态展示，零 API 依赖
// 数字来源：docs/demo/02-specs/2026-08-30-系统介绍页-design.md §7（已核对源码）
const heroStats = [
  { label: '种子订单', value: 20, note: '模拟真实排产压力' },
  { label: '打印设备', value: 7, note: '排产就是排这些机器的活' },
  { label: '操作页', value: 6, note: '除本介绍页外的功能页' },
  { label: '智能工具', value: 18, note: '系统自己会用的能力' },
]

const pains = [
  { icon: '🕓', title: '手工排产慢', desc: '订单一多靠 Excel 排，排一轮要半天' },
  { icon: '🔀', title: '插单就打乱', desc: '来张急单或设备故障，整张排产表推倒重来' },
  { icon: '❓', title: '交期拍脑袋', desc: '什么时候能交付说不准，客户追问只能估' },
]

const flowSteps = [
  { step: '① 下单', who: '客户', desc: '客户订单进入系统，先排队' },
  { step: '② 待排队', who: '系统自动', desc: '按交期和优先级排好队' },
  { step: '③ 自动排产', who: '系统自动', desc: '算出每件货在哪台设备、什么时候做（数学规划，不是猜）' },
  { step: '④ 审批', who: '排版人', desc: '排产方案先通过审批再执行（可自动批）' },
  { step: '⑤ 上机打印', who: '系统 + 设备', desc: '订单进入打印中，占用设备' },
  { step: '⑥ 完成', who: '系统自动', desc: '打印完成、设备释放、看板数据更新' },
]

const abilities = [
  { name: '对话问订单', desc: '用大白话查订单、设备、库存、客户', ask: '现在有哪些紧急订单？', tab: 'debug' },
  { name: '自动排产', desc: '一键跑排产，给出批次和交期', ask: '帮我跑一轮排产', tab: 'debug' },
  { name: '审批决策', desc: '排产方案一键通过或驳回', ask: '审批通过最新排产版本', tab: 'schedule' },
  { name: '监控看板', desc: 'KPI、准交率、延期金额、良率一屏看', ask: '当前准交率和良率是多少', tab: 'dashboard' },
]

const reliability = [
  { value: '61', label: '自动化测试文件', note: '一键全绿，mock LLM 不花钱' },
  { value: 'S0-S11', label: '冒烟测试十二步', note: '部署后分层自检' },
  { value: '≥7/10', label: '评估门禁', note: '三层评估达标才放行' },
]

// 现场 15 分钟演示脚本入口：切到「演示」tab（DemoCasesView，提问可一键复制）
function goManual() {
  emit('switchTab', 'manual')
}

const layers = [
  { name: '数据层', note: '订单 / 设备 / 库存 / 客户，所有业务数据的家' },
  { name: '求解层', note: '数学规划引擎，算最优排单方案' },
  { name: '模拟层', note: '生产流程仿真，跑「如果」看结果' },
  { name: '智能体层', note: '听懂人话、会自己调用工具干活' },
  { name: '服务层', note: '把能力变成接口，供界面调用' },
  { name: '界面层', note: 'Web 控制台，人看的窗口' },
]

const highlights = [
  { title: '数学规划排产', desc: '不是拍脑袋，是用约束求解算全局最优（CP-SAT 数学规划引擎）' },
  { title: '全链路自动化', desc: '从下单到完成无人值守，同一订单只被打印一次（幂等防重复）' },
  { title: '对话式智能体', desc: '用自然语言就能查数据、跑排产、批版本（18 种工具自动调度）' },
]

const versionLine = [
  { v: 'v1', time: '2026-08-04', label: '对话助手' },
  { v: 'v2', time: '2026-08-25', label: '制造业主线' },
  { v: 'v3', time: '2026-08-30', label: '自动化 + 前端' },
]

const emit = defineEmits<{ switchTab: [name: string] }>()
</script>

<template>
  <div class="overview">
    <!-- ① Hero：这是什么系统 -->
    <section class="hero">
      <h1>面向 3D 打印柔性制造的智能排产系统</h1>
      <p class="hero-sub">订单进来自动排队、电脑算出最优排单方案、全程不用人盯，从下单到打印完成自动闭环</p>
      <div class="hero-stats">
        <div v-for="s in heroStats" :key="s.label" class="stat-card">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
          <div class="stat-note">{{ s.note }}</div>
        </div>
      </div>
    </section>

    <!-- ② 业务痛点：解决什么问题 -->
    <section>
      <h2>它解决什么问题</h2>
      <div class="pains">
        <div v-for="p in pains" :key="p.title" class="pain-card">
          <div class="pain-icon">{{ p.icon }}</div>
          <div class="pain-title">{{ p.title }}</div>
          <div class="pain-desc">{{ p.desc }}</div>
        </div>
      </div>
    </section>

    <!-- ③ 业务闭环：核心区 -->
    <section>
      <h2>业务怎么跑通</h2>
      <p class="section-sub">从下单到打印完成，6 步自动闭环</p>
      <div class="flow">
        <template v-for="(f, i) in flowSteps" :key="f.step">
          <div class="flow-card">
            <div class="flow-step">{{ f.step }}</div>
            <div class="flow-who">{{ f.who }}</div>
            <div class="flow-desc">{{ f.desc }}</div>
          </div>
          <div v-if="i < flowSteps.length - 1" class="flow-arrow">→</div>
        </template>
      </div>
    </section>

    <!-- ④ 能力速览：能做什么 -->
    <section>
      <h2>能做什么</h2>
      <div class="abilities">
        <div v-for="a in abilities" :key="a.name" class="ability-card">
          <div class="ability-name">{{ a.name }}</div>
          <div class="ability-desc">{{ a.desc }}</div>
          <div class="ability-ask">「{{ a.ask }}」</div>
          <el-button type="primary" plain @click="emit('switchTab', a.tab)">去试试</el-button>
        </div>
      </div>
    </section>

    <!-- ⑤ 可靠性：怎么证明可靠 -->
    <section>
      <h2>怎么证明可靠</h2>
      <div class="reliability">
        <div v-for="r in reliability" :key="r.label" class="reliability-card">
          <div class="reliability-value">{{ r.value }}</div>
          <div class="reliability-label">{{ r.label }}</div>
          <div class="reliability-note">{{ r.note }}</div>
        </div>
      </div>
      <div class="demo-entry">
        <p class="demo-entry-text">现场 15 分钟演示脚本：13 步主线，提问可一键复制到调试台。</p>
        <el-button type="primary" plain @click="goManual">打开演示脚本</el-button>
      </div>
    </section>

    <!-- ⑥ 技术架构：技术底座（点到为止） -->
    <section>
      <h2>技术底座</h2>
      <div class="layers">
        <div v-for="l in layers" :key="l.name" class="layer">
          <span class="layer-name">{{ l.name }}</span>
          <span class="layer-note">{{ l.note }}</span>
        </div>
      </div>
      <h3 class="sub-title">三个设计亮点</h3>
      <div class="highlights">
        <div v-for="h in highlights" :key="h.title" class="highlight-card">
          <div class="highlight-title">{{ h.title }}</div>
          <div class="highlight-desc">{{ h.desc }}</div>
        </div>
      </div>
    </section>

    <!-- ⑦ 从哪开始 -->
    <section>
      <h2>从哪开始</h2>
      <div class="actions">
        <el-button type="primary" @click="emit('switchTab', 'debug')">试试调试台</el-button>
        <el-button @click="emit('switchTab', 'schedule')">查看审批</el-button>
        <el-button @click="emit('switchTab', 'resources')">看资源</el-button>
        <el-button @click="emit('switchTab', 'config')">看配置</el-button>
      </div>
      <div class="versions">
        <template v-for="(v, i) in versionLine" :key="v.v">
          <div class="version">
            <div class="version-v">{{ v.v }}</div>
            <div class="version-time">{{ v.time }}</div>
            <div class="version-label">{{ v.label }}</div>
          </div>
          <div v-if="i < versionLine.length - 1" class="version-arrow">→</div>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.overview {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

section {
  margin-top: 40px;
}

section h2 {
  font-size: 22px;
  font-weight: 600;
  margin-bottom: 4px;
}

.section-sub {
  color: #909399;
  font-size: 14px;
  margin-bottom: 16px;
}

/* ① Hero */
.hero {
  text-align: center;
  padding: 24px 0 8px;
}

.hero h1 {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 12px;
}

.hero-sub {
  color: #606266;
  font-size: 16px;
  max-width: 720px;
  margin: 0 auto 28px;
  line-height: 1.7;
}

.hero-stats {
  display: flex;
  gap: 16px;
}

.stat-card {
  flex: 1;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 18px 12px;
}

.stat-value {
  font-size: 40px;
  font-weight: 700;
  color: #409eff;
  line-height: 1.2;
}

.stat-label {
  font-size: 15px;
  font-weight: 600;
  margin-top: 4px;
}

.stat-note {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* ② 痛点 */
.pains {
  display: flex;
  gap: 16px;
}

.pain-card {
  flex: 1;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}

.pain-icon {
  font-size: 32px;
}

.pain-title {
  font-size: 16px;
  font-weight: 600;
  margin: 10px 0 6px;
}

.pain-desc {
  color: #909399;
  font-size: 14px;
  line-height: 1.6;
}

/* ③ 业务闭环 */
.flow {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.flow-card {
  flex: 1 1 150px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px;
  background: #fff;
}

.flow-step {
  font-weight: 700;
  font-size: 15px;
  color: #409eff;
}

.flow-who {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 4px;
  padding: 1px 6px;
}

.flow-desc {
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.flow-arrow {
  align-self: center;
  color: #c0c4cc;
  font-size: 20px;
  flex-shrink: 0;
}

/* ④ 能力速览 */
.abilities {
  display: flex;
  gap: 16px;
}

.ability-card {
  flex: 1;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 20px 16px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.ability-name {
  font-size: 17px;
  font-weight: 700;
}

.ability-desc {
  color: #606266;
  font-size: 14px;
  margin: 10px 0;
  line-height: 1.6;
}

.ability-ask {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  color: #303133;
  margin-bottom: 12px;
  width: 100%;
  box-sizing: border-box;
}

/* ⑤ 可靠性 */
.reliability {
  display: flex;
  gap: 16px;
}

.reliability-card {
  flex: 1;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 20px 12px;
  text-align: center;
}

.reliability-value {
  font-size: 32px;
  font-weight: 700;
  color: #409eff;
}

.reliability-label {
  font-size: 15px;
  font-weight: 600;
  margin-top: 6px;
}

.reliability-note {
  font-size: 13px;
  color: #909399;
  margin-top: 6px;
  line-height: 1.5;
}

.demo-entry {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px 18px;
}

.demo-entry-text {
  color: #606266;
  font-size: 14px;
  margin: 0;
}

/* ⑥ 技术架构 */
.layers {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.layer {
  display: flex;
  align-items: center;
  gap: 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 18px;
  background: #fff;
}

.layer-name {
  font-weight: 700;
  width: 110px;
  flex-shrink: 0;
}

.layer-note {
  color: #606266;
  font-size: 14px;
}

.sub-title {
  font-size: 17px;
  font-weight: 600;
  margin: 28px 0 12px;
}

.highlights {
  display: flex;
  gap: 16px;
}

.highlight-card {
  flex: 1;
  background: #ecf5ff;
  border-radius: 8px;
  padding: 16px;
}

.highlight-title {
  font-weight: 700;
  margin-bottom: 6px;
}

.highlight-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

/* ⑦ 从哪开始 */
.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 28px;
}

.versions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.version {
  flex: 1;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}

.version-v {
  font-weight: 700;
  font-size: 18px;
  color: #409eff;
}

.version-time {
  font-size: 12px;
  color: #909399;
  margin: 4px 0;
}

.version-label {
  font-size: 14px;
}

.version-arrow {
  color: #c0c4cc;
  font-size: 18px;
  flex-shrink: 0;
}
</style>
