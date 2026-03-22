'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import styles from './devices.module.css';

interface DeviceRow {
  id: number;
  device_uid: string;
  name: string;
  ip: string;
  mac: string;
  vendor: string;
  model: string;
  device_class: string;
  online: boolean;
  last_seen: number | null;
  health_status: string;
  active_alerts: number;
  profile_id: number | null;
  owner_agent_id: number | null;
}

const HEALTH_COLOR: Record<string, string> = {
  ok: 'green', info: 'blue', warning: 'orange', critical: 'red',
};

const CLASS_ICON: Record<string, string> = {
  server: '🖥️', switch: '🔀', printer: '🖶', router: '📡', default: '📦',
};

function timeAgo(ts: number | null): string {
  if (!ts) return 'Never';
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function NetworkDevicesPage() {
  const [devices, setDevices] = useState<DeviceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [healthFilter, setHealthFilter] = useState('all');
  const [classFilter, setClassFilter] = useState('all');

  const fetchDevices = useCallback(async () => {
    try {
      const r = await fetch('/api/agent/devices');
      if (r.ok) setDevices(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDevices();
    const interval = setInterval(fetchDevices, 30_000);
    return () => clearInterval(interval);
  }, [fetchDevices]);

  const filtered = devices.filter(d => {
    const q = search.toLowerCase();
    const matchSearch = !q || d.name.toLowerCase().includes(q) ||
      d.ip.includes(q) || d.device_uid.toLowerCase().includes(q) ||
      d.vendor.toLowerCase().includes(q);
    const matchHealth = healthFilter === 'all' || d.health_status === healthFilter;
    const matchClass = classFilter === 'all' || d.device_class === classFilter;
    return matchSearch && matchHealth && matchClass;
  });

  const classes = Array.from(new Set(devices.map(d => d.device_class).filter(Boolean)));

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Network Devices</h1>
          <p className={styles.subtitle}>
            {devices.filter(d => d.online).length} online · {devices.length} total
          </p>
        </div>
      </div>

      {/* Stats summary */}
      <div className={styles.statsRow}>
        {Object.entries({ ok: 'Healthy', warning: 'Warning', critical: 'Critical' }).map(([k, label]) => (
          <button
            key={k}
            className={`${styles.statCard} ${styles[k]} ${healthFilter === k ? styles.active : ''}`}
            onClick={() => setHealthFilter(healthFilter === k ? 'all' : k)}
          >
            <div className={styles.statValue}>{devices.filter(d => d.health_status === k).length}</div>
            <div className={styles.statLabel}>{label}</div>
          </button>
        ))}
        <div className={`${styles.statCard} ${styles.blue}`}>
          <div className={styles.statValue}>{devices.filter(d => d.active_alerts > 0).length}</div>
          <div className={styles.statLabel}>With Alerts</div>
        </div>
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <input
          className={styles.search}
          placeholder="Search by name, IP, UID, vendor…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select
          className={styles.select}
          value={classFilter}
          onChange={e => setClassFilter(e.target.value)}
        >
          <option value="all">All types</option>
          {classes.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          className={styles.select}
          value={healthFilter}
          onChange={e => setHealthFilter(e.target.value)}
        >
          <option value="all">All health</option>
          <option value="ok">Healthy</option>
          <option value="warning">Warning</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      <div className={styles.card}>
        {loading ? (
          <div className={styles.loading}>Loading devices…</div>
        ) : filtered.length === 0 ? (
          <div className={styles.empty}>No devices match your filters.</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th></th>
                <th>Device</th>
                <th>IP</th>
                <th>Vendor / Model</th>
                <th>Health</th>
                <th>Alerts</th>
                <th>Last Seen</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(d => (
                <tr key={d.id}>
                  <td className={styles.iconCell}>
                    {CLASS_ICON[d.device_class] || CLASS_ICON.default}
                  </td>
                  <td className={styles.deviceName}>
                    <Link href={`/network/devices/${d.id}`}>{d.name || d.device_uid}</Link>
                    <span className={styles.muted}>{d.device_uid}</span>
                  </td>
                  <td className={styles.mono}>{d.ip || '—'}</td>
                  <td className={styles.muted}>
                    {d.vendor} {d.model}
                  </td>
                  <td>
                    <span className={`${styles.badge} ${styles[`badge_${HEALTH_COLOR[d.health_status] || 'blue'}`]}`}>
                      {d.health_status}
                    </span>
                  </td>
                  <td>
                    {d.active_alerts > 0 ? (
                      <span className={styles.alertCount}>{d.active_alerts}</span>
                    ) : (
                      <span className={styles.muted}>—</span>
                    )}
                  </td>
                  <td>
                    <span className={`${styles.dot} ${d.online ? styles.dotOnline : styles.dotOffline}`} />
                    <span className={styles.muted}> {timeAgo(d.last_seen)}</span>
                  </td>
                  <td>
                    <Link href={`/network/devices/${d.id}`} className={styles.actionBtn}>View →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
