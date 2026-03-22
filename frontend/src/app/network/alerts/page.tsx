'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import styles from './alerts.module.css';

interface AlertRow {
  id: number;
  device_id: number;
  item_id: number | null;
  severity: string;
  message: string;
  source: string;
  active: boolean;
  opened_at: number;
  closed_at: number | null;
}

const SEV_COLOR: Record<string, string> = {
  critical: 'red', warning: 'orange', info: 'blue',
};

const SEV_ICON: Record<string, string> = {
  critical: '🔴', warning: '🟠', info: '🔵',
};

function timeAgo(ts: number | null): string {
  if (!ts) return '—';
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeOnly, setActiveOnly] = useState(true);
  const [severity, setSeverity] = useState('all');
  const [closing, setClosing] = useState<number | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const params = new URLSearchParams({ active_only: String(activeOnly) });
      if (severity !== 'all') params.set('severity', severity);
      const r = await fetch(`/api/agent/alerts?${params}`);
      if (r.ok) setAlerts(await r.json());
    } finally {
      setLoading(false);
    }
  }, [activeOnly, severity]);

  useEffect(() => {
    fetchAlerts();
    const t = setInterval(fetchAlerts, 15_000);
    return () => clearInterval(t);
  }, [fetchAlerts]);

  async function closeAlert(id: number) {
    setClosing(id);
    await fetch(`/api/agent/alerts/${id}/close`, { method: 'POST' });
    setTimeout(() => { setClosing(null); fetchAlerts(); }, 500);
  }

  const critical = alerts.filter(a => a.severity === 'critical').length;
  const warnings = alerts.filter(a => a.severity === 'warning').length;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Alerts</h1>
          <p className={styles.subtitle}>
            {critical > 0 && <span className={styles.criticalCount}>{critical} critical</span>}
            {warnings > 0 && <span className={styles.warningCount}>{warnings} warning</span>}
            {alerts.length === 0 && <span className={styles.okText}>All clear ✓</span>}
          </p>
        </div>
        <div className={styles.headerActions}>
          <label className={styles.toggle}>
            <input type="checkbox" checked={activeOnly} onChange={e => setActiveOnly(e.target.checked)} />
            Active only
          </label>
          <select className={styles.select} value={severity} onChange={e => setSeverity(e.target.value)}>
            <option value="all">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </div>
      </div>

      {/* Summary cards */}
      {activeOnly && (
        <div className={styles.summaryRow}>
          {[
            { label: 'Critical', count: critical, color: 'red', sev: 'critical' },
            { label: 'Warning', count: warnings, color: 'orange', sev: 'warning' },
            { label: 'Info', count: alerts.filter(a => a.severity === 'info').length, color: 'blue', sev: 'info' },
          ].map(s => (
            <button
              key={s.label}
              className={`${styles.summaryCard} ${styles[s.color]} ${severity === s.sev ? styles.active : ''}`}
              onClick={() => setSeverity(severity === s.sev ? 'all' : s.sev)}
            >
              <span className={styles.summaryIcon}>{SEV_ICON[s.sev]}</span>
              <span className={styles.summaryCount}>{s.count}</span>
              <span className={styles.summaryLabel}>{s.label}</span>
            </button>
          ))}
        </div>
      )}

      <div className={styles.card}>
        {loading ? (
          <div className={styles.loading}>Loading alerts…</div>
        ) : alerts.length === 0 ? (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>✅</div>
            <p>No alerts match your filters.</p>
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Device</th>
                <th>Source</th>
                <th>Message</th>
                <th>Opened</th>
                {!activeOnly && <th>Closed</th>}
                {activeOnly && <th>Action</th>}
              </tr>
            </thead>
            <tbody>
              {alerts.map(alert => (
                <tr key={alert.id} className={`${styles.row} ${alert.severity === 'critical' ? styles.rowCritical : ''}`}>
                  <td>
                    <span className={`${styles.badge} ${styles[`badge_${SEV_COLOR[alert.severity] || 'blue'}`]}`}>
                      {alert.severity}
                    </span>
                  </td>
                  <td>
                    <Link href={`/network/devices/${alert.device_id}`} className={styles.deviceLink}>
                      Device #{alert.device_id}
                    </Link>
                  </td>
                  <td className={styles.mono}>{alert.source || '—'}</td>
                  <td className={styles.message}>{alert.message}</td>
                  <td className={styles.muted}>{timeAgo(alert.opened_at)}</td>
                  {!activeOnly && <td className={styles.muted}>{timeAgo(alert.closed_at)}</td>}
                  {activeOnly && (
                    <td>
                      <button
                        className={styles.closeBtn}
                        onClick={() => closeAlert(alert.id)}
                        disabled={closing === alert.id}
                      >
                        {closing === alert.id ? '…' : 'Close'}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
