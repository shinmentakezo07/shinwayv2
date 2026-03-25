---
paths:
  - "admin-ui/**/*.ts"
  - "admin-ui/**/*.tsx"
  - "admin-ui/**/*.js"
  - "admin-ui/**/*.jsx"
---
# Next.js / TypeScript Rules

> Stack: Next.js 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui, SWR, Axios.
> Theme: dark glassmorphism — `#090910` bg, `#00e5a0` accent.

## TypeScript

- TypeScript for all files — no `.js` in `admin-ui/`.
- Prefer `interface` over `type` for object shapes.
- Never use `any`. Use `unknown` and narrow it. Use `never` for exhaustive checks.
- Enable strict mode in `tsconfig.json`.
- Avoid enums; use `const` maps with `as const`.
- Use `satisfies` operator for type-validated literals.
- Explicit return types on all exported functions.

## Naming

- Directories: lowercase with dashes (`components/key-manager/`).
- Components: PascalCase (`CreateKeyModal.tsx`).
- Event handlers: prefix with `handle` (`handleSubmit`, `handleKeyDelete`).
- Boolean variables: prefix with auxiliary verb (`isLoading`, `hasError`, `canEdit`).
- Named exports for all components (no default exports).

## Component Architecture

- Server Components by default. Add `'use client'` only when needed for:
  - Browser APIs (`localStorage`, `window`)
  - Event listeners / interactive state
  - SWR hooks
- Wrap client components in `<Suspense fallback={...}>` at the boundary.
- Use dynamic imports (`next/dynamic`) for non-critical heavy components.
- Props interfaces co-located with the component file.
- Structure: exports → component → subcomponents → helpers → types.

## State & Data Fetching

- Use SWR for all client-side data fetching — no raw `useEffect` + `fetch`.
- Proxy all backend calls through `admin-ui/app/api/` route handlers.
- Route handlers forward to FastAPI backend using `x-admin-token` header.
- Use `useActionState` (React 19) not deprecated `useFormState`.
- Minimize `useState` — derive state from SWR data where possible.

## Styling

- Tailwind v4 utility classes only — no custom CSS files except global theme tokens.
- Mobile-first responsive design.
- Dark glassmorphism palette: bg `#090910`, surface `rgba(255,255,255,0.05)`, accent `#00e5a0`.
- Use `cn()` utility for conditional class merging.
- shadcn/ui components as base — extend via `className`, never modify component source.

## Performance

- Optimize images: WebP format, `next/image` with explicit `width`/`height`.
- Memoize expensive computations with `useMemo`; stable callbacks with `useCallback`.
- Avoid re-render cascades: keep state local, lift only when necessary.
- Minimize bundle: tree-shake imports (`import { X } from 'lib'` not `import lib from 'lib'`).

## Error Handling

- Use `error.tsx` for route-level error boundaries.
- All SWR hooks handle `error` state — never render stale UI silently.
- API route handlers return consistent `{ error: string }` on failure with proper HTTP status.
- Never expose internal error details or stack traces to the client.

## Code Quality

- Functions ≤ 50 lines. Files ≤ 400 lines.
- No magic numbers — extract to named constants.
- No nested ternaries.
- Early returns instead of deeply nested if/else.
- No commented-out code — delete it.
