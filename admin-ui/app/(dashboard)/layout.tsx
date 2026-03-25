'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { SWRConfig } from 'swr'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { Toaster } from 'sonner'

const pageTitles: Record<string, string> = {
  '/dashboard': 'Overview',
  '/keys': 'API Keys',
  '/credentials': 'Credentials',
  '/logs': 'Request Logs',
  '/cache': 'Cache',
  '/settings': 'Settings',
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem('admin_token')
    if (!token) router.replace('/login')
  }, [])

  // Cmd+K / Ctrl+K to open palette
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      setPaletteOpen(prev => !prev)
    }
    if (e.key === 'Escape') {
      setPaletteOpen(false)
    }
  }, [])

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const title = pageTitles[pathname] ?? 'Admin'

  return (
    <SWRConfig value={{ revalidateOnFocus: true }}>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        [cmdk-group-heading] {
          padding: 6px 16px 3px;
          font-size: 9px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.16em;
          color: rgba(255,255,255,0.28);
          font-family: var(--mono);
        }
        [cmdk-item] {
          cursor: pointer;
          border-radius: 9px;
          margin: 1px 6px;
          outline: none;
          transition: background 0.1s;
        }
        [cmdk-item][aria-selected="true"] {
          background: rgba(255,255,255,0.07);
        }
        [cmdk-item][aria-selected="true"] [data-palette-row] {
          color: rgba(255,255,255,0.92);
        }
        [cmdk-list] {
          scrollbar-width: thin;
          scrollbar-color: rgba(255,255,255,0.08) transparent;
        }
        [cmdk-input] {
          caret-color: rgba(255,255,255,0.9);
        }
        [cmdk-input]::placeholder {
          color: rgba(255,255,255,0.25);
        }
      `}</style>
      <div className="shell">
        <Sidebar onOpenPalette={() => setPaletteOpen(true)} />
        <div className="main-col">
          <Topbar title={title} onOpenPalette={() => setPaletteOpen(true)} />
          <main
            className="page"
            style={{ animation: 'fadeIn 0.3s ease' }}
          >
            {children}
          </main>
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            backgroundColor: '#111111',
            border: '1px solid rgba(255,255,255,0.1)',
            color: '#e0e0e0',
            fontFamily: 'IBM Plex Sans, sans-serif',
          },
        }}
      />
    </SWRConfig>
  )
}
