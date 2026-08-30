import axios from 'axios'

const http = axios.create({ baseURL: import.meta.env.BASE_URL, timeout: 15_000 })

export interface ScheduleVersion {
  id: number
  created_at: string
  triggered_by: string
  status: string
  batch_count: number
}

export async function fetchVersions(): Promise<ScheduleVersion[]> {
  const { data } = await http.get<{ versions: ScheduleVersion[] }>('/schedule/versions')
  return data.versions
}

export async function approveSchedule(versionId: number, action: '通过' | '驳回', token: string): Promise<{ ok: boolean; message: string }> {
  const { data } = await http.post(
    '/schedule/approve',
    { version_id: versionId, action },
    { headers: { 'X-Admin-Token': token } },
  )
  return data
}
