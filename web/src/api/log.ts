import axios from 'axios'

const http = axios.create({ baseURL: import.meta.env.BASE_URL, timeout: 10_000 })

export type OperationCategory = 'auto' | 'simulator' | 'manual' | 'debug'

export interface OperationLogItem {
  id: number
  category: OperationCategory
  action: string
  status: 'ok' | 'fail'
  summary: string
  detail_json: string | null
  sim_time: string | null
  real_time: string
  trace_id: string | null
  relate_id: string | null
}

export interface LogQuery {
  category?: string
  start?: string
  end?: string
  keyword?: string
  page: number
  page_size: number
}

export interface LogPage {
  total: number
  page: number
  page_size: number
  items: OperationLogItem[]
}

export async function fetchLogs(q: LogQuery): Promise<LogPage> {
  const { data } = await http.get<LogPage>('/logs', { params: q })
  return data
}
