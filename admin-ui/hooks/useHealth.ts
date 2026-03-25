import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { HealthResponse } from '@/lib/types'

export function useHealth() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`health:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading } = useSWR(
    swrKey,
    () => api.get<HealthResponse>('/health').then(r => r.data),
    { refreshInterval: 10_000, revalidateOnFocus: true }
  )
  return {
    health: data ?? null,
    isReady: data?.status === 'ready',
    error,
    isLoading,
  }
}
