import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { StatsResponse } from '@/lib/types'

export function useStats() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`stats:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading } = useSWR(
    swrKey,
    () => api.get<StatsResponse>('/stats').then(r => r.data),
    {
      refreshInterval: 1_000,
      revalidateOnFocus: true,
    }
  )
  return { stats: data ?? null, error, isLoading }
}
