'use client';
export const dynamic = 'force-dynamic';
import { useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  getEnrollmentToken,
  getPackageCatalog,
  regenerateToken as apiRegenerateToken,
  getCustomers,
  type PackageCatalog,
} from '@/lib/api';
import styles from './page.module.css';

const INSTALL_MODES = ['Silent', 'Interactive'] as const;
const ARCH_OPTIONS = ['x64 (64-bit)', 'x86 (32-bit)', 'Both'] as const;
const PACKAGE_FORMATS = ['Single EXE Installer'] as const;

export default function DeploymentPackagePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const customerParam = searchParams.get('customer');
  const isPlaceholderCustomer = !customerParam || customerParam === 'default';
  const [customerId, setCustomerId] = useState(isPlaceholderCustomer ? '' : customerParam);
  const [customerName, setCustomerName] = useState(isPlaceholderCustomer ? 'Select customer' : customerParam);
  const [catalog, setCatalog] = useState<PackageCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  // Load customer name from API
  useEffect(() => {
    getCustomers()
      .then((list) => {
        if (isPlaceholderCustomer && list.length > 0) {
          const fallback = list[0];
          const nextCustomerId = fallback.slug || fallback.id;
          setCustomerId(nextCustomerId);
          setCustomerName(fallback.name);
          router.replace(`/enrollment/windows/package?customer=${nextCustomerId}`);
          return;
        }
        const activeCustomerId = isPlaceholderCustomer ? customerId : (customerParam || customerId);
        const match = list.find((c) => c.slug === activeCustomerId || c.id === activeCustomerId);
        if (match) {
          setCustomerId(match.slug || match.id);
          setCustomerName(match.name);
        }
      })
      .catch(() => {/* backend not available yet */});
  }, [customerId, customerParam, isPlaceholderCustomer, router]);

  const [form, setForm] = useState({
    serverUrl: '',
    enrollmentToken: '',
    agentName: 'NOCKO MDM Agent',
    installMode: 'Silent' as (typeof INSTALL_MODES)[number],
    arch: 'x64 (64-bit)' as (typeof ARCH_OPTIONS)[number],
    format: 'Single EXE Installer' as (typeof PACKAGE_FORMATS)[number],
    scheduleTask: true,
    autoStart: true,
    installPath: 'C:\\Program Files\\NOCKO MDM\\Agent',
    logPath: 'C:\\ProgramData\\NOCKO MDM\\logs',
  });

  // Fetch token from API for the active customer
  const fetchToken = useCallback(async () => {
    if (!customerId) return;
    try {
      const data = await getEnrollmentToken(customerId);
      setForm((f) => ({ ...f, enrollmentToken: data.token }));
    } catch {
      // backend unavailable — token stays empty
    }
  }, [customerId]);

  useEffect(() => { fetchToken(); }, [fetchToken]);

  const fetchCatalog = useCallback(async () => {
    if (!customerId) return;
    try {
      const data = await getPackageCatalog(customerId);
      setCatalog(data);
      setCatalogError(null);
      setCustomerName(data.customer_name);
      setForm((f) => ({
        ...f,
        serverUrl: data.server_url || f.serverUrl,
        enrollmentToken: data.enrollment_token || f.enrollmentToken,
      }));
    } catch (err) {
      setCatalog(null);
      setCatalogError(err instanceof Error ? err.message : String(err));
    }
  }, [customerId]);

  useEffect(() => { fetchCatalog(); }, [fetchCatalog]);


  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);
  const [copied, setCopied] = useState(false);

  const set = (key: string, val: unknown) =>
    setForm((f) => ({ ...f, [key]: val }));

  // Map UI label → API format value
  const formatToAPI = (label: string): string => {
    if (label.startsWith('Single')) return 'exe';
    return 'exe';
  };

  const archToAPI = (label: string): string => {
    if (label.startsWith('x86')) return 'x86';
    return 'x64';
  };

  const selectedFormat = formatToAPI(form.format);
  const selectedArch = archToAPI(form.arch);
  const selectedArtifact = catalog?.artifacts.find(
    (artifact) => artifact.format === selectedFormat && artifact.arch === selectedArch,
  );
  const selectedFormatAvailable = Boolean(selectedArtifact);

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      if (!customerId) {
        throw new Error('Select a valid customer before generating a package.');
      }
      if (!selectedArtifact) {
        throw new Error(
          `No prebuilt ${selectedFormat.toUpperCase()} release is available for ${selectedArch}. ` +
          'Publish the Windows agent from GitHub Actions first.',
        );
      }

      const res = await fetch('/api/mdm/packages/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(90_000), // 90s — backend downloads ~10 MB EXE from GitHub
        body: JSON.stringify({
          customer_id:   customerId,
          format:        selectedFormat,
          arch:          selectedArch,
          server_url:    form.serverUrl || undefined,
          install_mode:  form.installMode.toLowerCase(), // "silent" | "interactive"
          agent_display_name: form.agentName,
          install_dir: form.installPath,
          log_dir: form.logPath,
          register_scheduled_task: form.scheduleTask,
          start_immediately: form.autoStart,
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
      const message = e instanceof Error ? e.message : String(e);
      const isTimeout = e instanceof DOMException && e.name === 'TimeoutError';
      const isFetchFail = message === 'Failed to fetch';
      setGenerateError(
        isTimeout
          ? 'Package generation timed out. The server may be downloading the base EXE from GitHub — please try again.'
          : isFetchFail
            ? 'Could not reach the server. Ensure the backend is running and try again.'
            : message,
      );
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
    if (!customerId) return;
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
          <h1 className={styles.pageTitle}>Windows Enrollment</h1>
          <p className={styles.pageSubtitle}>
            Generate one Windows installer EXE with embedded cloud connection settings for this customer.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        <span className={`${styles.tab} ${styles.tabActive}`}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
            <path d="M20 6h-2.18c.07-.44.18-.88.18-1.36C18 2.54 15.46 0 12.36 0c-1.86 0-3.58.88-4.63 2.24L12 6.5l4.27-4.27c.34.77.73 1.57.73 2.41 0 2.21-1.79 4-4 4H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z"/>
          </svg>
          Deployment Package
        </span>
        <Link
          href={`/enrollment/windows/autopilot?customer=${customerId}`}
          className={styles.tab}
        >
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
            <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/>
          </svg>
          Windows Autopilot
        </Link>
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
              <div style={{ marginTop: 10, fontSize: 12, color: '#94a3b8' }}>
                The portal personalizes one prebuilt Windows EXE by embedding the customer bootstrap config directly into the file.
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
            <div style={{ marginTop: 10, fontSize: 12, color: '#94a3b8' }}>
              These values are embedded into the generated EXE bootstrap config and used during the self-install flow.
            </div>
          </div>

          {/* Section: Options */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>⚙️</span> Options
            </h2>
            <label className={styles.checkRow}>
              <input type="checkbox" checked={form.scheduleTask} onChange={(e) => set('scheduleTask', e.target.checked)} />
              <span>Reserved for legacy ZIP flow</span>
            </label>
            <label className={styles.checkRow}>
              <input type="checkbox" checked={form.autoStart} onChange={(e) => set('autoStart', e.target.checked)} />
              <span>Start the Windows service immediately after installation</span>
            </label>
          </div>

          <div className={styles.actions}>
            <button
              className={styles.generateBtn}
              onClick={handleGenerate}
              disabled={generating || !customerId || !form.enrollmentToken || !selectedFormatAvailable}
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
            {!generateError && !selectedFormatAvailable && (
              <div style={{ marginTop: 8, color: '#f59e0b', fontSize: 13 }}>
                ⚠️ No base EXE release artifact is configured yet for this architecture.
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
            <dt>Release Channel</dt><dd>{catalog?.release_channel ?? 'stable'}</dd>
            <dt>Release Version</dt><dd>{catalog?.release_version ?? 'Not published yet'}</dd>
            <dt>Agent Name</dt><dd>{form.agentName}</dd>
            <dt>Install Mode</dt><dd>{form.installMode}</dd>
            <dt>Architecture</dt><dd>{form.arch}</dd>
            <dt>Format</dt><dd>{form.format}</dd>
            <dt>Selected Artifact</dt><dd>{selectedArtifact?.filename ?? 'Unavailable'}</dd>
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

          {catalogError && (
            <div className={styles.infoBox} style={{ marginTop: 16, color: '#fca5a5' }}>
              <strong>Catalog status:</strong> {catalogError}
            </div>
          )}

          <div className={styles.infoBox}>
            <strong>How to deploy:</strong>
            <ol className={styles.stepList}>
              <li>Generate the customer-specific EXE from this page.</li>
              <li>Copy the EXE to the target Windows machine.</li>
              <li>Run the EXE as Administrator. It installs the agent service and writes the embedded config automatically.</li>
              <li>The device should auto-enroll and appear under Enrollment → Devices.</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
