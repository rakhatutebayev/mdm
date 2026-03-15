'use client';
export const dynamic = 'force-dynamic';
import { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import styles from './page.module.css';

const DEFAULT_HOST = 'https://mdm.nocko.com';

export default function AutoPilotPage() {
  const searchParams = useSearchParams();
  const customerId   = searchParams.get('customer') || 'default';

  const [serverUrl, setServerUrl] = useState(DEFAULT_HOST);

  useEffect(() => {
    fetch('/api/mdm/settings')
      .then((r) => r.json())
      .then((d) => { if (d?.mdm_server_url) setServerUrl(d.mdm_server_url.replace(/\/$/, '')); })
      .catch(() => {});
  }, []);

  const mdmUrl   = `${serverUrl}/mdm/microsoft/enrollment`;
  const termsUrl = `${serverUrl}/mdm/microsoft/terms`;

  const [copied, setCopied] = useState<string | null>(null);


  const copyVal = (key: string, val: string) => {
    navigator.clipboard.writeText(val).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const CopyBtn = ({ id, val }: { id: string; val: string }) => (
    <button className={styles.copyBtn} onClick={() => copyVal(id, val)} title="Copy">
      {copied === id ? (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="#16a34a">
          <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
          <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
        </svg>
      )}
    </button>
  );

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Windows Enrollment</h1>
        <p className={styles.pageSubtitle}>
          Enroll Windows 10/11 devices via native MDM (OMA-DM) or the NOCKO agent package.
        </p>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        <Link
          href={`/enrollment/windows/package?customer=${customerId}`}
          className={styles.tab}
        >
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
            <path d="M20 6h-2.18c.07-.44.18-.88.18-1.36C18 2.54 15.46 0 12.36 0c-1.86 0-3.58.88-4.63 2.24L12 6.5l4.27-4.27c.34.77.73 1.57.73 2.41 0 2.21-1.79 4-4 4H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z"/>
          </svg>
          Deployment Package
        </Link>
        <span className={`${styles.tab} ${styles.tabActive}`}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
            <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/>
          </svg>
          Windows Autopilot
        </span>
      </div>

      <div className={styles.layout}>
        {/* ── Left column ── */}
        <div className={styles.card}>

          {/* MDM Server Endpoints */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>🔗 MDM Server Endpoints</h2>
            <div className={styles.formRow}>
              <label className={styles.label}>MDM Enrollment URL</label>
              <div className={styles.inputRow}>
                <input className={styles.input} value={mdmUrl} readOnly />
                <CopyBtn id="mdm_url" val={mdmUrl} />
              </div>
              <span className={styles.hint}>
                Entra ID → Mobility → MDM User Scope → Discovery Service URL
              </span>
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Terms of Use URL</label>
              <div className={styles.inputRow}>
                <input className={styles.input} value={termsUrl} readOnly />
                <CopyBtn id="terms_url" val={termsUrl} />
              </div>
            </div>
          </div>

          {/* Entra ID Steps */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>🏢 Azure Entra ID Setup</h2>
            <div className={styles.steps}>
              <div className={styles.step}>
                <div className={styles.stepNum}>1</div>
                <div className={styles.stepText}>
                  In <strong>Entra ID → Mobility (MDM and WIP)</strong>, add NOCKO MDM as an app.
                  Set MDM User Scope to <code>All</code> or a specific group.
                </div>
              </div>
              <div className={styles.step}>
                <div className={styles.stepNum}>2</div>
                <div className={styles.stepText}>
                  Set <strong>MDM Discovery URL</strong> to:{' '}
                  <code>{mdmUrl}</code>
                </div>
              </div>
              <div className={styles.step}>
                <div className={styles.stepNum}>3</div>
                <div className={styles.stepText}>
                  On the Windows device: <strong>Settings → Accounts → Access work or school → Connect</strong>.
                  Sign in with Entra ID credentials — the device auto-enrolls.
                </div>
              </div>
              <div className={styles.step}>
                <div className={styles.stepNum}>4</div>
                <div className={styles.stepText}>
                  The device appears in <strong>Enrollment → Devices</strong> with status{' '}
                  <span className={`${styles.badge} ${styles.badgeGreen}`}>Enrolled</span>.
                </div>
              </div>
            </div>
          </div>

          {/* PowerShell alternative */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>💻 PowerShell Manual Enroll</h2>
            <div className={styles.infoPanel}>
              <div className={styles.infoPanelTitle}>Run as Administrator</div>
              <pre className={styles.codeBlock}>{
`# Enroll device to NOCKO MDM via OMA-DM
$ServerURL   = "${mdmUrl}"
$EnrollToken = "YOUR-ENROLLMENT-TOKEN"

$body = @{ token = $EnrollToken; server = $ServerURL } | ConvertTo-Json
Invoke-RestMethod -Method Post \\
  -Uri "$ServerURL/enroll" \\
  -Body $body -ContentType "application/json"
Write-Host "Enrollment complete."`
              }</pre>
            </div>
          </div>
        </div>

        {/* ── Right side panel ── */}
        <div className={styles.sideCard}>
          <div className={styles.sideTitle}>Which method to use?</div>

          <div className={styles.reqList}>
            <div style={{ fontWeight: 600, fontSize: 12, color: '#23252e', marginBottom: 6 }}>
              Windows Autopilot ← you are here
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Native OMA-DM (built into Windows)</span>
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Requires Azure Entra ID tenant</span>
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Zero-touch for domain-joined orgs</span>
            </div>
          </div>

          <div className={styles.separator} />

          <div className={styles.reqList}>
            <div style={{ fontWeight: 600, fontSize: 12, color: '#23252e', marginBottom: 6 }}>
              <Link href={`/enrollment/windows/package?customer=${customerId}`} style={{ color: '#4a7cff', textDecoration: 'none' }}>
                Deployment Package →
              </Link>
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Standalone NOCKO agent (no Azure needed)</span>
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Works on any Windows 10/11 (domain or workgroup)</span>
            </div>
            <div className={styles.reqItem}>
              <span className={styles.reqDot}>·</span>
              <span>Single EXE/ZIP with token embedded</span>
            </div>
          </div>

          <div className={styles.separator} />

          <div style={{ fontSize: 12, color: '#8b90a4' }}>
            For MSP deployments without Azure, use the{' '}
            <Link href={`/enrollment/windows/package?customer=${customerId}`} style={{ color: '#4a7cff' }}>
              Deployment Package
            </Link>{' '}
            approach.
          </div>
        </div>
      </div>
    </div>
  );
}
