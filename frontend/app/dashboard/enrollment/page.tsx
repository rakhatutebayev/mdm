'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

const PLATFORM_OPTIONS = [
    { value: 'any',     label: 'Any Platform' },
    { value: 'ios',     label: '🍎 iOS / iPadOS' },
    { value: 'android', label: '🤖 Android' },
    { value: 'macos',   label: '💻 macOS' },
    { value: 'windows', label: '🪟 Windows' },
];

type Tab = 'general' | 'windows';

export default function EnrollmentPage() {
    const [tab, setTab]         = useState<Tab>('general');
    const [tokens, setTokens]   = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [form, setForm]       = useState({ platform: 'any', is_byod: false, assigned_user_email: '', max_uses: 1, expires_in_days: 7 });
    const [qrToken, setQrToken] = useState<string | null>(null);

    // Windows-specific state
    const [winTokenId, setWinTokenId]   = useState('');
    const [winScript, setWinScript]     = useState<any>(null);
    const [winLoading, setWinLoading]   = useState(false);
    const [entraConfig, setEntraConfig] = useState<any>(null);
    const [entraLoading, setEntraLoading] = useState(false);
    const [copied, setCopied]           = useState('');

    const load = async () => {
        setLoading(true);
        try { setTokens(await api.listTokens()); }
        finally { setLoading(false); }
    };

    useEffect(() => { load(); }, []);

    // Pre-select first windows token when switching to Windows tab
    useEffect(() => {
        if (tab === 'windows') {
            const winToken = tokens.find(t => (t.platform === 'windows' || t.platform === 'any') && t.is_valid);
            if (winToken) setWinTokenId(winToken.id);
            loadEntraConfig();
        }
    }, [tab, tokens]);

    const loadEntraConfig = async () => {
        setEntraLoading(true);
        try { setEntraConfig(await api.entraConfig()); }
        catch { setEntraConfig({ enabled: false }); }
        finally { setEntraLoading(false); }
    };

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        setCreating(true);
        try {
            const token = await api.createToken(form);
            await load();
            setQrToken(token.token);
        } finally {
            setCreating(false);
        }
    };

    const revoke = async (id: string) => {
        await api.revokeToken(id);
        await load();
        if (qrToken) setQrToken(null);
    };

    const handleGenerateScript = async () => {
        if (!winTokenId) return;
        setWinLoading(true);
        try {
            const data = await api.windowsScript(winTokenId);
            setWinScript(data);
        } catch (e: any) {
            alert(e.message);
        } finally {
            setWinLoading(false);
        }
    };

    const copyText = (text: string, key: string) => {
        navigator.clipboard?.writeText(text);
        setCopied(key);
        setTimeout(() => setCopied(''), 2000);
    };

    const CopyBtn = ({ text, id }: { text: string; id: string }) => (
        <button
            id={`btn-copy-${id}`}
            className="btn btn-ghost btn-sm"
            onClick={() => copyText(text, id)}
            style={{ flexShrink: 0 }}
        >
            {copied === id ? '✅ Copied' : '📋 Copy'}
        </button>
    );

    return (
        <>
            <div className="page-header">
                <div>
                    <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>Device Enrollment</h1>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Generate enrollment links and QR codes for corporate & BYOD devices
                    </div>
                </div>
            </div>

            <div className="page-content">
                {/* Tabs */}
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border)', paddingBottom: '0' }}>
                    {([
                        { key: 'general', label: '🔗 General Enrollment' },
                        { key: 'windows', label: '🪟 Windows 10 / 11' },
                    ] as { key: Tab; label: string }[]).map(t => (
                        <button
                            key={t.key}
                            id={`tab-${t.key}`}
                            onClick={() => setTab(t.key)}
                            style={{
                                padding: '0.6rem 1.2rem',
                                background: 'none',
                                border: 'none',
                                borderBottom: tab === t.key ? '2px solid var(--primary)' : '2px solid transparent',
                                color: tab === t.key ? 'var(--text)' : 'var(--text-muted)',
                                fontWeight: tab === t.key ? 700 : 400,
                                fontSize: '0.875rem',
                                cursor: 'pointer',
                                marginBottom: '-1px',
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* ── GENERAL TAB ── */}
                {tab === 'general' && (
                    <>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '2rem' }}>
                            {/* Create token form */}
                            <div className="card">
                                <div className="card-title">Generate Enrollment Link</div>
                                <form onSubmit={handleCreate}>
                                    <div className="form-group">
                                        <label>Platform</label>
                                        <select id="select-platform" value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
                                            {PLATFORM_OPTIONS.map((o) => (
                                                <option key={o.value} value={o.value}>{o.label}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label>Assigned User Email (optional)</label>
                                        <input id="input-user-email" type="email" value={form.assigned_user_email}
                                            onChange={(e) => setForm({ ...form, assigned_user_email: e.target.value })}
                                            placeholder="employee@company.com" />
                                    </div>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                        <div className="form-group">
                                            <label>Max Uses</label>
                                            <input id="input-max-uses" type="number" min={1} max={100} value={form.max_uses}
                                                onChange={(e) => setForm({ ...form, max_uses: parseInt(e.target.value) })} />
                                        </div>
                                        <div className="form-group">
                                            <label>Expires in (days)</label>
                                            <input id="input-expires" type="number" min={1} max={30} value={form.expires_in_days}
                                                onChange={(e) => setForm({ ...form, expires_in_days: parseInt(e.target.value) })} />
                                        </div>
                                    </div>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textTransform: 'none', fontSize: '0.875rem', fontWeight: 500, marginBottom: '1.25rem', cursor: 'pointer' }}>
                                        <input id="checkbox-byod" type="checkbox" checked={form.is_byod}
                                            onChange={(e) => setForm({ ...form, is_byod: e.target.checked })} />
                                        BYOD Enrollment (install Work Profile only)
                                    </label>
                                    <button id="btn-generate-token" type="submit" className="btn btn-primary"
                                        style={{ width: '100%', justifyContent: 'center' }} disabled={creating}>
                                        {creating ? 'Generating…' : '🔗 Generate Enrollment Link'}
                                    </button>
                                </form>
                            </div>

                            {/* QR / instructions */}
                            <div className="card">
                                {qrToken ? (
                                    <>
                                        <div className="card-title">QR Code — Scan to Enroll</div>
                                        <div style={{ textAlign: 'center', margin: '1rem 0' }}>
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={api.qrCodeUrl(qrToken)} alt="Enrollment QR Code"
                                                style={{ width: 180, height: 180, background: 'white', padding: 8, borderRadius: 8, margin: '0 auto' }} />
                                        </div>
                                        <div style={{ background: 'var(--bg-base)', borderRadius: 'var(--radius-sm)', padding: '0.75rem', fontFamily: 'monospace', fontSize: '0.75rem', wordBreak: 'break-all', marginBottom: '1rem' }}>
                                            {`${typeof window !== 'undefined' ? window.location.origin : ''}/enroll/${qrToken}`}
                                        </div>
                                        <button className="btn btn-secondary" style={{ width: '100%', justifyContent: 'center' }}
                                            onClick={() => navigator.clipboard?.writeText(`${window.location.origin}/enroll/${qrToken}`)}>
                                            📋 Copy Enrollment URL
                                        </button>
                                    </>
                                ) : (
                                    <>
                                        <div className="card-title">Enrollment Instructions</div>
                                        <div className="enrollment-steps">
                                            <div className="enrollment-step"><div>Generate a link above. Choose <strong>BYOD</strong> for personal devices.</div></div>
                                            <div className="enrollment-step"><div>Share the <strong>QR code</strong> or <strong>URL</strong> via email or message.</div></div>
                                            <div className="enrollment-step"><div>On <strong>iOS/macOS</strong>: Open in Safari → Install profile → Trust in Settings.</div></div>
                                            <div className="enrollment-step"><div>On <strong>Android</strong>: Open the link → Install Work Profile or complete Enterprise enrollment.</div></div>
                                            <div className="enrollment-step"><div>Device will appear in the <strong>Devices</strong> list once enrolled.</div></div>
                                        </div>
                                        <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                                            💡 Apple enrollment requires a trusted HTTPS server with valid APNs certificates configured in <code>.env</code>.
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Token list */}
                        <TokenTable tokens={tokens} loading={loading} onQr={setQrToken} onRevoke={revoke} onRefresh={load} />
                    </>
                )}

                {/* ── WINDOWS TAB ── */}
                {tab === 'windows' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

                        {/* Path selector cards */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>

                            {/* PATH A — Standalone */}
                            <div className="card" style={{ borderTop: '3px solid var(--primary)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                    <span style={{ fontSize: '1.5rem' }}>⚙️</span>
                                    <div>
                                        <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>Path A — Standalone Agent</div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>No Azure AD required · PowerShell scheduled task</div>
                                    </div>
                                </div>
                                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                                    Install the NOCKO MDM PowerShell agent on any Windows 10/11 PC. Works without Entra or domain join. Runs as SYSTEM, checks in every 15 min.
                                </p>

                                <div className="form-group">
                                    <label>Enrollment Token</label>
                                    <select id="select-win-token" value={winTokenId} onChange={e => setWinTokenId(e.target.value)}>
                                        <option value="">— Select token —</option>
                                        {tokens.filter(t => t.is_valid && (t.platform === 'windows' || t.platform === 'any')).map(t => (
                                            <option key={t.id} value={t.id}>
                                                {t.token.slice(0, 16)}… · Uses: {t.use_count}/{t.max_uses}
                                            </option>
                                        ))}
                                    </select>
                                    {tokens.filter(t => t.is_valid && (t.platform === 'windows' || t.platform === 'any')).length === 0 && (
                                        <div style={{ fontSize: '0.78rem', color: 'var(--warning)', marginTop: '0.4rem' }}>
                                            ⚠️ No active Windows/Any tokens. Generate one in the General tab first.
                                        </div>
                                    )}
                                </div>

                                <button id="btn-gen-win-script" className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }}
                                    onClick={handleGenerateScript} disabled={!winTokenId || winLoading}>
                                    {winLoading ? 'Generating…' : '⚡ Generate One-Liner Install Command'}
                                </button>

                                {winScript && (
                                    <div style={{ marginTop: '1.25rem' }}>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                                            Run this in PowerShell <strong>as Administrator</strong> on the Windows device:
                                        </div>
                                        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 8, padding: '0.75rem 1rem', fontFamily: 'monospace', fontSize: '0.72rem', wordBreak: 'break-all', position: 'relative' }}>
                                            {winScript.one_liner}
                                            <div style={{ marginTop: '0.5rem' }}>
                                                <CopyBtn text={winScript.one_liner} id="one-liner" />
                                            </div>
                                        </div>
                                        <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                            <a
                                                id="btn-download-bat"
                                                href={winScript.script_url.replace('/download', '/download-bat')}
                                                download
                                                className="btn btn-primary btn-sm"
                                                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
                                            >
                                                ⬇️ Download .bat Installer
                                            </a>
                                            <a id="btn-download-ps1" href={winScript.script_url} download
                                                className="btn btn-ghost btn-sm">
                                                📄 Download .ps1 Script
                                            </a>
                                            <CopyBtn text={winScript.one_liner} id="one-liner" />
                                        </div>
                                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem', lineHeight: 1.5 }}>
                                            💡 <strong>.bat installer</strong> = double-click as Admin, no PowerShell policy issues.<br />
                                            💡 <strong>.ps1 script</strong> = run manually with{' '}
                                            <code style={{ background: 'var(--bg-hover)', padding: '1px 4px', borderRadius: 3 }}>
                                                powershell -ExecutionPolicy Bypass -File .\nocko-agent.ps1 -Install
                                            </code>
                                        </div>
                                    </div>
                                )}

                                {/* Manual steps */}
                                <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.6rem' }}>Manual Installation Steps</div>
                                    {[
                                        '1. Generate an enrollment token with Platform = Windows in the General tab',
                                        '2. Download the .ps1 script or use the one-liner above',
                                        '3. On the Windows PC, open PowerShell as Administrator',
                                        '4. Run the one-liner (or: .\\nocko-mdm-agent.ps1 -Install)',
                                        '5. Device appears in the Devices list within 60 seconds',
                                    ].map(s => (
                                        <div key={s} style={{ fontSize: '0.78rem', color: 'var(--text-muted)', padding: '0.2rem 0' }}>{s}</div>
                                    ))}
                                </div>
                            </div>

                            {/* PATH B — Entra / OMA-DM */}
                            <div className="card" style={{ borderTop: '3px solid #0078d4' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                    <span style={{ fontSize: '1.5rem' }}>🔷</span>
                                    <div>
                                        <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>Path B — Entra ID (OMA-DM)</div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Native Windows MDM via Azure AD join</div>
                                    </div>
                                </div>
                                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                                    Uses the built-in Windows MDM client. The device enrolls via <strong>Settings → Accounts → Access work or school</strong> and connects to NOCKO MDM as the MDM provider through Microsoft Entra (Azure AD).
                                </p>

                                {entraLoading ? (
                                    <div className="loading-spinner" />
                                ) : entraConfig ? (
                                    <>
                                        <div style={{ marginBottom: '1rem' }}>
                                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.3rem' }}>Entra Integration Status</div>
                                            <span className={`badge ${entraConfig.enabled ? 'enrolled' : 'unenrolled'}`}>
                                                <span className="badge-dot" />
                                                {entraConfig.enabled ? 'Configured' : 'Not Configured'}
                                            </span>
                                            {!entraConfig.enabled && (
                                                <div style={{ fontSize: '0.75rem', color: 'var(--warning)', marginTop: '0.4rem' }}>
                                                    Set ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_TENANT_ID in .env to enable.
                                                </div>
                                            )}
                                        </div>

                                        {/* URLs */}
                                        {[
                                            { label: 'MDM Discovery URL', key: 'discovery_url', val: entraConfig.discovery_url },
                                            { label: 'MDM Enrollment URL', key: 'enrollment_url', val: entraConfig.enrollment_url },
                                            { label: 'Terms of Service URL', key: 'tos_url',        val: entraConfig.tos_url },
                                        ].map(row => (
                                            <div key={row.key} style={{ marginBottom: '0.75rem' }}>
                                                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>{row.label}</div>
                                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                    <code style={{ flex: 1, fontSize: '0.72rem', background: 'var(--bg-base)', padding: '0.4rem 0.6rem', borderRadius: 4, wordBreak: 'break-all' }}>
                                                        {row.val}
                                                    </code>
                                                    <CopyBtn text={row.val} id={row.key} />
                                                </div>
                                            </div>
                                        ))}
                                    </>
                                ) : null}

                                {/* Setup steps */}
                                <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.6rem' }}>Azure AD / Entra Setup (Admin → Portal)</div>
                                    {[
                                        '1. In Azure Portal → Entra ID → Mobility (MDM & MAM)',
                                        '2. Click "Add application" → choose "Other"',
                                        '3. Set MDM Discovery URL to the value above',
                                        '4. Set MDM Terms of Use URL to the ToS URL above',
                                        '5. Set MDM Enrollment URL to the enrollment URL above',
                                        '6. Set ENTRA_TENANT_ID, CLIENT_ID, CLIENT_SECRET in .env',
                                        '7. Users: Settings → Accounts → "Access work or school" → Connect',
                                    ].map(s => (
                                        <div key={s} style={{ fontSize: '0.78rem', color: 'var(--text-muted)', padding: '0.2rem 0' }}>{s}</div>
                                    ))}
                                </div>

                                <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.6rem' }}>When Entra Enrollment Completes</div>
                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                                        Windows will call the OMA-DM Discovery → Policy → Enrollment endpoints automatically. The device is registered in the NOCKO MDM database and appears in the Devices list with <strong>Entra Joined: Yes</strong>.
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Comparison table */}
                        <div className="card">
                            <div className="card-title">Enrollment Path Comparison</div>
                            <div className="table-wrapper" style={{ margin: 0 }}>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Feature</th>
                                            <th>⚙️ Path A — Standalone Agent</th>
                                            <th>🔷 Path B — Entra ID OMA-DM</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {[
                                            ['Requires Azure AD / Entra ID', '❌ No', '✅ Yes'],
                                            ['Azure AD domain join', '❌ Not required', '✅ Required (or Hybrid)'],
                                            ['Windows version', 'Windows 10 / 11 any edition', 'Windows 10 Pro/Ent, Windows 11'],
                                            ['Enrollment method', 'PowerShell script (Admin)', 'Settings → Work Account'],
                                            ['Communicates via', 'REST API (agent polling)', 'OMA-DM (SOAP/XML)'],
                                            ['Zero-touch capable', '⚙️ Via Intune/GPO deployment', '✅ Via Autopilot or bulk enrollment'],
                                            ['Commands supported', 'Lock, Reboot, App install, Script, Wallpaper, Inventory', 'Lock, Reboot, Policy, Profile'],
                                            ['Inventory collection', '✅ Full hardware (RAM, disk, CPU, monitors)', '✅ Via check-in after enrollment'],
                                            ['Best for', 'Workgroup PCs, mixed environments, no AD', 'Corporate fleet with Azure AD Premium'],
                                        ].map(([feat, a, b]) => (
                                            <tr key={String(feat)}>
                                                <td style={{ fontWeight: 500, fontSize: '0.83rem' }}>{feat}</td>
                                                <td style={{ fontSize: '0.82rem' }}>{a}</td>
                                                <td style={{ fontSize: '0.82rem' }}>{b}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Token list (windows tokens) */}
                        <TokenTable tokens={tokens} loading={loading} onQr={setQrToken} onRevoke={revoke} onRefresh={load} filterPlatform="windows" />
                    </div>
                )}
            </div>
        </>
    );
}

// ── Reusable token table ────────────────────────────────────────────────────
function TokenTable({
    tokens, loading, onQr, onRevoke, onRefresh, filterPlatform,
}: {
    tokens: any[]; loading: boolean;
    onQr: (t: string) => void; onRevoke: (id: string) => void;
    onRefresh: () => void; filterPlatform?: string;
}) {
    const filtered = filterPlatform
        ? tokens.filter(t => t.platform === filterPlatform || t.platform === 'any')
        : tokens;

    return (
        <div className="table-wrapper">
            <div className="table-header">
                <h3 style={{ margin: 0, fontSize: '0.95rem' }}>
                    {filterPlatform ? 'Windows Enrollment Tokens' : 'Active Enrollment Tokens'}
                </h3>
                <button className="btn btn-ghost btn-sm" onClick={onRefresh}>↺ Refresh</button>
            </div>
            {loading ? (
                <div className="loading-spinner" />
            ) : filtered.length === 0 ? (
                <div className="empty-state" style={{ padding: '2rem' }}>
                    <p>No enrollment tokens yet.</p>
                </div>
            ) : (
                <table>
                    <thead>
                        <tr>
                            <th>Token</th>
                            <th>Platform</th>
                            <th>Type</th>
                            <th>Assigned To</th>
                            <th>Uses</th>
                            <th>Expires</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((t) => (
                            <tr key={t.id}>
                                <td style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{t.token.slice(0, 12)}…</td>
                                <td>{t.platform.toUpperCase()}</td>
                                <td>{t.is_byod ? <span className="badge pending">BYOD</span> : 'Managed'}</td>
                                <td style={{ fontSize: '0.8rem' }}>{t.assigned_user_email || '—'}</td>
                                <td>{t.use_count} / {t.max_uses}</td>
                                <td style={{ fontSize: '0.8rem' }}>{new Date(t.expires_at).toLocaleDateString()}</td>
                                <td>
                                    <span className={`badge ${t.is_valid ? 'enrolled' : 'unenrolled'}`}>
                                        <span className="badge-dot" />
                                        {t.is_valid ? 'Active' : 'Expired'}
                                    </span>
                                </td>
                                <td>
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        <button id={`btn-qr-${t.token}`} className="btn btn-ghost btn-sm" onClick={() => onQr(t.token)}>QR</button>
                                        <button id={`btn-revoke-${t.id}`} className="btn btn-danger btn-sm" onClick={() => onRevoke(t.id)}>Revoke</button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
}
