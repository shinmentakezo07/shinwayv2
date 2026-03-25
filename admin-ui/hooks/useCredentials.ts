import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { CredentialsResponse } from '@/lib/types'

export function useCredentials() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`credentials:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () => api.get<CredentialsResponse>('/credentials').then(r => r.data),
    { refreshInterval: 15_000, revalidateOnFocus: true }
  )
  return {
    credentials: data?.credentials ?? [],
    poolSize: data?.pool_size ?? 0,
    error,
    isLoading,
    mutate,
  }
}
