import type { Metadata } from 'next';
import { Suspense } from 'react';
import './globals.css';
import TopNav from '@/components/TopNav/TopNav';

export const metadata: Metadata = {
  title: 'NOCKO MDM',
  description: 'Mobile Device Management Platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<div style={{ height: 'var(--nav-height)', background: '#23252e' }} />}>
          <TopNav />
        </Suspense>
        <main style={{ minHeight: 'calc(100vh - var(--nav-height))' }}>
          {children}
        </main>
      </body>
    </html>
  );
}
