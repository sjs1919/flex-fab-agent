<template>
  <div style="padding: 24px; max-width: 1200px; margin: 0 auto">
    <h1>排产看板</h1>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 16px" />

    <el-row :gutter="16">
      <!-- KPI 历史折线（与 query_kpi 同源） -->
      <el-col :span="24">
        <el-card shadow="never">
          <template #header>KPI 走势（准交率 / 延期金额，按 sim tick 快照）</template>
          <div v-loading="loading">
            <el-empty v-if="!loading && !kpiData.length" description="暂无 KPI 快照（模拟器 tick 后生成）" />
            <div v-show="kpiData.length" ref="kpiChartEl" style="width: 100%; height: 320px" />
          </div>
        </el-card>
      </el-col>

      <!-- 成本分模型 -->
      <el-col :span="12" style="margin-top: 16px">
        <el-card shadow="never">
          <template #header>LLM 成本分模型（¥）</template>
          <div v-loading="loading">
            <el-empty v-if="!loading && !costModels.length" description="暂无成本记录（/ask 调用后生成）" />
            <div v-show="costModels.length" ref="costChartEl" style="width: 100%; height: 300px" />
          </div>
        </el-card>
      </el-col>

      <!-- Trace 摘要表 -->
      <el-col :span="12" style="margin-top: 16px">
        <el-card shadow="never">
          <template #header>Trace 摘要（最近 {{ traceData.length }} 条）</template>
          <el-table v-loading="loading" :data="traceData" size="small" max-height="300" empty-text="暂无 trace 记录">
            <el-table-column prop="created_at" label="时间" width="160" />
            <el-table-column prop="trace_id" label="trace_id" width="130" show-overflow-tooltip />
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ row.total_ms.toFixed(1) }} ms</template>
            </el-table-column>
            <el-table-column prop="span_count" label="span" width="60" />
            <el-table-column label="类型分布">
              <template #default="{ row }">
                <el-tag v-for="(n, k) in row.by_kind" :key="k" size="small" style="margin-right: 4px">{{ k }}×{{ n }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchCosts, fetchKpiHistory, fetchTraces, type TraceRecord } from '../api/dashboard'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const loading = ref(false)
const error = ref('')
const kpiData = ref<Awaited<ReturnType<typeof fetchKpiHistory>>>([])
const costModels = ref<{ model: string; cost: number; calls: number }[]>([])
const traceData = ref<TraceRecord[]>([])

const kpiChartEl = ref<HTMLDivElement>()
const costChartEl = ref<HTMLDivElement>()
let kpiChart: echarts.ECharts | null = null
let costChart: echarts.ECharts | null = null

function renderKpiChart() {
  if (!kpiChartEl.value || !kpiData.value.length) return
  kpiChart = kpiChart ?? echarts.init(kpiChartEl.value)
  const times = kpiData.value.map((k) => k.sim_time.slice(5, 16))
  kpiChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['准交率 %', '延期金额 ¥'] },
    grid: { left: 50, right: 60, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: times },
    yAxis: [
      { type: 'value', name: '准交率 %', max: 100 },
      { type: 'value', name: '延期金额 ¥' },
    ],
    series: [
      {
        name: '准交率 %', type: 'line', smooth: true, data: kpiData.value.map((k) =>
          k.metrics.on_time_rate == null ? null : Math.round(k.metrics.on_time_rate * 1000) / 10),
        connectNulls: true,
      },
      { name: '延期金额 ¥', type: 'line', smooth: true, yAxisIndex: 1, data: kpiData.value.map((k) => k.metrics.delay_total ?? 0) },
    ],
  })
}

function renderCostChart() {
  if (!costChartEl.value || !costModels.value.length) return
  costChart = costChart ?? echarts.init(costChartEl.value)
  costChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 60 },
    xAxis: { type: 'category', data: costModels.value.map((c) => c.model), axisLabel: { rotate: 20 } },
    yAxis: { type: 'value', name: '¥' },
    series: [{ name: '费用 ¥', type: 'bar', data: costModels.value.map((c) => c.cost) }],
  })
}

function handleResize() {
  kpiChart?.resize()
  costChart?.resize()
}

onMounted(async () => {
  loading.value = true
  try {
    const [kpi, cost, traces] = await Promise.all([fetchKpiHistory(), fetchCosts(), fetchTraces()])
    kpiData.value = kpi
    costModels.value = Object.entries(cost.by_model)
      .map(([model, v]) => ({ model, cost: v.cost, calls: v.calls }))
      .sort((a, b) => b.cost - a.cost)
    traceData.value = traces
    // 等 v-show 渲染完成再 init，否则在 display:none 的容器上 echarts 得到 0 尺寸
    await nextTick()
    renderKpiChart()
    renderCostChart()
    window.addEventListener('resize', handleResize)
  } catch (e) {
    error.value = `看板数据加载失败：${e instanceof Error ? e.message : String(e)}（请确认 API :8000 已启动）`
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  kpiChart?.dispose()
  costChart?.dispose()
})
</script>
