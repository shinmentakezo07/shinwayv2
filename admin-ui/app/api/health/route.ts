import { NextRequest, NextResponse } from 'next/server'
import { getInstances } from '@/lib/instances'
import type { HealthResponse } from '@/lib/types'

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''
  const instances = getInstances()

  // If a token was supplied, validate it against the first reachable instance.
  if (token) {
    const authResults = await Promise.allSettled(
      instances.map(inst =>
        fetch(`${inst.url}/v1/models`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: 'no-store',
          signal: AbortSignal.timeout(4000),
        })
      )
    )

    // Find first settled-fulfilled result that has a real Response value
    const firstAuth = authResults.find(
      (r): r is PromiseFulfilledResult<Response> => r.status === 'fulfilled' && r.value instanceof Response
    )

    if (!firstAuth) {
      // Every instance failed to respond
      return NextResponse.json({ status: 'not_ready', reason: 'upstream_unreachable' } satisfies HealthResponse, { status: 502 })
    }

    if (firstAuth.value.status === 401) {
      return NextResponse.json({ ok: false, reason: 'invalid_token' } satisfies HealthResponse, { status: 401 })
    }
  }

  // Check /health/ready on all instances
  const healthResults = await Promise.allSettled(
    instances.map(inst =>
      fetch(`${inst.url}/health/ready`, {
        cache: 'no-store',
        signal: AbortSignal.timeout(4000),
      }).then(r => r.json() as Promise<HealthResponse>)
    )
  )

  const anyReady = healthResults.some(
    (r): r is PromiseFulfilledResult<HealthResponse> =>
      r.status === 'fulfilled' && r.value?.status === 'ready'
  )

  if (anyReady) {
    return NextResponse.json({ status: 'ready' } satisfies HealthResponse)
  }

  return NextResponse.json(
    { status: 'not_ready', reason: 'no_instances_ready' } satisfies HealthResponse,
    { status: 503 }
  )
}
