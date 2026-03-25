import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'

export interface ManagedKey {
  key: string
  label: string
  created_at: number
  rpm_limit: number
  rps_limit: number
  token_limit_daily: number
  budget_usd: number
  allowed_models: string[]
  is_active: boolean
}

export interface CreateKeyPayload {
  label: string
  rpm_limit: number
  rps_limit: number
  token_limit_daily: number
  budget_usd: number
  allowed_models: string[]
}

export function useManagedKeys() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`managed-keys:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () => api.get<{ keys: ManagedKey[]; count: number }>('/keys').then(r => r.data),
    { revalidateOnFocus: true }
  )
  return {
    keys: data?.keys ?? [],
    count: data?.count ?? 0,
    error,
    isLoading,
    mutate,
  }
}
