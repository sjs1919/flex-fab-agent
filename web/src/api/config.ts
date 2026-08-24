import axios from 'axios'

// 配置 API 客户端（M6 T6.8 F-2；GET 匿名，PUT 需 admin token）
const http = axios.create({ baseURL: '/', timeout: 10_000 })

export interface ConfigView {
  data_source: string
  sim_tick_seconds: number
  solver_timeout_override: number | null
  调试台: {
    case_collection_enabled: string
    sample_rate: string
    judge_enabled: string
  }
}

export async function fetchConfig(): Promise<ConfigView> {
  const { data } = await http.get<ConfigView>('/config')
  return data
}

export async function saveConfig(category: string, key: string, value: string, token: string): Promise<{ category: string; key: string; value: string }> {
  const { data } = await http.put('/config', { category, key, value }, { headers: { 'X-Admin-Token': token } })
  return data
}
