import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { InstancesResponse } from '@/app/api/instances/route'

export function useInstances() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`instances:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading } = useSWR(
    swrKey,
    () => api.get<InstancesResponse>('/instances').then(r => r.data),
    { refreshInterval: 10_000, revalidateOnFocus: true }
  )
  return {
    instances: data?.instances ?? [],
    count: data?.count ?? 0,
    healthy: data?.healthy ?? 0,
    error,
    isLoading,
  }
}
