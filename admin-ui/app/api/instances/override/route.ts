// POST /api/instances/override
// Body: { urls: string[] }
// Updates the live in-memory instance list used by all fanout calls.
// Resets to env defaults on server restart — clients persist to localStorage and re-apply on mount.

import { NextRequest, NextResponse } from 'next/server'
import { setInstances, parseInstanceUrls, DEFAULT_INSTANCES } from '@/lib/instances'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { urls?: unknown }
    const urls = body.urls

    if (!Array.isArray(urls)) {
      return NextResponse.json({ error: 'urls must be an array' }, { status: 400 })
    }

    const cleaned = (urls as unknown[]).filter((u): u is string => typeof u === 'string' && u.trim().length > 0)

    if (cleaned.length === 0) {
      // Reset to env defaults
      setInstances(DEFAULT_INSTANCES)
      return NextResponse.json({ ok: true, reset: true, instances: DEFAULT_INSTANCES })
    }

    const instances = parseInstanceUrls(cleaned.join(','))
    setInstances(instances)
    return NextResponse.json({ ok: true, instances })
  } catch {
    return NextResponse.json({ error: 'invalid_body' }, { status: 400 })
  }
}

// GET returns the current live list and the env defaults for the UI to compare
export async function GET() {
  const { getInstances, DEFAULT_INSTANCES } = await import('@/lib/instances')
  return NextResponse.json({
    instances: getInstances(),
    defaults: DEFAULT_INSTANCES,
  })
}
