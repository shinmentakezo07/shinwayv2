import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'

export interface ConfigEntry {
  value: string | number | boolean
  default: string | number | boolean
  type: 'str' | 'int' | 'float' | 'bool'
  overridden: boolean
}

export type RuntimeConfigSnapshot = Record<string, ConfigEntry>

export function useRuntimeConfig() {
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    setSwrKey(`config:${localStorage.getItem('admin_token') ?? ''}`)
  }, [])

  const { data, error, isLoading, mutate } = useSWR<RuntimeConfigSnapshot>(
    swrKey,
    () => api.get<RuntimeConfigSnapshot>('/config').then(r => r.data),
    { refreshInterval: 30_000 }
  )

  async function patchKey(key: string, value: string | number | boolean): Promise<void> {
    await api.patch(`/config/${key}`, { value })
    await mutate()
  }

  async function resetKey(key: string): Promise<void> {
    await api.delete(`/config/${key}`)
    await mutate()
  }

  return {
    config: data ?? {},
    isLoading,
    error,
    patchKey,
    resetKey,
    refresh: mutate,
  }
}
