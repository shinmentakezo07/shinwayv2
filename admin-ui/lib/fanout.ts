// Fan-out helper — fires a fetch against every live instance in parallel.
// Reads from getInstances() so runtime overrides via /api/instances/override
// are reflected immediately without a server restart.

import { getInstances, type Instance } from './instances'

export interface InstanceResult<T> {
  instance: Instance
  ok: boolean
  data: T | null
  status: number
}

type FetchFn<T> = (baseUrl: string) => Promise<{ data: T; status: number }>

/** Call fetchFn against every live instance in parallel, settle all. */
export async function fanout<T>(fetchFn: FetchFn<T>): Promise<InstanceResult<T>[]> {
  const instances = getInstances()
  const results = await Promise.allSettled(
    instances.map(async (instance) => {
      const { data, status } = await fetchFn(instance.url)
      return { instance, ok: status >= 200 && status < 300, data, status }
    })
  )
  return results.map((r, i) =>
    r.status === 'fulfilled'
      ? r.value
      : { instance: instances[i], ok: false, data: null, status: 0 }
  )
}

/** Return the data from the first successful result, or null. */
export function firstOk<T>(results: InstanceResult<T>[]): T | null {
  return results.find(r => r.ok)?.data ?? null
}

/** Sum numeric fields across all successful results. */
export function sumFields<T extends Record<string, unknown>>(
  results: InstanceResult<T>[],
  fields: (keyof T)[]
): Partial<T> {
  const out: Partial<T> = {}
  for (const field of fields) {
    const total = results
      .filter(r => r.ok && r.data !== null)
      .reduce((acc, r) => acc + (Number((r.data as T)[field]) || 0), 0)
    ;(out as Record<string | symbol, unknown>)[field as string] = total
  }
  return out
}
