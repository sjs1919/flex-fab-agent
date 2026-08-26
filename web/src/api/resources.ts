import axios from 'axios'

const http = axios.create({ baseURL: '/', timeout: 15_000 })

export type ResourceCategory = 'machines' | 'customers' | 'orders' | 'inventory' | 'batches' | 'preprocess'

export async function fetchResources(category: ResourceCategory): Promise<Record<string, unknown>[]> {
  const { data } = await http.get<{ items: Record<string, unknown>[] }>(`/resources/${category}`)
  return data.items
}
