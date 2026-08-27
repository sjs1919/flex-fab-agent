import axios from 'axios'

const http = axios.create({ baseURL: '/', timeout: 15_000 })

export type ResourceCategory = 'machines' | 'customers' | 'orders' | 'inventory' | 'batches' | 'preprocess' | 'personnel'

export async function fetchResources(category: ResourceCategory): Promise<Record<string, unknown>[]> {
  const { data } = await http.get<{ items: Record<string, unknown>[] }>(`/resources/${category}`)
  return data.items
}

export async function setPersonnelStatus(id: string, status: '上班' | '请假', token: string): Promise<{ ok: boolean; message: string }> {
  const { data } = await http.put(
    `/resources/personnel/${encodeURIComponent(id)}/status`,
    { status },
    { headers: { 'X-Admin-Token': token } },
  )
  return data
}
