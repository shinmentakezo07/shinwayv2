import { useState, useEffect } from 'react'
import useSWR from 'swr'
import api from '@/lib/api'
import type { PromptLogsResponse, PromptLogEntry } from '@/lib/types'

interface UsePromptLogsOptions {
  limit?: number
  offset?: number
  apiKey?: string
  provider?: string
  model?: string
  search?: string
}

export function usePromptLogs(opts: UsePromptLogsOptions = {}) {
  const { limit = 100, offset = 0, apiKey, provider, model, search } = opts
  const [swrKey, setSwrKey] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    params.set('offset', String(offset))
    if (apiKey)   params.set('api_key',  apiKey)
    if (provider) params.set('provider', provider)
    if (model)    params.set('model',    model)
    if (search)   params.set('search',   search)
    const token = localStorage.getItem('admin_token') ?? ''
    setSwrKey(`prompt-logs:${token}:${params.toString()}`)
  }, [limit, offset, apiKey, provider, model, search])

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () => api.get<PromptLogsResponse>(`/prompt-logs?${buildParams(opts)}`).then(r => r.data),
    {
      refreshInterval: 2_000,
      revalidateOnFocus: true,
    }
  )

  return {
    logs: (data?.logs ?? []) as PromptLogEntry[],
    total: data?.total ?? 0,
    count: data?.count ?? 0,
    error,
    isLoading,
    mutate,
  }
}

function buildParams(opts: UsePromptLogsOptions): string {
  const p = new URLSearchParams()
  p.set('limit',  String(opts.limit  ?? 100))
  p.set('offset', String(opts.offset ?? 0))
  if (opts.apiKey)   p.set('api_key',  opts.apiKey)
  if (opts.provider) p.set('provider', opts.provider)
  if (opts.model)    p.set('model',    opts.model)
  if (opts.search)   p.set('search',   opts.search)
  return p.toString()
}
