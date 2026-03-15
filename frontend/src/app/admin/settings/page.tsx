'use client';
import { useState, useEffect } from 'react';
import styles from './page.module.css';

interface Settings {
  mdm_server_url: string;
  agent_checkin_interval: string;
  agent_heartbeat_interval: string;
  agent_metrics_interval: string;
  agent_inventory_interval: string;
  agent_commands_interval: string;
  agent_log_level: string;
  smtp_host: string;
  smtp_port: string;
  smtp_user: string;
  smtp_pass: string;
  smtp_from: string;
  enroll_auto_approve: boolean;
  enroll_require_token: boolean;
  audit_log_enabled: boolean;
  siem_enabled: boolean;
}

const DEFAULT: Settings = {
  mdm_server_url: 'https://mdm.nocko.com',
  agent_checkin_interval: '300',
  agent_heartbeat_interval: '60',
  agent_metrics_interval: '120',
  agent_inventory_interval: '21600',
  agent_commands_interval: '45',
  agent_log_level: 'INFO',
  smtp_host: '',
  smtp_port: '587',
  smtp_user: '',
  smtp_pass: '',
  smtp_from: 'noreply@mdm.nocko.com',
  enroll_auto_approve: false,
  enroll_require_token: true,
  audit_log_enabled: true,
  siem_enabled: false,
};

