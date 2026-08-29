import axios from 'axios'

// 调试台 API 客户端（M6 T6.7 G5；开发走 vite proxy，生产同源/反代）
// judge/rerun/label 写端点为 admin（R-7），token 从 localStorage 传入 X-Admin-Token 头
// 120s：语义缓存首启冷加载 embedding（~40s）+ 主备回落串行耗时，30s 会误报超时
const http = axios.create({ baseURL: '/', timeout: 120_000 })

export interface SpanItem {
  name: string
  ms: number | null
  attrs: Record<string, unknown>
  parent: string | null
}

export interface TraceSummary {
  total_ms: number
  span_count: number
  by_kind: Record<string, number>
  spans: SpanItem[]
}

export interface AskResponse {
  answer: string
  tool_results: Array<Record<string, unknown>>
  thread_id: string | null
  trace_id: string
  trace: TraceSummary
}

export interface CaseRecord {
  trace_id: string
  created_at: string
  query: string
  answer: string
  type: string
  good: boolean | null
  tools: string[]
  judge?: Record<string, unknown>
  rerun?: { trace_id: string; answer: string }
}

export interface DebugStats {
  total: number
  by_type: Record<string, number>
  good_count: number
  bad_count: number
  bad_to_good_rate: number | null
}

export interface JudgeResult {
  answer_relevancy?: number
  judged_answer?: string
  [k: string]: unknown
}

export async function askTrace(query: string): Promise<AskResponse> {
  const { data } = await http.post<AskResponse>('/ask', { query })
  return data
}

export async function fetchCases(type?: string, good?: string, limit = 200): Promise<CaseRecord[]> {
  const params: Record<string, string | number> = { limit }
  if (type) params.type = type
  if (good) params.good = good
  const { data } = await http.get<{ items: CaseRecord[] }>('/debug/cases', { params })
  return data.items
}

export async function fetchTrace(traceId: string): Promise<{ trace: { total_ms: number; span_count: number; by_kind: Record<string, number>; spans: SpanItem[] }; case: CaseRecord | null }> {
  const { data } = await http.get(`/debug/trace/${encodeURIComponent(traceId)}`)
  return data
}

export async function rerunCase(traceId: string, token: string): Promise<{ trace_id: string; new_trace_id: string; answer: string }> {
  const { data } = await http.post(`/debug/rerun/${encodeURIComponent(traceId)}`, {}, { headers: { 'X-Admin-Token': token } })
  return data
}

export async function judgeCase(traceId: string, token: string): Promise<{ trace_id: string; judge: JudgeResult }> {
  const { data } = await http.post(`/debug/judge/${encodeURIComponent(traceId)}`, {}, { headers: { 'X-Admin-Token': token } })
  return data
}

export async function labelCase(traceId: string, good: boolean, token: string): Promise<{ trace_id: string; good: boolean }> {
  const { data } = await http.put(`/debug/cases/${encodeURIComponent(traceId)}/label`, { good }, { headers: { 'X-Admin-Token': token } })
  return data
}

export async function fetchStats(): Promise<DebugStats> {
  const { data } = await http.get<DebugStats>('/debug/stats')
  return data
}

export async function fetchAdminToken(): Promise<{ token: string; role: string; ttl_hours: number }> {
  const { data } = await http.get('/debug/admin-token')
  return data
}
