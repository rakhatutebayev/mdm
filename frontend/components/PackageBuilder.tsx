'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Org { id: string; name: string; domain?: string; }

interface ExeStatus {
  available: boolean;
  size_mb?: number;
  uploaded_at?: string;
  version?: string;
}

interface PackageResult {
  token_id: string;
  token: string;
  package_name: string;
  download_url: string;
  oneliner: string;
  expires_at?: string;
  max_uses: number;
}

interface Props {
  org: Org;
  onClose: () => void;
}

const STEPS = ['Configure', 'Build', 'Deploy'];

export default function PackageBuilder({ org, onClose }: Props) {
  const [step, setStep] = useState(0);
  const [exeStatus, setExeStatus] = useState<ExeStatus | null>(null);
  const [form, setForm] = useState({
    package_name: `${org.name} Agent`,
    max_uses: 0,
    expires_in_days: 0,
    package_type: 'zip' as 'zip' | 'ps1',
  });
  const [building, setBuilding] = useState(false);
  const [result, setResult] = useState<PackageResult | null>(null);
  const [zipDownloadUrl, setZipDownloadUrl] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');

  useEffect(() => {
    api.get<ExeStatus>('/agent-packages/exe-status').then(setExeStatus).catch(() => {});
  }, []);

  const handleBuild = async () => {
    setBuilding(true);
    setError('');
    try {
      if (form.package_type === 'zip') {
        // Build ZIP package via agent-packages endpoint
        const res = await fetch('/api/v1/agent-packages/build', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          },
          body: JSON.stringify({
            org_id: org.id,
            package_name: form.package_name,
            max_uses: form.max_uses,
            expires_in_days: form.expires_in_days,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Build failed');
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        setZipDownloadUrl(url);
        setStep(2);
      } else {
        // PS1 script via original enrollment endpoint
        const data = await api.post('/enrollment/package/windows', {
          org_id: org.id,
          package_name: form.package_name,
          max_uses: form.max_uses,
          expires_in_days: form.expires_in_days,
        });
        setResult(data);
        setStep(2);
      }
    } catch (e: any) {
      setError(e.message || 'Failed to build package');
    } finally {
      setBuilding(false);
    }
  };

  const copy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(''), 2000);
  };

  const safeOrgName = org.name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');

  // ── Styles ─────────────────────────────────────────────────────────────────

  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 1000,
    background: 'rgba(0,0,0,0.75)',
    backdropFilter: 'blur(6px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  };
  const modal: React.CSSProperties = {
    background: 'var(--card-bg)', border: '1px solid var(--border)',
    borderRadius: 20, padding: '2rem',
    width: 580, maxWidth: '95vw', maxHeight: '92vh', overflowY: 'auto',
  };
  const codeBox: React.CSSProperties = {
    background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
    padding: '12px 14px', fontFamily: 'monospace', fontSize: '0.78rem',
    wordBreak: 'break-all', color: 'var(--text-muted)', position: 'relative',
    lineHeight: 1.6,
  };
  const badge = (color: string) => ({
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '3px 10px', borderRadius: 99, fontSize: '0.7rem', fontWeight: 700,
    background: `${color}20`, color,
  });
  const copyBtn: React.CSSProperties = {
    position: 'absolute', top: 8, right: 8,
    background: 'var(--border)', border: 'none', borderRadius: 4,
    padding: '3px 8px', cursor: 'pointer', fontSize: '0.7rem', color: 'var(--text)',
  };

  return (
    <div style={overlay}>
      <div style={modal}>

        {/* ── Header ── */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700 }}>📦 Package Builder</h2>
            <p style={{ margin: '4px 0 0', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Create a self-contained Windows agent installer for <strong>{org.name}</strong>
            </p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '1.3rem', lineHeight: 1 }}>✕</button>
        </div>

        {/* ── Step indicator ── */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '1.75rem', gap: 4 }}>
          {STEPS.map((s, i) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.75rem', fontWeight: 700,
                background: i < step ? '#10b981' : i === step ? 'var(--accent)' : 'var(--border)',
                color: i <= step ? '#fff' : 'var(--text-muted)',
                transition: 'all 0.3s',
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ marginLeft: 6, fontSize: '0.8rem', fontWeight: i === step ? 700 : 400, color: i <= step ? 'var(--text)' : 'var(--text-muted)', flex: 1 }}>
                {s}
              </span>
              {i < STEPS.length - 1 && (
                <div style={{ width: 20, height: 1, background: i < step ? '#10b981' : 'var(--border)', flexShrink: 0 }} />
              )}
            </div>
          ))}
        </div>

        {error && (
          <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444', borderRadius: 8, padding: '10px 14px', marginBottom: '1rem', color: '#ef4444', fontSize: '0.85rem' }}>
            ⚠️ {error}
          </div>
        )}

        {/* ══════════ STEP 0: Configure ══════════ */}
        {step === 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

            {/* Org info */}
            <div style={{ background: 'rgba(37,99,235,0.08)', border: '1px solid rgba(37,99,235,0.2)', borderRadius: 10, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>ORGANIZATION</div>
                <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{org.name}</div>
                {org.domain && <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>{org.domain}</div>}
              </div>
              <span style={badge('#2563eb')}>🏢 Target</span>
            </div>

            {/* Package type selector */}
            <div>
              <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: 8 }}>Package Type</label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {[
                  {
                    id: 'zip', icon: '🗜️', label: 'Full Package',
                    desc: exeStatus?.available
                      ? `ZIP with .exe + config + installer (${exeStatus.size_mb} MB)`
                      : 'ZIP with config + scripts (EXE not available yet)',
                    recommended: exeStatus?.available,
                  },
                  {
                    id: 'ps1', icon: '📜', label: 'Script Only',
                    desc: 'Pre-configured PowerShell script (.ps1)',
                    recommended: !exeStatus?.available,
                  },
                ].map(t => (
                  <div
                    key={t.id}
                    id={`pkg-type-${t.id}`}
                    onClick={() => setForm(p => ({ ...p, package_type: t.id as any }))}
                    style={{
                      border: `2px solid ${form.package_type === t.id ? 'var(--accent)' : 'var(--border)'}`,
                      borderRadius: 10, padding: '12px', cursor: 'pointer',
                      background: form.package_type === t.id ? 'rgba(37,99,235,0.06)' : 'var(--bg)',
                      transition: 'all 0.2s',
                    }}
                  >
                    <div style={{ fontSize: '1.4rem', marginBottom: 4 }}>{t.icon}</div>
                    <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 2 }}>
                      {t.label}
                      {t.recommended && <span style={{ ...badge('#10b981'), marginLeft: 6, fontSize: '0.65rem' }}>★ BEST</span>}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>{t.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* EXE status warning */}
            {form.package_type === 'zip' && !exeStatus?.available && (
              <div style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid #f59e0b', borderRadius: 8, padding: '10px 14px', fontSize: '0.8rem', color: '#f59e0b' }}>
                ⚠️ No agent .exe uploaded yet. The ZIP will include config + scripts but not the installer.<br />
                <span style={{ color: 'var(--text-muted)' }}>
                  To add the installer: build NOCKO-Agent-Setup.exe on Windows (PyInstaller + Inno Setup),
                  then upload via <strong>Settings → Agent Binary</strong>.
                </span>
              </div>
            )}

            {/* Package name */}
            <div>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Package Name</label>
              <input className="input" id="pkg-name" style={{ width: '100%' }}
                value={form.package_name}
                onChange={e => setForm(p => ({ ...p, package_name: e.target.value }))}
              />
            </div>

            {/* Options row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Max Installs</label>
                <select className="input" id="pkg-max-uses" style={{ width: '100%' }}
                  value={form.max_uses}
                  onChange={e => setForm(p => ({ ...p, max_uses: parseInt(e.target.value) }))}>
                  <option value={0}>Unlimited ♾️</option>
                  <option value={1}>1 device</option>
                  <option value={10}>10 devices</option>
                  <option value={50}>50 devices</option>
                  <option value={100}>100 devices</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Expires In</label>
                <select className="input" id="pkg-expires" style={{ width: '100%' }}
                  value={form.expires_in_days}
                  onChange={e => setForm(p => ({ ...p, expires_in_days: parseInt(e.target.value) }))}>
                  <option value={0}>Never 🔒</option>
                  <option value={7}>7 days</option>
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={365}>1 year</option>
                </select>
              </div>
            </div>

            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', background: 'var(--bg)', borderRadius: 8, padding: '10px 14px', lineHeight: 1.6 }}>
              ℹ️ All settings are <strong>baked into the package</strong> — just run it on any Windows machine and it will automatically enroll under <strong>{org.name}</strong>.
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" id="btn-next-configure" onClick={() => setStep(1)}>
                Next → Configure
              </button>
            </div>
          </div>
        )}

        {/* ══════════ STEP 1: Build ══════════ */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Summary */}
            <div style={{ background: 'var(--bg)', borderRadius: 10, border: '1px solid var(--border)', padding: '14px 16px' }}>
              <div style={{ fontWeight: 700, marginBottom: 10 }}>📋 Package Summary</div>
              {[
                ['Organization', org.name],
                ['Package name', form.package_name],
                ['Type', form.package_type === 'zip' ? '🗜️ Full Package (ZIP)' : '📜 Script (PS1)'],
                ['Max installs', form.max_uses === 0 ? 'Unlimited' : `${form.max_uses} devices`],
                ['Expires', form.expires_in_days === 0 ? 'Never' : `In ${form.expires_in_days} days`],
                ['Server', 'https://mdm.it-uae.com'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ fontWeight: 600 }}>{v}</span>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, paddingTop: 4 }}>
              <button className="btn btn-ghost" onClick={() => setStep(0)}>← Back</button>
              <button className="btn btn-primary" id="btn-build-package" onClick={handleBuild} disabled={building}
                style={{ minWidth: 160 }}>
                {building ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                    Building...
                  </span>
                ) : '⚙️ Build Package'}
              </button>
            </div>
          </div>
        )}

        {/* ══════════ STEP 2: Deploy ══════════ */}
        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Success */}
            <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid #10b981', borderRadius: 12, padding: '20px', textAlign: 'center' }}>
              <div style={{ fontSize: '2.5rem', marginBottom: 6 }}>✅</div>
              <div style={{ fontWeight: 800, fontSize: '1.05rem', color: '#10b981' }}>Package Ready!</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>
                {form.package_type === 'zip' ? `${form.package_name}.zip` : `nocko-agent-${safeOrgName}.ps1`}
              </div>
            </div>

            {/* Download button */}
            {form.package_type === 'zip' && zipDownloadUrl ? (
              <a
                href={zipDownloadUrl}
                download={`nocko-agent-${safeOrgName}.zip`}
                id="btn-download-zip"
                style={{
                  display: 'block', textAlign: 'center', background: 'var(--accent)',
                  color: '#fff', borderRadius: 10, padding: '14px 20px',
                  textDecoration: 'none', fontWeight: 700, fontSize: '0.95rem',
                  letterSpacing: 0.3,
                }}
              >
                ⬇️ Download {form.package_name}.zip
              </a>
            ) : result ? (
              <a
                href={result.download_url}
                download
                id="btn-download-ps1"
                style={{
                  display: 'block', textAlign: 'center', background: 'var(--accent)',
                  color: '#fff', borderRadius: 10, padding: '14px 20px',
                  textDecoration: 'none', fontWeight: 700, fontSize: '0.95rem',
                }}
              >
                ⬇️ Download nocko-agent-{safeOrgName}.ps1
              </a>
            ) : null}

            {/* Install instructions */}
            {form.package_type === 'zip' ? (
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.82rem', marginBottom: 8 }}>📂 What's inside the ZIP:</div>
                <div style={{ fontSize: '0.78rem', background: 'var(--bg)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
                  {[
                    ['NOCKO-Agent-Setup.exe', exeStatus?.available ? '✅ Included' : '❌ Not available', exeStatus?.available ? '#10b981' : '#ef4444'],
                    ['nocko-config.json', '✅ Pre-configured for ' + org.name, '#10b981'],
                    ['install-silent.bat', '✅ Double-click installer', '#10b981'],
                    ['install.ps1', '✅ PowerShell installer', '#10b981'],
                    ['README.txt', '✅ Instructions', '#10b981'],
                  ].map(([file, status, color]) => (
                    <div key={file} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
                      <code style={{ color: 'var(--text)' }}>{file}</code>
                      <span style={{ color, fontWeight: 600, fontSize: '0.72rem' }}>{status}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Usage instructions tabs */}
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.82rem', marginBottom: 8 }}>🚀 How to Install:</div>
              <div style={{ ...codeBox, marginBottom: 8 }}>
                <div style={{ color: '#94a3b8', marginBottom: 4, fontSize: '0.72rem' }}>Option 1 — Double-click (no PowerShell)</div>
                <div>Right-click <code>install-silent.bat</code> → Run as Administrator</div>
              </div>
              <div style={codeBox}>
                <div style={{ color: '#94a3b8', marginBottom: 4, fontSize: '0.72rem' }}>Option 2 — Remote one-liner</div>
                <div>{result?.oneliner || `irm 'https://mdm.it-uae.com/api/v1/enrollment/package/windows/.../download' | iex`}</div>
                {result?.oneliner && (
                  <button style={copyBtn} onClick={() => copy(result.oneliner, 'liner')}>
                    {copied === 'liner' ? '✓' : 'Copy'}
                  </button>
                )}
              </div>
            </div>

            {/* SCCM/GPO tip */}
            <div style={{ background: 'rgba(37,99,235,0.06)', border: '1px solid rgba(37,99,235,0.2)', borderRadius: 8, padding: '10px 14px', fontSize: '0.78rem' }}>
              🏢 <strong>Group Policy / SCCM deployment:</strong><br />
              <code style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                NOCKO-Agent-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
              </code><br />
              Copy <code>nocko-config.json</code> to <code>%ProgramData%\NOCKO-Agent\config.json</code>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn btn-ghost" onClick={() => { setStep(0); setResult(null); setZipDownloadUrl(''); }}>← New Package</button>
              <button className="btn btn-primary" id="btn-done" onClick={onClose}>Done ✓</button>
            </div>
          </div>
        )}

      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
