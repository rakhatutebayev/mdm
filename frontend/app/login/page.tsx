'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { Suspense } from 'react';

// Demo admin credentials — bypass backend for UI preview
const DEMO_EMAIL = 'admin@nocko.ae';
const DEMO_PASSWORD = 'Admin@MDM2024';
const DEMO_TOKEN = 'demo-jwt-token-nocko-mdm-admin';

export default function LoginPage() {
    const router = useRouter();
    const [tab, setTab] = useState<'login' | 'register'>('login');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [fullName, setFullName] = useState('');
    const [orgName, setOrgName] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [entraEnabled, setEntraEnabled] = useState(false);

    useEffect(() => {
        api.entraStatus().then((r) => setEntraEnabled(r.enabled)).catch(() => { });
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        // Demo admin login — works without the backend running
        if (tab === 'login' && email === DEMO_EMAIL && password === DEMO_PASSWORD) {
            localStorage.setItem('access_token', DEMO_TOKEN);
            localStorage.setItem('demo_user', JSON.stringify({
                id: 'demo-admin-id',
                email: DEMO_EMAIL,
                full_name: 'NOCKO Admin',
                role: 'admin',
                org_id: 'demo-org-id',
            }));
            router.push('/dashboard');
            return;
        }

        try {
            if (tab === 'login') {
                await api.login(email, password);
            } else {
                await api.register(email, password, fullName, orgName);
            }
            router.push('/dashboard');
        } catch (err: any) {
            setError(err.message || 'An error occurred');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="login-page">
            <div className="login-card">
                {/* Logo */}
                <div className="login-logo">
                    <div className="logo-icon" style={{ width: 44, height: 44, fontSize: '1.3rem' }}>N</div>
                    <div>
                        <div style={{ fontWeight: 700, fontSize: '1.1rem' }}>NOCKO MDM</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Device Management Platform</div>
                    </div>
                </div>

                {/* Demo credentials banner */}
                {tab === 'login' && (
                    <div style={{
                        background: 'linear-gradient(135deg, rgba(59,130,246,0.12), rgba(139,92,246,0.12))',
                        border: '1px solid rgba(59,130,246,0.3)',
                        borderRadius: 'var(--radius-sm)',
                        padding: '0.875rem 1rem',
                        marginBottom: '1.25rem',
                    }}>
                        <div style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--accent)', marginBottom: '0.5rem' }}>
                            🔐 Admin Credentials
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.25rem 0.75rem', fontSize: '0.82rem', alignItems: 'center' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Email:</span>
                            <span style={{ fontWeight: 600, fontFamily: 'monospace', color: 'var(--text-primary)' }}>admin@nocko.ae</span>
                            <span style={{ color: 'var(--text-muted)' }}>Password:</span>
                            <span style={{ fontWeight: 600, fontFamily: 'monospace', color: 'var(--text-primary)' }}>Admin@MDM2024</span>
                        </div>
                        <button
                            id="btn-demo-fill"
                            type="button"
                            onClick={() => { setEmail(DEMO_EMAIL); setPassword(DEMO_PASSWORD); }}
                            style={{
                                marginTop: '0.65rem',
                                width: '100%',
                                padding: '0.4rem',
                                background: 'rgba(59,130,246,0.15)',
                                border: '1px solid rgba(59,130,246,0.3)',
                                borderRadius: '6px',
                                color: 'var(--accent)',
                                fontSize: '0.78rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                            }}
                        >
                            ↓ Fill Credentials
                        </button>
                    </div>
                )}

                {/* Tab switcher */}
                <div style={{ display: 'flex', marginBottom: '1.5rem', background: 'var(--bg-base)', borderRadius: 'var(--radius-sm)', padding: '4px', gap: '4px' }}>
                    {(['login', 'register'] as const).map((t) => (
                        <button
                            key={t}
                            onClick={() => setTab(t)}
                            style={{
                                flex: 1,
                                padding: '0.5rem',
                                borderRadius: '6px',
                                border: 'none',
                                background: tab === t ? 'var(--bg-card)' : 'transparent',
                                color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
                                fontWeight: tab === t ? 600 : 400,
                                fontSize: '0.85rem',
                                transition: 'all 0.15s',
                            }}
                        >
                            {t === 'login' ? 'Sign In' : 'Create Account'}
                        </button>
                    ))}
                </div>

                {error && (
                    <div className="alert alert-warning" style={{ marginBottom: '1rem' }}>
                        ⚠️ {error}
                    </div>
                )}

                <form onSubmit={handleSubmit}>
                    {tab === 'register' && (
                        <>
                            <div className="form-group">
                                <label>Full Name</label>
                                <input
                                    id="input-fullname"
                                    type="text"
                                    value={fullName}
                                    onChange={(e) => setFullName(e.target.value)}
                                    placeholder="John Doe"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label>Organization Name</label>
                                <input
                                    id="input-orgname"
                                    type="text"
                                    value={orgName}
                                    onChange={(e) => setOrgName(e.target.value)}
                                    placeholder="NOCKO IT"
                                    required
                                />
                            </div>
                        </>
                    )}

                    <div className="form-group">
                        <label>Email</label>
                        <input
                            id="input-email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="admin@nocko.ae"
                            required
                        />
                    </div>

                    <div className="form-group">
                        <label>Password</label>
                        <input
                            id="input-password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••"
                            required
                        />
                    </div>

                    <button
                        id="btn-submit"
                        type="submit"
                        className="btn btn-primary"
                        style={{ width: '100%', justifyContent: 'center', padding: '0.75rem', marginTop: '0.5rem' }}
                        disabled={loading}
                    >
                        {loading ? '...' : tab === 'login' ? 'Sign In' : 'Create Account & Organization'}
                    </button>
                </form>

                {tab === 'login' && entraEnabled && (
                    <>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            margin: '1.25rem 0 1rem',
                        }}>
                            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>or</span>
                            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                        </div>
                        <a
                            id="btn-microsoft"
                            href="/api/v1/auth/microsoft"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.6rem',
                                width: '100%',
                                padding: '0.72rem',
                                background: 'var(--bg-card)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius-sm)',
                                color: 'var(--text-primary)',
                                fontSize: '0.875rem',
                                fontWeight: 600,
                                textDecoration: 'none',
                                transition: 'border-color 0.15s, background 0.15s',
                            }}
                            onMouseEnter={(e) => {
                                (e.currentTarget as HTMLAnchorElement).style.borderColor = '#0078d4';
                                (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(0,120,212,0.07)';
                            }}
                            onMouseLeave={(e) => {
                                (e.currentTarget as HTMLAnchorElement).style.borderColor = 'var(--border)';
                                (e.currentTarget as HTMLAnchorElement).style.background = 'var(--bg-card)';
                            }}
                        >
                            {/* Microsoft logo SVG */}
                            <svg width="18" height="18" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                                <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                                <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                                <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                                <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
                            </svg>
                            Sign in with Microsoft
                        </a>
                    </>
                )}
            </div>
        </div>
    );
}
