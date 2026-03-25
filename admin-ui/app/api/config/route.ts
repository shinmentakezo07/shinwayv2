import { NextRequest, NextResponse } from 'next/server'
import { PRIMARY } from '@/lib/instances'

// Config is instance-specific; reads/writes go to primary
function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function GET(req: NextRequest) {
  const res = await fetch(`${PRIMARY.url}/v1/internal/config`, {
    headers: { Authorization: `Bearer ${token(req)}` },
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
