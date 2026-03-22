'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import styles from './device.module.css';

interface DeviceDetail {
  id: number;
  device_uid: string;
  name: string;
  ip: string;
  mac: string;
  serial: string;
  vendor: string;
  model: string;
  device_class: string;
  location: string;
  online: boolean;
  last_seen: number | null;
  health_status: string;
  active_alerts: number;
  profile_id: number | null;
  owner_agent_id: number | null;
  inventory: {
    vendor: string; model: string; serial: string;
    cpu_model: string; ram_gb: number | null;
    disk_count: number | null; firmware_version: string;
    updated_at: string;
  } | null;
  last_values: { key: string; name: string; value: string; value_type: string; clock: number }[];
  alerts: { id: number; severity: string; message: string; source: string; opened_at: number }[];
}

interface HistoryPoint { clock: number; value: number }

const HEALTH_BORDER: Record<string, string> = {
  ok: '#22c55e44', warning: '#f59e0b44', critical: '#ef444466',
};

const SEV_COLOR: Record<string, string> = {
  critical: '#ef4444', warning: '#f59e0b', info: '#60a5fa',
};

function timeAgo(ts: number | null): string {
  if (!ts) return 'Never';
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function MiniSparkline({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) return <span className={styles.sparklineEmpty}>—</span>;
  const values = points.map(p => Number(p.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const W = 80, H = 28;
  const pts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((Number(p.value) - min) / range) * H;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={W} height={H} className={styles.sparkline}>
      <polyline points={pts} fill="none" stroke="#7b8cff" strokeWidth="1.5" />
    </svg>
  );
}

export default function DeviceDetailPage({ params }: { params: { id: string } }) {
  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [history, setHistory] = useState<Record<string, HistoryPoint[]>>({});
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'metrics' | 'inventory' | 'alerts' | 'events' | 'templates'>('metrics');

  const fetchDevice = useCallback(async () => {
    const r = await fetch(`/api/agent/devices/${params.id}`);
    if (r.ok) {
      const data: DeviceDetail = await r.json();
      setDevice(data);
      if (!selectedKey && data.last_values.length > 0) {
        setSelectedKey(data.last_values[0].key);
      }
    }
    setLoading(false);
  }, [params.id, selectedKey]);

  const fetchHistory = useCallback(async (key: string, itemId: number, valueType: string) => {
    const from = Math.floor(Date.now() / 1000) - 3600; // last hour
    const r = await fetch(
      `/api/agent/devices/${params.id}/history?item_id=${itemId}&value_type=${valueType}&from_ts=${from}&limit=120`
    );
    if (r.ok) {
      const data = await r.json();
      setHistory(prev => ({ ...prev, [key]: data }));
    }
  }, [params.id]);

  useEffect(() => {
    fetchDevice();
    const t = setInterval(fetchDevice, 30_000);
    return () => clearInterval(t);
  }, [fetchDevice]);

  // Fetch history when a metric key is selected
  useEffect(() => {
    if (!device || !selectedKey) return;
    const lv = device.last_values.find(v => v.key === selectedKey);
    if (lv && !['string', 'text', 'log'].includes(lv.value_type)) {
      fetchHistory(lv.key, 0, lv.value_type);
    }
  }, [selectedKey, device, fetchHistory]);

  if (loading) return <div className={styles.loading}>Loading device…</div>;
  if (!device) return <div className={styles.loading}>Device not found.</div>;

  const healthColor = HEALTH_BORDER[device.health_status] || '#2d3048';
  const selectedLv = device.last_values.find(v => v.key === selectedKey);
  const sparkPoints = selectedKey ? (history[selectedKey] || []) : [];

  return (
    <div className={styles.page}>
      {/* Breadcrumb */}
      <div className={styles.breadcrumb}>
        <Link href="/network/devices">← Network Devices</Link>
        <span> / </span>
        <span>{device.name || device.device_uid}</span>
      </div>

      {/* Header */}
      <div className={styles.header} style={{ borderColor: healthColor }}>
        <div className={styles.headerLeft}>
          <div className={styles.deviceClass}>{device.device_class || 'device'}</div>
          <h1 className={styles.title}>{device.name || device.device_uid}</h1>
          <div className={styles.headerMeta}>
            <span className={styles.metaItem}>🌐 {device.ip || '—'}</span>
            <span className={styles.metaItem}>🔑 {device.device_uid}</span>
            {device.serial && <span className={styles.metaItem}>S/N: {device.serial}</span>}
            {device.location && <span className={styles.metaItem}>📍 {device.location}</span>}
          </div>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.onlineBadge} data-online={device.online}>
            {device.online ? '● Online' : '● Offline'}
          </div>
          <div className={`${styles.healthBadge} ${styles[`health_${device.health_status}`]}`}>
            {device.health_status}
          </div>
          {device.active_alerts > 0 && (
            <div className={styles.alertPill}>{device.active_alerts} alert{device.active_alerts > 1 ? 's' : ''}</div>
          )}
          <div className={styles.lastSeen}>Last seen: {timeAgo(device.last_seen)}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {(['metrics', 'inventory', 'alerts', 'events', 'templates'] as const).map(t => (
          <button key={t} className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
            onClick={() => setTab(t)}>
            {t === 'alerts' && device.active_alerts > 0
              ? `Alerts (${device.active_alerts})`
              : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* METRICS TAB */}
      {tab === 'metrics' && (
        <div className={styles.metricsLayout}>
          {/* Left: metric list */}
          <div className={styles.metricList}>
            {device.last_values.length === 0 ? (
              <div className={styles.emptyState}>No metrics collected yet.</div>
            ) : (
              device.last_values.map(lv => (
                <button
                  key={lv.key}
                  className={`${styles.metricRow} ${selectedKey === lv.key ? styles.metricRowActive : ''}`}
                  onClick={() => setSelectedKey(lv.key)}
                >
                  <div className={styles.metricKey}>{lv.key}</div>
                  <div className={styles.metricValue}>
                    <span className={styles.metricVal}>{lv.value}</span>
                    <span className={styles.metricType}>{lv.value_type}</span>
                  </div>
                  <div className={styles.metricTime}>{timeAgo(lv.clock)}</div>
                </button>
              ))
            )}
          </div>

          {/* Right: detail */}
          <div className={styles.metricDetail}>
            {selectedLv ? (
              <>
                <div className={styles.detailHeader}>
                  <div className={styles.detailKey}>{selectedLv.key}</div>
                  <div className={styles.detailName}>{selectedLv.name}</div>
                </div>
                <div className={styles.currentValue}>
                  {selectedLv.value}
                  <span className={styles.currentUnit}>{selectedLv.value_type}</span>
                </div>
                <div className={styles.chartSection}>
                  <div className={styles.chartTitle}>Last hour</div>
                  {sparkPoints.length >= 2 ? (
                    <FullChart points={sparkPoints} />
                  ) : (
                    <div className={styles.chartEmpty}>
                      {['string', 'text', 'log'].includes(selectedLv.value_type)
                        ? 'String values have no chart.'
                        : 'Not enough data points yet.'}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className={styles.emptyState}>Select a metric to view details.</div>
            )}
          </div>
        </div>
      )}

      {/* INVENTORY TAB */}
      {tab === 'inventory' && (
        <div className={styles.inventoryGrid}>
          {!device.inventory ? (
            <div className={styles.emptyState}>No inventory data collected yet.</div>
          ) : (
            [
              { label: 'Vendor', value: device.inventory.vendor },
              { label: 'Model', value: device.inventory.model },
              { label: 'Serial Number', value: device.inventory.serial },
              { label: 'CPU Model', value: device.inventory.cpu_model },
              { label: 'RAM', value: device.inventory.ram_gb != null ? `${device.inventory.ram_gb} GB` : '—' },
              { label: 'Disks', value: device.inventory.disk_count != null ? String(device.inventory.disk_count) : '—' },
              { label: 'Firmware', value: device.inventory.firmware_version },
              { label: 'Last Updated', value: device.inventory.updated_at },
            ].map(row => (
              <div key={row.label} className={styles.invRow}>
                <span className={styles.invLabel}>{row.label}</span>
                <span className={styles.invValue}>{row.value || '—'}</span>
              </div>
            ))
          )}
        </div>
      )}

      {/* ALERTS TAB */}
      {tab === 'alerts' && (
        <div className={styles.alertsList}>
          {device.alerts.length === 0 ? (
            <div className={styles.emptyState}>✅ No active alerts.</div>
          ) : (
            device.alerts.map(alert => (
              <div key={alert.id} className={styles.alertCard} style={{ borderColor: SEV_COLOR[alert.severity] + '44' }}>
                <div className={styles.alertSev} style={{ color: SEV_COLOR[alert.severity] }}>
                  ● {alert.severity}
                </div>
                <div className={styles.alertMsg}>{alert.message}</div>
                <div className={styles.alertMeta}>
                  <span>{alert.source}</span>
                  <span>Opened {timeAgo(alert.opened_at)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* EVENTS TAB */}
      {tab === 'events' && <EventsPanel deviceId={params.id} />}

      {/* TEMPLATES TAB */}
      {tab === 'templates' && <TemplatesPanel deviceId={params.id} />}
    </div>
  );
}

// ── Templates Panel ──────────────────────────────────────────────────────────
function TemplatesPanel({ deviceId }: { deviceId: string }) {
  const [profiles, setProfiles] = useState<{ id: number; name: string; templates: { id: number; name: string }[] }[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    fetch('/api/agent/profiles')
      .then(r => r.json())
      .then(async (ps: { id: number; name: string }[]) => {
        const withTemplates = await Promise.all(ps.map(async p => {
          const r = await fetch(`/api/agent/profiles/${p.id}/templates`);
          const tmpl = r.ok ? await r.json() : [];
          return { id: p.id, name: p.name, templates: tmpl };
        }));
        setProfiles(withTemplates);
      })
      .catch(() => {});
  }, []);

  async function assignTemplate(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedTemplateId) return;
    setAssigning(true);
    const r = await fetch(`/api/agent/devices/${deviceId}/templates`, {
      method: 'POST',
      body: JSON.stringify({ template_id: Number(selectedTemplateId), enabled: true }),
    });
    setAssigning(false);
    if (r.ok) {
      setMsg('Template assigned ✓');
      setTimeout(() => setMsg(''), 4000);
    } else {
      const d = await r.json();
      setMsg(d.detail || 'Assignment failed');
    }
  }

  const allTemplates = profiles.flatMap(p =>
    p.templates.map(t => ({ id: t.id, label: `${p.name} / ${t.name}` }))
  );

  return (
    <div className={styles.templatePanel}>
      <div className={styles.templatePanelTitle}>Assign Template to Device</div>
      <p className={styles.templatePanelNote}>
        Assigned templates define which SNMP keys are collected from this device.
      </p>
      <form className={styles.assignForm} onSubmit={assignTemplate}>
        <select
          className={styles.assignSelect}
          value={selectedTemplateId}
          onChange={e => setSelectedTemplateId(e.target.value)}
          required
        >
          <option value="">Select a template…</option>
          {allTemplates.map(t => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
        <button type="submit" className={styles.assignBtn} disabled={assigning}>
          {assigning ? 'Assigning…' : 'Assign'}
        </button>
      </form>
      {msg && <div className={styles.assignMsg}>{msg}</div>}
    </div>
  );
}

// ── Events Panel (lazy-loaded) ────────────────────────────────────────────────
function EventsPanel({ deviceId }: { deviceId: string }) {
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/agent/devices/${deviceId}/events`).then(r => r.json()).then(data => {
      setEvents(data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [deviceId]);

  if (loading) return <div className={styles.loading}>Loading events…</div>;

  return (
    <div className={styles.eventsList}>
      {events.length === 0 ? (
        <div className={styles.emptyState}>No events recorded yet.</div>
      ) : events.map(ev => (
        <div key={ev.id} className={styles.eventRow}>
          <span className={styles.eventSev} data-sev={ev.severity}>●</span>
          <span className={styles.eventType}>{ev.event_type}</span>
          <span className={styles.eventMsg}>{ev.message}</span>
          <span className={styles.eventTime}>{timeAgo(ev.clock)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Full chart using SVG path ─────────────────────────────────────────────────
function FullChart({ points }: { points: HistoryPoint[] }) {
  const W = 600, H = 120, PAD = 20;
  const values = points.map(p => Number(p.value));
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;

  const pts = points.map((p, i) => {
    const x = PAD + (i / (points.length - 1)) * (W - PAD * 2);
    const y = PAD + H - ((Number(p.value) - minV) / range) * H;
    return `${x},${y}`;
  });

  const areaPath = `M ${pts[0]} L ${pts.join(' L ')} L ${PAD + (W - PAD * 2)},${PAD + H} L ${PAD},${PAD + H} Z`;
  const linePath = `M ${pts.join(' L ')}`;

  const lastVal = values[values.length - 1];

  return (
    <div className={styles.chartWrapper}>
      <div className={styles.chartStats}>
        <span>Min: {minV.toFixed(2)}</span>
        <span>Avg: {(values.reduce((a, b) => a + b, 0) / values.length).toFixed(2)}</span>
        <span>Max: {maxV.toFixed(2)}</span>
        <span className={styles.chartLast}>Now: {lastVal.toFixed(2)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H + PAD * 2}`} className={styles.chart} preserveAspectRatio="none">
        <defs>
          <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7b8cff" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#7b8cff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#chartGrad)" />
        <path d={linePath} fill="none" stroke="#7b8cff" strokeWidth="2" />
        {/* Last point dot */}
        <circle
          cx={PAD + (W - PAD * 2)}
          cy={PAD + H - ((lastVal - minV) / range) * H}
          r="4" fill="#7b8cff"
        />
      </svg>
    </div>
  );
}