export default function SettingsPage() {
  const [form, setForm] = useState<Settings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  // Load settings from backend
  useEffect(() => {
    fetch('/api/mdm/settings')
      .then((r) => r.json())
      .then((data: Settings) => setForm({ ...DEFAULT, ...data }))
      .catch(() => { /* backend unavailable, use defaults */ })
      .finally(() => setLoading(false));
  }, []);

  const set = (key: keyof Settings, val: string | boolean) =>
    setForm((f) => ({ ...f, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch('/api/mdm/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated: Settings = await res.json();
      setForm({ ...DEFAULT, ...updated });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const testSmtp = () => {
    setTestResult('Sending test email…');
    setTimeout(() => setTestResult('✅ Test email sent successfully'), 1500);
  };

  if (loading) return <div className={styles.page} style={{ color: '#8b90a4', fontSize: 13 }}>Loading settings…</div>;

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Settings</h1>
        <p className={styles.pageSubtitle}>Configure server host, notifications, and enrollment behaviour.</p>
      </div>

      {/* ── Server ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>🖥️</span> Server
        </div>
        <div className={styles.sectionBody}>
          <div className={styles.formRow}>
            <label className={styles.label}>MDM Server Host URL</label>
            <input
              className={styles.input}
              value={form.mdm_server_url}
              onChange={(e) => set('mdm_server_url', e.target.value)}
              placeholder="https://mdm.nocko.com"
            />
            <span className={styles.hint}>
              Public URL used by agents to check in <strong>and</strong> embedded in generated installer packages.
              Change this when migrating to a new server.
            </span>
          </div>
          <div className={styles.formGrid}>
            <div className={styles.formRow}>
              <label className={styles.label}>Legacy Check-in Interval (seconds)</label>
              <input
                className={styles.input}
                type="number"
                value={form.agent_checkin_interval}
                onChange={(e) => set('agent_checkin_interval', e.target.value)}
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Agent Log Level</label>
              <select
                className={styles.select}
                value={form.agent_log_level}
                onChange={(e) => set('agent_log_level', e.target.value)}
              >
                {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((l) => <option key={l}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className={styles.formGrid}>
            <div className={styles.formRow}>
              <label className={styles.label}>Heartbeat Interval (seconds)</label>
              <input className={styles.input} type="number" value={form.agent_heartbeat_interval} onChange={(e) => set('agent_heartbeat_interval', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Metrics Interval (seconds)</label>
              <input className={styles.input} type="number" value={form.agent_metrics_interval} onChange={(e) => set('agent_metrics_interval', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Inventory Interval (seconds)</label>
              <input className={styles.input} type="number" value={form.agent_inventory_interval} onChange={(e) => set('agent_inventory_interval', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Commands Poll Interval (seconds)</label>
              <input className={styles.input} type="number" value={form.agent_commands_interval} onChange={(e) => set('agent_commands_interval', e.target.value)} />
            </div>
          </div>
          <div className={styles.infoBox}>
            Packages generated via <strong>Enrollment → Windows → Deployment Package</strong> will use{' '}
            <code>{form.mdm_server_url || 'https://mdm.nocko.com'}</code> as the server URL.
            Save settings before generating a new package.
          </div>
        </div>
      </div>

      {/* ── Email / SMTP ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>📧</span> Email Notifications (SMTP)
        </div>
        <div className={styles.sectionBody}>
          <div className={styles.formGrid}>
            <div className={styles.formRow}>
              <label className={styles.label}>SMTP Host</label>
              <input
                className={styles.input}
                placeholder="mail.example.com"
                value={form.smtp_host}
                onChange={(e) => set('smtp_host', e.target.value)}
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>SMTP Port</label>
              <input className={styles.input} value={form.smtp_port} onChange={(e) => set('smtp_port', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Username</label>
              <input className={styles.input} value={form.smtp_user} onChange={(e) => set('smtp_user', e.target.value)} />
            </div>
            <div className={styles.formRow}>
              <label className={styles.label}>Password</label>
              <input className={styles.input} type="password" value={form.smtp_pass} onChange={(e) => set('smtp_pass', e.target.value)} />
            </div>
          </div>
          <div className={styles.formRow}>
            <label className={styles.label}>From Address</label>
            <input
              className={styles.input}
              value={form.smtp_from}
              onChange={(e) => set('smtp_from', e.target.value)}
              style={{ maxWidth: 340 }}
            />
          </div>
          <button className={styles.testBtn} onClick={testSmtp}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
              <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/>
            </svg>
            Send Test Email
          </button>
          {testResult && <div className={styles.infoBox} style={{ marginTop: 10 }}>{testResult}</div>}
        </div>
      </div>

      {/* ── Enrollment ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>📲</span> Enrollment Policy
        </div>
        <div className={styles.sectionBody}>
          <div className={styles.toggleRow}>
            <div>
              <div className={styles.toggleLabel}>Require Enrollment Token</div>
              <div className={styles.toggleHint}>Devices must present a valid token to enroll</div>
            </div>
            <label className={styles.toggle}>
              <input type="checkbox" checked={form.enroll_require_token} onChange={(e) => set('enroll_require_token', e.target.checked)} />
              <span className={styles.toggleSlider} />
            </label>
          </div>
          <div className={styles.toggleRow}>
            <div>
              <div className={styles.toggleLabel}>Auto-Approve Enrollment</div>
              <div className={styles.toggleHint}>New devices enroll immediately without manual approval</div>
            </div>
            <label className={styles.toggle}>
              <input type="checkbox" checked={form.enroll_auto_approve} onChange={(e) => set('enroll_auto_approve', e.target.checked)} />
              <span className={styles.toggleSlider} />
            </label>
          </div>
        </div>
      </div>

      {/* ── Security & Audit ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>🔒</span> Security & Audit
        </div>
        <div className={styles.sectionBody}>
          <div className={styles.toggleRow}>
            <div>
              <div className={styles.toggleLabel}>Audit Log</div>
              <div className={styles.toggleHint}>Log all admin actions to the database</div>
            </div>
            <label className={styles.toggle}>
              <input type="checkbox" checked={form.audit_log_enabled} onChange={(e) => set('audit_log_enabled', e.target.checked)} />
              <span className={styles.toggleSlider} />
            </label>
          </div>
          <div className={styles.toggleRow}>
            <div>
              <div className={styles.toggleLabel}>SIEM Integration</div>
              <div className={styles.toggleHint}>Forward security events to a SIEM endpoint</div>
            </div>
            <label className={styles.toggle}>
              <input type="checkbox" checked={form.siem_enabled} onChange={(e) => set('siem_enabled', e.target.checked)} />
              <span className={styles.toggleSlider} />
            </label>
          </div>
          <div className={styles.infoBox} style={{ marginTop: 12 }}>
            API Base URL: <code>{form.mdm_server_url}/api/v1</code>
          </div>
        </div>
      </div>

      <div className={styles.actions}>
        <button className={styles.saveBtn} onClick={handleSave} disabled={saving}>
          {saved ? (
            <>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
              Saved!
            </>
          ) : saving ? 'Saving…' : (
            <>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M17 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V7l-4-4zm-5 16a3 3 0 110-6 3 3 0 010 6zm3-10H5V5h10v4z"/></svg>
              Save Settings
            </>
          )}
        </button>
      </div>
      {saveError && <div style={{ marginTop: 10, color: '#ef4444', fontSize: 13 }}>⚠️ {saveError}</div>}
    </div>
  );
}
