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

export default function LinuxDeploymentPackagePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const customerParam = searchParams.get('customer');
  const isPlaceholderCustomer = !customerParam || customerParam === 'default';
  const [customerId, setCustomerId] = useState(isPlaceholderCustomer ? '' : customerParam);
  const [customerName, setCustomerName] = useState(isPlaceholderCustomer ? 'Select customer' : customerParam);
  const [serverUrl, setServerUrl] = useState('');
  const [enrollmentToken, setEnrollmentToken] = useState('');
  const [copied, setCopied] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);

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
    if (typeof window !== 'undefined') {
      setServerUrl(window.location.origin);
    }
  }, []);

  const fetchToken = useCallback(async () => {
    if (!customerId) return;
    try {
      const data = await getEnrollmentToken(customerId);
      setEnrollmentToken(data.token);
    } catch {
      // backend unavailable
    }
  }, [customerId]);

  useEffect(() => { fetchToken(); }, [fetchToken]);

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
    ? `curl -fsSL ${serverUrl}/api/v1/packages/install-linux.sh | sudo bash -s -- --url ${serverUrl} --token ${enrollmentToken}${customerId ? ` --customer ${customerId}` : ''}`
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
                <input
                  className={styles.input}
                  type="text"
                  value={enrollmentToken}
                  readOnly
                />
                <button className={styles.iconActionBtn} onClick={handleCopyToken} title="Copy token">
                  {copiedToken ? (
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

          {/* Install command */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <span className={styles.sectionIcon}>💻</span> Install Command
            </h2>
            <div className={styles.formRow}>
              <label className={styles.label}>Run this command on the target Linux machine (requires sudo)</label>
              <div style={{ position: 'relative' }}>
                <textarea
                  readOnly
                  value={installCmd || 'Select a customer and wait for token…'}
                  rows={3}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '10px 44px 10px 12px',
                    fontFamily: 'monospace', fontSize: 12,
                    background: '#1e1e2e', color: '#a6e3a1',
                    border: '1px solid #2d2d44', borderRadius: 6,
                    resize: 'none', lineHeight: 1.6,
                  }}
                />
                <button
                  onClick={handleCopy}
                  disabled={!installCmd}
                  title="Copy command"
                  style={{
                    position: 'absolute', top: 8, right: 8,
                    background: '#2d2d44', border: '1px solid #3d3d5a',
                    borderRadius: 4, padding: '4px 8px', cursor: 'pointer',
                    color: copied ? '#a6e3a1' : '#cdd6f4', fontSize: 11,
                    display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  {copied ? (
                    <>
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="#a6e3a1"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
                      Copied
                    </>
                  ) : (
                    <>
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
                      Copy
                    </>
                  )}
                </button>
              </div>
            </div>
            <div style={{ marginTop: 4, fontSize: 12, color: '#94a3b8' }}>
              The script downloads the NOCKO MDM agent binary, writes the config, and registers a systemd service automatically.
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
            <dt>Platform</dt>
            <dd>Linux (amd64)</dd>
            <dt>Install method</dt>
            <dd>curl | bash</dd>
            <dt>Service manager</dt>
            <dd>systemd</dd>
          </dl>

          <div className={styles.infoBox}>
            <strong>How to deploy:</strong>
            <ol className={styles.stepList}>
              <li>Copy the install command from this page.</li>
              <li>Open a terminal on the target Linux machine.</li>
              <li>Paste and run the command with <code>sudo</code>.</li>
              <li>The device will auto-enroll and appear under Enrollment → Devices.</li>
            </ol>
          </div>

          <div className={styles.infoBox} style={{ marginTop: 12 }}>
            <strong>Supported distros:</strong>
            <ol className={styles.stepList}>
              <li>Ubuntu 20.04 / 22.04 / 24.04</li>
              <li>Debian 11 / 12</li>
              <li>CentOS 7 / 8 / Stream</li>
              <li>RHEL 8 / 9</li>
              <li>Any systemd-based amd64 distro</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
