import { NextRequest, NextResponse } from 'next/server'
import { getInstances } from '@/lib/instances'

export interface InstanceStatus {
  url: string
  label: string
  healthy: boolean
  latency_ms: number | null
}

export interface InstancesResponse {
  count: number
  healthy: number
  instances: InstanceStatus[]
}

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''
  const live = getInstances()

  const checks = await Promise.allSettled(
    live.map(async (inst) => {
      const t0 = Date.now()
      const res = await fetch(`${inst.url}/health/ready`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: 'no-store',
        signal: AbortSignal.timeout(4000),
      })
      return {
        url: inst.url,
        label: inst.label,
        healthy: res.ok,
        latency_ms: Date.now() - t0,
      } satisfies InstanceStatus
    })
  )

  const instances: InstanceStatus[] = checks.map((r, i) =>
    r.status === 'fulfilled'
      ? r.value
      : { url: live[i].url, label: live[i].label, healthy: false, latency_ms: null }
  )

  const healthy = instances.filter(s => s.healthy).length

  return NextResponse.json({
    count: instances.length,
    healthy,
    instances,
  } satisfies InstancesResponse)
}
