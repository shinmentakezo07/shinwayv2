import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Wiwi Admin',
  description: 'Wiwi Proxy Admin Console',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
