'use client';
export const dynamic = 'force-dynamic';
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { getEnrollmentToken, regenerateToken as apiRegenerateToken, getCustomers } from '@/lib/api';
import styles from './page.module.css';

const INSTALL_MODES = ['Silent', 'Interactive'] as const;
const ARCH_OPTIONS = ['x64 (64-bit)', 'x86 (32-bit)', 'Both'] as const;
const PACKAGE_FORMATS = ['ZIP (Scripts + Agent)', 'MSI Installer', 'EXE Installer'] as const;

export default function DeploymentPackagePage() {
  const searchParams = useSearchParams();
  const customerId = searchParams.get('customer') || 'default';
  const [customerName, setCustomerName] = useState(customerId);

  // Load customer name from API
  useEffect(() => {
    getCustomers()
      .then((list) => {
        const match = list.find((c) => c.slug === customerId || c.id === customerId);
        if (match) setCustomerName(match.name);
      })
      .catch(() => {/* backend not available yet */});
  }, [customerId]);

  const [form, setForm] = useState({
    serverUrl: 'https://mdm.it-uae.com',
    enrollmentToken: '',
    agentName: 'NOCKO MDM Agent',
    installMode: 'Silent' as (typeof INSTALL_MODES)[number],
    arch: 'x64 (64-bit)' as (typeof ARCH_OPTIONS)[number],
    format: 'ZIP (Scripts + Agent)' as (typeof PACKAGE_FORMATS)[number],
    scheduleTask: true,
    autoStart: true,
    installPath: 'C:\\Program Files\\NOCKO MDM\\Agent',
    logPath: 'C:\\ProgramData\\NOCKO MDM\\logs',
  });

  // Fetch token from API for the active customer
  const fetchToken = useCallback(async () => {
    try {
      const data = await getEnrollmentToken(customerId);
      setForm((f) => ({ ...f, enrollmentToken: data.token }));
    } catch {
      // backend unavailable — token stays empty
    }
  }, [customerId]);

  useEffect(() => { fetchToken(); }, [fetchToken]);


  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);
  const [copied, setCopied] = useState(false);

  const set = (key: string, val: unknown) =>
    setForm((f) => ({ ...f, [key]: val }));

  // Map UI label → API format value
  const formatToAPI = (label: string): string => {
    if (label.startsWith('ZIP')) return 'zip';
    if (label.startsWith('MSI')) return 'msi';
    if (label.startsWith('EXE')) return 'exe';
    return 'zip';
  };

  const archToAPI = (label: string): string => {
    if (label.startsWith('x86')) return 'x86';
    return 'x64';
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      const res = await fetch('/api/mdm/packages/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_id:  customerId,
          format:       formatToAPI(form.format),
          arch:         archToAPI(form.arch),
          server_url:   form.serverUrl || undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Package generation failed');
      }
      // Trigger browser download
      const blob = await res.blob();
      const cd   = res.headers.get('Content-Disposition') || '';
      const name = cd.match(/filename="([^"]+)"/)?.[1] ?? 'nocko-mdm-agent.zip';
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = name; a.click();
      URL.revokeObjectURL(url);
      setGenerated(true);
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleCopyToken = () => {
    navigator.clipboard.writeText(form.enrollmentToken).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const regenerateToken = async () => {
    try {
      const data = await apiRegenerateToken(customerId);
      set('enrollmentToken', data.token);
    } catch {
      // fallback: generate locally
      set('enrollmentToken', 'enroll-' + Math.random().toString(36).slice(2, 10).toUpperCase());
    }
    setGenerated(false);
  };

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Deployment Package</h1>
          <p className={styles.pageSubtitle}>
            Configure and generate a Windows MDM agent installation package for distribution to client machines.
          </p>
        </div>
      </div>

      <div className={styles.layout}>
        {/* ─── Left: Form ─── */}
        <div className={styles.formCard}>
          {/* Section: Connection */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>🔗</span> Connection
            </h2>

            <div className={styles.formRow}>
              <label className={styles.label}>MDM Server URL</label>
              <input
                className={styles.input}
                type="text"
                value={form.serverUrl}
                onChange={(e) => set('serverUrl', e.target.value)}
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Enrollment Token</label>
              <div className={styles.tokenRow}>
                <input
                  className={styles.input}
                  type="text"
                  value={form.enrollmentToken}
                  readOnly
                />
                <button className={styles.iconActionBtn} onClick={handleCopyToken} title="Copy token">
                  {copied ? (
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="#16a34a"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
                  ) : (
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
                  )}
                </button>
                <button className={styles.iconActionBtn} onClick={regenerateToken} title="Regenerate token">
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M17.65 6.35A7.96 7.96 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                </button>
              </div>
            </div>
          </div>

          {/* Section: Package */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>📦</span> Package Configuration
            </h2>
            <div className={styles.formRow}>
              <label className={styles.label}>Agent Display Name</label>
              <input className={styles.input} type="text" value={form.agentName} onChange={(e) => set('agentName', e.target.value)} />
            </div>
            <div className={styles.formGrid}>
              <div className={styles.formRow}>
                <label className={styles.label}>Install Mode</label>
                <select className={styles.select} value={form.installMode} onChange={(e) => set('installMode', e.target.value)}>
                  {INSTALL_MODES.map((m) => <option key={m}>{m}</option>)}
                </select>
              </div>
              <div className={styles.formRow}>
                <label className={styles.label}>Architecture</label>
                <select className={styles.select} value={form.arch} onChange={(e) => set('arch', e.target.value)}>
                  {ARCH_OPTIONS.map((a) => <option key={a}>{a}</option>)}
                </select>
              </div>
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Package Format</label>
              <div className={styles.radioGroup}>
                {PACKAGE_FORMATS.map((f) => (
                  <label key={f} className={`${styles.radioLabel} ${form.format === f ? styles.radioLabelActive : ''}`}>
                    <input type="radio" name="format" value={f} checked={form.format === f} onChange={() => set('format', f)} className={styles.radioInput}/>
                    {f}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Section: Install Paths */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>📁</span> Installation Paths
            </h2>
            <div className={styles.formRow}>
              <label className={styles.label}>Install Directory</label>
              <input className={styles.input} type="text" value={form.installPath} onChange={(e) => set('installPath', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Log Directory</label>
              <input className={styles.input} type="text" value={form.logPath} onChange={(e) => set('logPath', e.target.value)} />
            </div>
          </div>

          {/* Section: Options */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>⚙️</span> Options
            </h2>
            <label className={styles.checkRow}>
              <input type="checkbox" checked={form.scheduleTask} onChange={(e) => set('scheduleTask', e.target.checked)} />
              <span>Register as Windows Scheduled Task (auto-run on startup)</span>
            </label>
            <label className={styles.checkRow}>
              <input type="checkbox" checked={form.autoStart} onChange={(e) => set('autoStart', e.target.checked)} />
              <span>Start agent immediately after installation</span>
            </label>
          </div>

          <div className={styles.actions}>
            <button
              className={styles.generateBtn}
              onClick={handleGenerate}
              disabled={generating || !form.enrollmentToken}
            >
              {generating ? (
                <>⏳ Generating…</>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zm-8 2V5h2v6h1.17L12 13.17 9.83 11H11zm-6 7h14v2H5z"/></svg>
                  Generate &amp; Download Package
                </>
              )}
            </button>
            {generateError && (
              <div style={{ marginTop: 8, color: '#ef4444', fontSize: 13 }}>
                ⚠️ {generateError}
              </div>
            )}
          </div>
        </div>

        {/* ─── Right: Preview / Summary ─── */}
        <div className={styles.previewCard}>
          <h2 className={styles.previewTitle}>Package Summary</h2>

          <dl className={styles.summaryList}>
            <dt>Customer</dt>
            <dd className={styles.summaryCustomer}>{customerName}</dd>
            <dt>Server</dt><dd>{form.serverUrl || '—'}</dd>
            <dt>Token</dt><dd className={styles.mono}>{form.enrollmentToken}</dd>
            <dt>Agent Name</dt><dd>{form.agentName}</dd>
            <dt>Install Mode</dt><dd>{form.installMode}</dd>
            <dt>Architecture</dt><dd>{form.arch}</dd>
            <dt>Format</dt><dd>{form.format}</dd>
            <dt>Scheduled Task</dt><dd>{form.scheduleTask ? '✅ Yes' : '❌ No'}</dd>
            <dt>Auto-Start</dt><dd>{form.autoStart ? '✅ Yes' : '❌ No'}</dd>
          </dl>

          {generated && !generateError && (
            <div className={styles.downloadBox}>
              <svg viewBox="0 0 24 24" width="32" height="32" fill="#16a34a"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
              <div>
                <div className={styles.downloadTitle}>Download started!</div>
                <div className={styles.downloadHint}>Check your Downloads folder.</div>
              </div>
            </div>
          )}

          <div className={styles.infoBox}>
            <strong>How to deploy:</strong>
            <ol className={styles.stepList}>
              <li>Download the generated package</li>
              <li>Copy to the target machine (or shared drive / GPO)</li>
              <li>Run <code>setup.bat</code> as Administrator</li>
              <li>The agent will auto-enroll &amp; appear in Enrollment → Devices</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
