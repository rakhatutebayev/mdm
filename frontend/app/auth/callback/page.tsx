'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

function CallbackContent() {
    const router = useRouter();
    const params = useSearchParams();

    useEffect(() => {
        const access_token = params.get('access_token');
        const refresh_token = params.get('refresh_token');

        if (access_token && refresh_token) {
            localStorage.setItem('access_token', access_token);
            localStorage.setItem('refresh_token', refresh_token);
            router.replace('/dashboard');
        } else {
            router.replace('/login?error=microsoft_auth_failed');
        }
    }, [params, router]);

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '100vh',
            flexDirection: 'column',
            gap: '1rem',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
        }}>
            <div style={{
                width: 40,
                height: 40,
                border: '3px solid var(--border)',
                borderTop: '3px solid var(--accent)',
                borderRadius: '50%',
                animation: 'spin 0.8s linear infinite',
            }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
                Completing Microsoft sign-in...
            </div>
        </div>
    );
}

export default function AuthCallbackPage() {
    return (
        <Suspense fallback={null}>
            <CallbackContent />
        </Suspense>
    );
}
