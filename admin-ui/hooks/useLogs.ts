import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { LogsResponse } from '@/lib/types'

export function useLogs() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    // Set key after hydration so SWR reads the correct token
    setSwrKey(`logs:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading } = useSWR(
    swrKey,
    () => api.get<LogsResponse>('/logs?limit=500').then(r => r.data),
    {
      refreshInterval: 1_000,
      revalidateOnFocus: true,
    }
  )
  return {
    logs: data?.logs ?? [],
    count: data?.count ?? 0,
    error,
    isLoading,
  }
}
