import axios from 'axios'

// 看板只读 API 客户端（M5b T5b.7 端点；开发走 vite proxy，生产同源/反代）
const http = axios.create({ baseURL: '/', timeout: 10_000 })

export interface KpiSnapshot {
  id: number
  sim_time: string
  metrics: {
    generated_at?: string
    on_time?: number
    sample?: number
    on_time_rate?: number | null
    delay_total?: number
    cabin_utilization?: number
    batch_count?: number
    done_parts?: number
    scrap?: number
    yield_rate?: number | null
    preprocess?: { utilization?: number; bottleneck?: string; [k: string]: unknown }
    [k: string]: unknown
  }
}

export interface CostRecord {
  id: number
  trace_id: string
  created_at: string
  total_cost: number
  total_tokens: number
  total_calls: number
  by_provider: Record<string, { calls: number; tokens: number; cost: number }>
  by_model: Record<string, { calls: number; tokens: number; cost: number }>
}

export interface TraceRecord {
  id: number
  trace_id: string
  created_at: string
  total_ms: number
  span_count: number
  by_kind: Record<string, number>
}

export async function fetchKpiHistory(limit = 500): Promise<KpiSnapshot[]> {
  const { data } = await http.get<{ items: KpiSnapshot[] }>('/dashboard/kpi-history', { params: { limit } })
  return data.items
}

export async function fetchCosts(limit = 500): Promise<{ items: CostRecord[]; by_model: Record<string, { calls: number; tokens: number; cost: number }> }> {
  const { data } = await http.get('/dashboard/costs', { params: { limit } })
  return data
}

export async function fetchTraces(limit = 200): Promise<TraceRecord[]> {
  const { data } = await http.get<{ items: TraceRecord[] }>('/dashboard/traces', { params: { limit } })
  return data.items
}
