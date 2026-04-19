'use client';
export const dynamic = 'force-dynamic';
import { useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  getEnrollmentToken,
  regenerateToken as apiRegenerateToken,
  getCustomers,
} from '@/lib/api';
import styles from '../../windows/package/page.module.css';

// ── Distro catalog ────────────────────────────────────────────────────────────
// Each entry: { slug (sent to backend), label, family, icon }
const DISTROS = [
  // RedHat family
  { slug: 'centos7',    label: 'CentOS 7',               family: 'rpm', icon: '🐧' },
  { slug: 'centos8',    label: 'CentOS 8 / Stream 8',    family: 'rpm', icon: '🐧' },
  { slug: 'centos9',    label: 'CentOS Stream 9',         family: 'rpm', icon: '🐧' },
  { slug: 'rhel7',      label: 'RHEL 7',                  family: 'rpm', icon: '🎩' },
  { slug: 'rhel8',      label: 'RHEL 8',                  family: 'rpm', icon: '🎩' },
  { slug: 'rhel9',      label: 'RHEL 9',                  family: 'rpm', icon: '🎩' },
  { slug: 'almalinux',  label: 'AlmaLinux 8 / 9',         family: 'rpm', icon: '🐧' },
  { slug: 'rocky',      label: 'Rocky Linux 8 / 9',       family: 'rpm', icon: '🐧' },
  { slug: 'fedora',     label: 'Fedora 38 / 39 / 40',     family: 'rpm', icon: '🐧' },
  // Debian family
  { slug: 'ubuntu',     label: 'Ubuntu 20.04 / 22.04',    family: 'deb', icon: '🟠' },
  { slug: 'ubuntu',     label: 'Ubuntu 24.04',            family: 'deb', icon: '🟠' },
  { slug: 'debian',     label: 'Debian 11 / 12',          family: 'deb', icon: '🌀' },
] as const;

type DistroSlug = typeof DISTROS[number]['slug'];

const FAMILY_LABELS: Record<string, string> = {
  rpm: 'RedHat / CentOS family  (glibc 2.17+)',
  deb: 'Debian / Ubuntu family  (glibc 2.31+)',
};

export default function LinuxDeploymentPackagePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const customerParam = searchParams.get('customer');
  const isPlaceholderCustomer = !customerParam || customerParam === 'default';
  const [customerId, setCustomerId] = useState(isPlaceholderCustomer ? '' : customerParam);
  const [customerName, setCustomerName] = useState(isPlaceholderCustomer ? 'Select customer' : customerParam);
  const [serverUrl, setServerUrl] = useState('');
  const [enrollmentToken, setEnrollmentToken] = useState('');
  const [agentVersion, setAgentVersion] = useState('—');
  const [copied, setCopied] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [selectedDistro, setSelectedDistro] = useState<DistroSlug>('centos7');

  useEffect(() => {
    getCustomers()
      .then((list) => {
        if (isPlaceholderCustomer && list.length > 0) {
          const fallback = list[0];
          const nextCustomerId = fallback.slug || fallback.id;
          setCustomerId(nextCustomerId);
          setCustomerName(fallback.name);
          router.replace(`/enrollment/linux/package?customer=${nextCustomerId}`);
          return;
        }
        const activeCustomerId = isPlaceholderCustomer ? customerId : (customerParam || customerId);
        const match = list.find((c) => c.slug === activeCustomerId || c.id === activeCustomerId);
        if (match) {
          setCustomerId(match.slug || match.id);
          setCustomerName(match.name);
        }
      })
      .catch(() => {});
  }, [customerId, customerParam, isPlaceholderCustomer, router]);

  useEffect(() => {
    if (typeof window !== 'undefined') setServerUrl(window.location.origin);
  }, []);

  const fetchToken = useCallback(async () => {
    if (!customerId) return;
    try {
      const data = await getEnrollmentToken(customerId);
      setEnrollmentToken(data.token);
    } catch { /* backend unavailable */ }
  }, [customerId]);

  useEffect(() => { fetchToken(); }, [fetchToken]);

  useEffect(() => {
    if (!serverUrl) return;
    fetch(`${serverUrl}/api/v1/packages/latest/linux-version?distro=${selectedDistro}`)
      .then(r => r.text())
      .then(v => setAgentVersion(v.trim() || '—'))
      .catch(() => {});
  }, [serverUrl, selectedDistro]);

  const regenerateToken = async () => {
    if (!customerId) return;
    try {
      const data = await apiRegenerateToken(customerId);
      setEnrollmentToken(data.token);
    } catch {
      setEnrollmentToken('enroll-' + Math.random().toString(36).slice(2, 10).toUpperCase());
    }
  };

  const installCmd = enrollmentToken && serverUrl
    ? `curl -fsSL ${serverUrl}/api/v1/packages/install-linux.sh | sudo bash -s -- --url ${serverUrl} --token ${enrollmentToken}${customerId ? ` --customer ${customerId}` : ''} --distro ${selectedDistro}`
    : '';

  const handleCopy = () => {
    if (!installCmd) return;
    navigator.clipboard.writeText(installCmd).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleCopyToken = () => {
    navigator.clipboard.writeText(enrollmentToken).then(() => {
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    });
  };

  const currentDistroInfo = DISTROS.find(d => d.slug === selectedDistro) ?? DISTROS[0];

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Linux Enrollment</h1>
          <p className={styles.pageSubtitle}>
            One-line bash installer with embedded connection settings for this customer.
          </p>
        </div>
      </div>

      <div className={styles.layout}>
        {/* ─── Left: Form ─── */}
        <div className={styles.formCard}>
          {/* Connection */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>🔗</span> Connection
            </h2>

            <div className={styles.formRow}>
              <label className={styles.label}>MDM Server URL</label>
              <input
                className={styles.input}
                type="text"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
              />
            </div>

            <div className={styles.formRow}>
              <label className={styles.label}>Enrollment Token</label>
              <div className={styles.tokenRow}>
                <input className={styles.input} type="text" value={enrollmentToken} readOnly />
                <button className={styles.iconActionBtn} onClick={handleCopyToken} title="Copy token">
                  {copiedToken
                    ? <svg viewBox="0 0 24 24" width="15" height="15" fill="#16a34a"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
                    : <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
                  }
                </button>
                <button className={styles.iconActionBtn} onClick={regenerateToken} title="Regenerate token">
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M17.65 6.35A7.96 7.96 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                </button>
              </div>
            </div>
          </div>

          {/* Distro selector */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>🐧</span> Linux Distribution
            </h2>

            <div className={styles.formRow}>
              <label className={styles.label}>Select your distro</label>
              <select
                className={styles.input}
                value={selectedDistro}
                onChange={(e: { target: HTMLSelectElement }) => setSelectedDistro(e.target.value as DistroSlug)}
              >
                <optgroup label="RedHat / CentOS family">
                  {DISTROS.filter(d => d.family === 'rpm').map((d, i) => (
                    <option key={`rpm-${i}`} value={d.slug}>{d.icon} {d.label}</option>
                  ))}
                </optgroup>
                <optgroup label="Debian / Ubuntu family">
                  {DISTROS.filter(d => d.family === 'deb').map((d, i) => (
                    <option key={`deb-${i}`} value={d.slug}>{d.icon} {d.label}</option>
                  ))}
                </optgroup>
              </select>
            </div>

            <div style={{
              marginTop: 8, padding: '8px 12px',
              background: '#f0f4ff', borderRadius: 6,
              border: '1px solid #c7d2fe',
              fontSize: 12, color: '#4a5580',
              display: 'flex', gap: 8, alignItems: 'center',
            }}>
              <span>ℹ️</span>
              <span>
                <strong>{currentDistroInfo.label}</strong> — {FAMILY_LABELS[currentDistroInfo.family]}.
                The installer will download the correct binary automatically.
              </span>
            </div>
          </div>

          {/* Install command */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>💻</span> Install Command
            </h2>
            <div className={styles.formRow}>
              <label className={styles.label}>Run on the target machine (requires root)</label>
              <div style={{ position: 'relative' }}>
                <textarea
                  readOnly
                  value={installCmd || 'Select a customer and wait for token…'}
                  rows={3}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '10px 44px 10px 12px',
                    fontFamily: 'monospace', fontSize: 12,
                    background: '#f8f9fc', color: '#1a1c2e',
                    border: '1px solid #e2e4ec', borderRadius: 6,
                    resize: 'none', lineHeight: 1.6,
                  }}
                />
                <button
                  onClick={handleCopy}
                  disabled={!installCmd}
                  title="Copy command"
                  style={{
                    position: 'absolute', top: 8, right: 8,
                    background: '#eef1ff', border: '1px solid #c7d2fe',
                    borderRadius: 4, padding: '4px 8px', cursor: 'pointer',
                    color: copied ? '#059669' : '#4a7cff', fontSize: 11,
                    display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  {copied ? (
                    <><svg viewBox="0 0 24 24" width="12" height="12" fill="#059669"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>Copied</>
                  ) : (
                    <><svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>Copy</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ─── Right: Summary ─── */}
        <div className={styles.previewCard}>
          <h2 className={styles.previewTitle}>Deployment Summary</h2>

          <dl className={styles.summaryList}>
            <dt>Customer</dt>
            <dd className={styles.summaryCustomer}>{customerName}</dd>
            <dt>Server</dt>
            <dd>{serverUrl || '—'}</dd>
            <dt>Token</dt>
            <dd className={styles.mono}>{enrollmentToken || '—'}</dd>
            <dt>Distribution</dt>
            <dd>{currentDistroInfo.icon} {currentDistroInfo.label}</dd>
            <dt>Family</dt>
            <dd>{FAMILY_LABELS[currentDistroInfo.family]}</dd>
            <dt>Agent Version</dt>
            <dd>{agentVersion}</dd>
            <dt>Install method</dt>
            <dd>curl | bash</dd>
            <dt>Service manager</dt>
            <dd>systemd</dd>
          </dl>

          <div className={styles.infoBox}>
            <strong>How to deploy:</strong>
            <ol className={styles.stepList}>
              <li>Select your Linux distribution above.</li>
              <li>Copy the install command.</li>
              <li>Paste and run on the target machine as root.</li>
              <li>The device auto-enrolls and appears under Enrollment → Devices.</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
