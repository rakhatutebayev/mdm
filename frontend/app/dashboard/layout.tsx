'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Sidebar from '@/components/Sidebar';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
    const router = useRouter();
    const pathname = usePathname();
    const [ready, setReady] = useState(false);
    const [checking, setChecking] = useState(true);

    useEffect(() => {
        // Run auth check on client side only (localStorage is client-only)
        const token = localStorage.getItem('access_token');

        if (!token) {
            router.replace('/login');
            return;
        }

        // Verify token is actually valid by calling /auth/me
        fetch('/api/v1/auth/me', {
            headers: { Authorization: `Bearer ${token}` },
        })
            .then((res) => {
                if (res.status === 401 || res.status === 403) {
                    localStorage.removeItem('access_token');
                    router.replace('/login');
                } else {
                    setReady(true);
                }
            })
            .catch(() => {
                // Network error — still allow access (offline mode)
                // Token exists, trust it
                setReady(true);
            })
            .finally(() => setChecking(false));
    }, [pathname]);

    if (checking) {
        return (
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: '100vh', background: 'var(--bg)',
            }}>
                <div style={{ textAlign: 'center' }}>
                    <div className="loading-spinner" style={{ margin: '0 auto 12px' }} />
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Verifying session…</div>
                </div>
            </div>
        );
    }

    if (!ready) return null;

    return (
        <div className="app-layout">
            <Sidebar />
            <main className="main-content">
                {children}
            </main>
        </div>
    );
}
