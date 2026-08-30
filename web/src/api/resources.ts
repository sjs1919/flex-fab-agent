import axios from 'axios'

const http = axios.create({ baseURL: import.meta.env.BASE_URL, timeout: 15_000 })

export type ResourceCategory = 'machines' | 'customers' | 'orders' | 'inventory' | 'batches' | 'preprocess' | 'personnel'

export async function fetchResources(category: ResourceCategory): Promise<Record<string, unknown>[]> {
  const { data } = await http.get<{ items: Record<string, unknown>[] }>(`/resources/${category}`)
  // 兜底：响应缺 items 字段时返回空数组，避免上层 rows.length 崩溃（历史：后端字段名不一致教训）
  return data.items ?? []
}

export async function setPersonnelStatus(id: string, status: '上班' | '请假', token: string): Promise<{ ok: boolean; message: string }> {
  const { data } = await http.put(
    `/resources/personnel/${encodeURIComponent(id)}/status`,
    { status },
    { headers: { 'X-Admin-Token': token } },
  )
  return data
}
