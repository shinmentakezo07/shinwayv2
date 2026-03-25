import { NextRequest, NextResponse } from 'next/server'
import { PRIMARY } from '@/lib/instances'

// Model list is static/same across instances — read from primary
export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''
  try {
    const res = await fetch(`${PRIMARY.url}/v1/models`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'upstream_unreachable' }, { status: 502 })
  }
}
