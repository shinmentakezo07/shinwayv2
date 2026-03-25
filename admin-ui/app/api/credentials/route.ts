import { NextRequest, NextResponse } from 'next/server'
import { fanout } from '@/lib/fanout'
import type { CredentialsResponse, CredentialInfo } from '@/lib/types'

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''

  const results = await fanout<CredentialsResponse>(async (base) => {
    const res = await fetch(`${base}/v1/internal/credentials`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return { data: await res.json(), status: res.status }
  })

  // Merge credential lists from all instances, re-index
  const allCreds: CredentialInfo[] = []
  let poolSize = 0

  for (const r of results) {
    if (!r.ok || !r.data) continue
    poolSize += r.data.pool_size
    for (const cred of r.data.credentials) {
      allCreds.push({ ...cred, index: allCreds.length })
    }
  }

  return NextResponse.json({ pool_size: poolSize, credentials: allCreds } satisfies CredentialsResponse)
}
