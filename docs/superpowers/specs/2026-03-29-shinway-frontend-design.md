# Shinway Public Frontend — Design Spec

**Date:** 2026-03-29
**Status:** Approved

## Overview

A standalone public-facing Next.js website for the Shinway AI proxy. Serves as marketing landing page, model explorer, interactive playground, and documentation hub. Separate from the existing `admin-ui` — lives in a new `frontend/` directory in the same repo.

## Goals

- Showcase Shinway to developers considering using the proxy
- Let visitors explore all available models with specs and capability badges
- Provide a fully interactive playground to test models before committing
- Offer getting-started docs and API reference

## Visual Style

Dark glassmorphism + developer-minimal hybrid:
- Background: `#090910` (same as admin-ui)
- Primary accent: `#00e5a0` (green, same as admin-ui)
- Secondary accent: `#6366f1` (indigo)
- Frosted glass cards with subtle border glow
- Monospace font for code and model IDs
- Clean grid layouts, minimal decoration
- Font: Inter (body) + JetBrains Mono (code/IDs)

## Tech Stack

- **Framework:** Next.js 15 App Router
- **Language:** TypeScript (strict)
- **Styling:** Tailwind CSS v4
- **Components:** shadcn/ui (Radix primitives)
- **Animation:** Framer Motion
- **Data fetching:** SWR
- **Icons:** Lucide React
- **Forms:** React Hook Form + Zod
- **Toast:** Sonner
- **Charts:** Recharts (for stats)

## Site Structure

| Route | Page | Description |
|---|---|---|
| `/` | Landing | Hero, features, stats, model preview strip, CTA |
| `/models` | Model Explorer | Browse/filter/search all models |
| `/playground` | Playground | Full interactive chat interface |
| `/docs` | Docs | Getting started, API reference |

**Navigation:** Sticky top navbar — Logo, Models, Playground, Docs, "Get API Key" button
**Footer:** Links, GitHub, status dot

---

## Page Designs

### Landing Page (`/`)

**Hero section:**
- Large headline: "The AI Gateway for Every Model"
- Subheadline: "OpenAI & Anthropic-compatible API. One endpoint. Every model."
- CTAs: "Get Started" (→ /docs) + "Explore Models" (→ /models)
- Animated streaming text demo (simulates a streaming chat completion)

**Stats bar:**
- Model count (live from `/v1/models` or static fallback)
- Requests served (static or live from `/internal/health`)
- Average latency (static or live)

**Features section (3 cards):**
1. Drop-in compatible — OpenAI & Anthropic SDK, zero code changes
2. Multi-model — one key, every model
3. Full streaming — SSE, tool calls, reasoning tokens

**How it works (3 steps):**
1. Get your API key
2. Point your SDK at Shinway
3. Call any model

**Model preview strip:** Scrolling horizontal strip of 6-8 model cards, "See all →" links to /models

**CTA banner:** "Ready to start?" + "Get API Key" button

---

### Model Explorer (`/models`)

**Layout:** Sidebar filters + main card grid

**Sidebar filters:**
- Fuzzy search input
- Provider filter (Anthropic, OpenAI, Google, Meta, etc.)
- Context window filter (8k, 32k, 128k+)
- Capabilities checkboxes (vision, tool calls, reasoning)

**Model card:**
- Model name + provider badge
- Model ID with one-click copy
- Context window size
- Capability badges
- "Try in Playground →" button

**Model detail modal:**
- Full specs
- SDK code snippet pointing at Shinway
- Copy model ID

**Data source:** Live fetch from `/v1/models` + static fallback. Refresh button.

---

### Playground (`/playground`)

**Layout:** Two-panel — left config, right chat

**Left config panel:**
- Model selector (searchable dropdown, grouped by provider)
- System prompt textarea (collapsible)
- Temperature slider (0–2)
- Max tokens slider (256–128k, capped per model)
- Top-p slider
- Token counter (live estimate)
- Clear conversation button

**Right chat panel:**
- Message thread (user right, assistant left)
- Streaming output token by token
- Tool call blocks (collapsible, shows name + args + result)
- Reasoning token block (collapsible `<thinking>` section)
- Copy button per message
- Bottom input bar (textarea + send + Ctrl+Enter shortcut)

**Auth:** API key input stored in `localStorage`. Required to send.

**Save/Load:** Export conversation as JSON. Import from file.

---

### Docs (`/docs`)

**Sections:**
- Getting started (install, set base URL, first call)
- Authentication (API keys, header format)
- Models (how to list, how to select)
- Streaming (SSE format, tool calls)
- API reference (endpoints, request/response schemas)

**Layout:** Left sidebar TOC + main content

---

## Data / API Integration

| Data | Source | Fallback |
|---|---|---|
| Model list | `GET /v1/models` | Static JSON in `lib/models.ts` |
| Health/stats | `GET /internal/health` | Static numbers |
| Chat completions | `POST /v1/chat/completions` | — |
| Token count | `POST /v1/messages/count_tokens` | Client-side estimate |

All API calls use the user's API key from `localStorage` via an `Authorization: Bearer <key>` header.

## Key Constraints

- No server-side secrets — all API calls are client → proxy directly
- API key lives in `localStorage` only, never sent to this frontend's server
- Static export compatible (no server-side data fetching required for landing/docs)
- Mobile responsive (min 320px)
- WCAG AA accessibility minimum
