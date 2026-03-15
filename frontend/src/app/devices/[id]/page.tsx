'use client';
export const dynamic = 'force-dynamic';
import { useParams, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState, useCallback, useRef } from 'react';
import { getDevice, type DeviceDetail } from '@/lib/api';
import styles from './page.module.css';

// ── Types ─────────────────────────────────────────────────────────────────────
interface MetricsSnapshot {
  recorded_at: string;
  cpu_pct: number | null;
  ram_used_gb: number | null;
  ram_total_gb: number | null;
  disk_used_gb: number | null;
  disk_total_gb: number | null;
  uptime_seconds: number | null;
  logical_disks: Array<{
    name: string;
    volume_name: string;
    file_system: string;
    drive_type: string;
    size_gb: number | null;
    free_gb: number | null;
    used_gb: number | null;
  }>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatUptime(sec: number | null) {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function pct(used: number | null, total: number | null): number {
  if (!used || !total || total === 0) return 0;
  return Math.round((used / total) * 100);
}

function gaugeColor(p: number): string {
  if (p < 60) return '#22c55e';
  if (p < 80) return '#f59e0b';
  return '#ef4444';
}

function formatGb(value: number | null | undefined) {
  return value == null ? '—' : `${value.toFixed(2)} GB`;
}

// ── Gauge Component ───────────────────────────────────────────────────────────
function Gauge({ label, value, unit, used, total, colorByPct = true }: {
  label: string;
  value: number;      // 0–100
  unit?: string;
  used?: number | null;
  total?: number | null;
  colorByPct?: boolean;
}) {
  const color = colorByPct ? gaugeColor(value) : '#4a7cff';
  const subtitle = (used != null && total != null)
    ? `${used.toFixed(1)} / ${total.toFixed(1)} ${unit ?? 'GB'}`
    : `${value}${unit ?? '%'}`;

  return (
    <div className={styles.gauge}>
      <div className={styles.gaugeLabel}>{label}</div>
      <div className={styles.gaugeArc}>
        <svg viewBox="0 0 100 60" className={styles.gaugeSvg}>
          {/* background track */}
          <path d="M 10 55 A 40 40 0 0 1 90 55" fill="none" stroke="#2a2d3a" strokeWidth="10" strokeLinecap="round"/>
          {/* filled arc */}
          <path
            d="M 10 55 A 40 40 0 0 1 90 55"
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${(value / 100) * 125.6} 125.6`}
          />
        </svg>
        <div className={styles.gaugeCenter}>
          <span className={styles.gaugeValue} style={{ color }}>{value}<span className={styles.gaugeUnit}>%</span></span>
        </div>
      </div>
      <div className={styles.gaugeSub}>{subtitle}</div>
    </div>
  );
}

const SECTION_ICONS: Record<string, string> = {
  'Device Summary':  '🖥️',
  'Hardware Summary': '⚙️',
  'Network Summary': '🌐',
  'MDM Info':        '🔒',
  'Physical Disks':  '💽',
  'Logical Disks':   '🗂️',
  'Monitor Summary': '🖱️',
};

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DeviceDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params.id as string;
  const customer = searchParams.get('customer') || 'default';

  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch(`/api/mdm/mdm/windows/metrics?device_id=${id}`);
      if (res.ok) {
        const data = await res.json();
        if (data.latest) setMetrics(data.latest);
      }
    } catch { /* metrics optional */ }
  }, [id]);

  const loadDevice = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dev] = await Promise.all([
        getDevice(id),
        fetchMetrics(),
      ]);
      setDevice(dev);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load device');
    } finally {
      setLoading(false);
    }
  }, [id, fetchMetrics]);

  useEffect(() => {
    void loadDevice();
  }, [loadDevice]);

  // ── Rename state with live status polling ─────────────────────────────────
  const [renameOpen, setRenameOpen]       = useState(false);
  const [renameValue, setRenameValue]     = useState('');
  const [renameRestart, setRenameRestart] = useState(true);
  const [renaming, setRenaming]           = useState(false);
  const [cmdStatus, setCmdStatus]         = useState<null | {
    phase: 'queued' | 'pending' | 'sent' | 'acked' | 'failed' | 'timeout';
    commandId: string;
    result?: string | null;
    newName: string;
  }>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPolling = useCallback((commandId: string, newName: string) => {
    const startedAt = Date.now();
    pollRef.current = setInterval(async () => {
      if (Date.now() - startedAt > 3 * 60 * 1000) {
        stopPolling();
        setCmdStatus(s => s ? { ...s, phase: 'timeout' } : null);
        return;
      }
      try {
        const r = await fetch(`/api/mdm/mdm/windows/portal/commands/${commandId}`);
        if (!r.ok) return;
        const d = await r.json();
        const phase = d.status as 'pending' | 'sent' | 'acked' | 'failed';
        setCmdStatus({ phase, commandId, result: d.result, newName });
        if (phase === 'acked' || phase === 'failed') stopPolling();
      } catch { /* keep polling */ }
    }, 5000);
  }, [stopPolling]);

  const handleRename = async () => {
    if (!renameValue.trim() || !device) return;
    setRenaming(true);
    setCmdStatus(null);
    stopPolling();
    try {
      const res = await fetch('/api/mdm/mdm/windows/portal/commands/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: device.id, new_name: renameValue.trim(), restart_after: renameRestart }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      const nm = data.new_name as string;
      const cid = data.command_id as string;
      setCmdStatus({ phase: 'queued', commandId: cid, newName: nm });
      setRenameValue('');
      startPolling(cid, nm);
    } catch (e: unknown) {
      setCmdStatus({ phase: 'failed', commandId: '', newName: renameValue, result: e instanceof Error ? e.message : 'Error' });
    } finally {
      setRenaming(false);
    }
  };

  useEffect(() => () => stopPolling(), [stopPolling]);

  if (error || !device) {
    return (
      <div className={styles.notFound}>
        <h2>{error || 'Device not found'}</h2>
        <Link href={`/enrollment?customer=${customer}`} className={styles.backLink}>← Back to Enrollment</Link>
      </div>
    );
  }

  const summarySec: Record<string, string> = {
    'Device Name':         device.device_name,
    'Device Type':         device.device_type,
    'Device Model':        device.model,
    'Device Manufacturer': device.manufacturer,
    'Serial Number':       device.serial_number || '—',
    'UDID':                device.udid || '—',
    'Shared Device':       device.shared_device ? 'Yes' : 'No',
    'OS':                  device.os_version,
    'Architecture':        device.architecture,
  };

  const networkSec: Record<string, string> = device.network ? {
    'IP Address':      device.network.ip_address || '—',
    'MAC Address':     device.network.mac_address || '—',
    'Hostname':        device.network.hostname || '—',
    'Wi-Fi SSID':      device.network.wifi_ssid || '—',
    'Connection Type': device.network.connection_type || '—',
    'DNS Server':      device.network.dns_server || '—',
    'Default Gateway': device.network.default_gateway || '—',
    'Last Check-in':   device.last_checkin ? new Date(device.last_checkin).toLocaleString() : '—',
  } : { 'Network Info': 'No network data available' };

  const hardwareSec: Record<string, string> = device.hardware_inventory ? {
    'Processor Model': device.hardware_inventory.processor_model || '—',
    'Processor Vendor': device.hardware_inventory.processor_vendor || '—',
    'Physical Cores': device.hardware_inventory.physical_cores != null ? String(device.hardware_inventory.physical_cores) : '—',
    'Logical Processors': device.hardware_inventory.logical_processors != null ? String(device.hardware_inventory.logical_processors) : '—',
    'Memory Total': formatGb(device.hardware_inventory.memory_total_gb),
    'Memory Slots': device.hardware_inventory.memory_slot_count != null ? String(device.hardware_inventory.memory_slot_count) : '—',
    'Memory Slots Used': device.hardware_inventory.memory_slots_used != null ? String(device.hardware_inventory.memory_slots_used) : '—',
    'Memory Modules': device.hardware_inventory.memory_module_count != null ? String(device.hardware_inventory.memory_module_count) : '—',
    'Machine Class': device.hardware_inventory.machine_class || '—',
    'Chassis Type': device.hardware_inventory.chassis_type || '—',
  } : { 'Hardware Info': 'No hardware inventory data available' };

  const mdmSec: Record<string, string> = {
    'Enrollment Method': device.enrollment_method,
    'Enrolled Time':     device.enrolled_at ? new Date(device.enrolled_at).toLocaleString() : '—',
    'MDM Status':        device.status,
    'Agent Version':     device.agent_version || '—',
    'Customer':          device.customer_name || customer,
  };

  const monitorSections = device.monitors.length === 0
    ? [{ title: 'Monitor Summary', data: { 'Monitor Info': 'No monitor data available' } }]
    : device.monitors.length === 1
      ? [{ title: 'Monitor Summary', data: {
          'Model':         device.monitors[0].model || '—',
          'Serial Number': device.monitors[0].serial_number || '—',
          'Resolution':    device.monitors[0].resolution || '—',
          'Refresh Rate':  device.monitors[0].refresh_rate || '—',
          'HDR Support':   device.monitors[0].hdr_support ? 'Yes' : 'No',
        }}]
      : [{ title: 'Monitor Summary', data: {
          'Number of Displays': String(device.monitors.length),
          ...Object.fromEntries(device.monitors.flatMap((m) => [
            [`Monitor ${m.display_index} — Model`,      m.model || '—'],
            [`Monitor ${m.display_index} — Resolution`, m.resolution || '—'],
            [`Monitor ${m.display_index} — HDR`,        m.hdr_support ? 'Yes' : 'No'],
          ]))
        }}];

  const physicalDiskSections = device.physical_disks.length === 0
    ? [{ title: 'Physical Disks', data: { 'Physical Disks': 'No physical disk data available' } }]
    : [{
        title: 'Physical Disks',
        data: {
          'Disk Count': String(device.physical_disks.length),
          ...Object.fromEntries(device.physical_disks.flatMap((disk, idx) => [
            [`Disk ${idx + 1} — Model`, disk.model || '—'],
            [`Disk ${idx + 1} — Size`, formatGb(disk.size_gb)],
            [`Disk ${idx + 1} — Media Type`, disk.media_type || '—'],
            [`Disk ${idx + 1} — Interface`, disk.interface_type || '—'],
          ])),
        },
      }];

  const logicalDiskSections = device.logical_disks.length === 0
    ? [{ title: 'Logical Disks', data: { 'Logical Disks': 'No logical disk data available' } }]
    : [{
        title: 'Logical Disks',
        data: {
          'Logical Disk Count': String(device.logical_disks.length),
          ...Object.fromEntries(device.logical_disks.flatMap((disk) => [
            [`${disk.name} — Volume`, disk.volume_name || '—'],
            [`${disk.name} — File System`, disk.file_system || '—'],
            [`${disk.name} — Drive Type`, disk.drive_type || '—'],
            [`${disk.name} — Size`, formatGb(disk.size_gb)],
            [`${disk.name} — Free`, formatGb(disk.free_gb)],
            [`${disk.name} — Used`, formatGb(disk.used_gb)],
          ])),
        },
      }];

  const sections = [
    { title: 'Device Summary',  data: summarySec },
    { title: 'Hardware Summary', data: hardwareSec },
    { title: 'Network Summary', data: networkSec },
    { title: 'MDM Info',        data: mdmSec },
    ...physicalDiskSections,
    ...logicalDiskSections,
    ...monitorSections,
  ];

  const statusClass =
    device.status === 'Enrolled'      ? styles.badgeGreen  :
    device.status === 'Pending'       ? styles.badgeOrange :
    device.status === 'Deprovisioned' ? styles.badgeRed    : styles.badgeRed;

  const cpuPct   = metrics?.cpu_pct    ?? null;
  const ramPct   = pct(metrics?.ram_used_gb ?? null, metrics?.ram_total_gb ?? null);
  const diskPct  = pct(metrics?.disk_used_gb ?? null, metrics?.disk_total_gb ?? null);
  const hasMetrics = metrics !== null;

  return (
    <div className={styles.page}>
      {/* ── Header ── */}
      <div className={styles.header}>
        <Link href={`/enrollment?customer=${customer}`} className={styles.backBtn}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
            <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
          </svg>
          Back to Enrollment
        </Link>
        <div className={styles.titleRow}>
          <div className={styles.deviceIcon}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="#4a7cff">
              <path d="M20 3H4v10c0 2.21 1.79 4 4 4h6c2.21 0 4-1.79 4-4v-3h2c1.11 0 2-.89 2-2V5c0-1.11-.89-2-2-2zm0 5h-2V5h2v3z"/>
            </svg>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h1 className={styles.pageTitle}>{device.device_name}</h1>
              <button
                title="Rename computer"
                onClick={() => { setRenameOpen(true); setCmdStatus(null); stopPolling(); setRenameValue(''); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '2px 4px', borderRadius: 4, display: 'flex', alignItems: 'center' }}
              >
                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                  <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 5.63l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83a1 1 0 000-1.41z"/>
                </svg>
              </button>
            </div>
            <div className={styles.metaRow}>
              <span className={styles.metaText}>{device.model}</span>
              <span className={styles.metaDot}>·</span>
              <span className={styles.metaText}>{device.os_version}</span>
              <span className={styles.metaDot}>·</span>
              <span className={`${styles.badge} ${statusClass}`}>{device.status}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Rename Modal ── */}
      {renameOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={(e) => e.target === e.currentTarget && setRenameOpen(false)}>
          <div style={{ background: '#1a1d2e', border: '1px solid #2a2d3a', borderRadius: 12, padding: 28, width: 400, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
            <h3 style={{ margin: '0 0 6px', color: '#f1f5f9', fontSize: 16 }}>🖊️ Rename Computer</h3>
            <p style={{ margin: '0 0 20px', color: '#94a3b8', fontSize: 13 }}>Current name: <strong style={{ color: '#cbd5e1' }}>{device.device_name}</strong></p>
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', color: '#94a3b8', fontSize: 12, marginBottom: 6 }}>New Computer Name <span style={{ color: '#ef4444' }}>*</span></label>
              <input
                type="text"
                maxLength={15}
                placeholder="e.g. OFFICE-PC-01"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value.replace(/[^a-zA-Z0-9-]/g, '').toUpperCase())}
                style={{ width: '100%', boxSizing: 'border-box', background: '#0f1117', border: '1px solid #2a2d3a', borderRadius: 6, color: '#f1f5f9', padding: '8px 12px', fontSize: 14, outline: 'none' }}
                autoFocus
              />
              <div style={{ color: '#64748b', fontSize: 11, marginTop: 4 }}>Max 15 chars, letters, digits, and hyphens only</div>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 20, color: '#94a3b8', fontSize: 13 }}>
              <input type="checkbox" checked={renameRestart} onChange={(e) => setRenameRestart(e.target.checked)} />
              Restart automatically after rename (recommended)
            </label>
            {/* Live status tracker */}
            {cmdStatus && (
              <div style={{ marginBottom: 16, borderRadius: 8, overflow: 'hidden', border: '1px solid #2a2d3a' }}>

                <div style={{ padding: '12px 14px' }}>
                  {/* Step 1: Queued */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 16 }}>📤</span>
                    <span style={{ fontSize: 13, color: '#cbd5e1' }}>Команда отправлена на сервер</span>
                    <span style={{ marginLeft: 'auto', fontSize: 12, color: '#22c55e' }}>✓</span>
                  </div>
                  {/* Step 2: Sent to agent */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 16 }}>
                      {cmdStatus.phase === 'sent' || cmdStatus.phase === 'acked' || cmdStatus.phase === 'failed' ? '📡' : '🔄'}
                    </span>
                    <span style={{ fontSize: 13, color: cmdStatus.phase === 'queued' || cmdStatus.phase === 'pending' ? '#64748b' : '#cbd5e1' }}>
                      {cmdStatus.phase === 'queued' || cmdStatus.phase === 'pending'
                        ? 'Ожидание получения агентом…'
                        : 'Агент получил команду'}
                    </span>
                    {(cmdStatus.phase === 'sent' || cmdStatus.phase === 'acked' || cmdStatus.phase === 'failed') && (
                      <span style={{ marginLeft: 'auto', fontSize: 12, color: '#22c55e' }}>✓</span>
                    )}
                    {(cmdStatus.phase === 'queued' || cmdStatus.phase === 'pending') && (
                      <span style={{ marginLeft: 'auto', fontSize: 11, color: '#f59e0b', animation: 'pulse 1.5s infinite' }}>⏳</span>
                    )}
                  </div>
                  {/* Step 3: Executed */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 16 }}>
                      {cmdStatus.phase === 'acked' ? '✅' : cmdStatus.phase === 'failed' ? '❌' : cmdStatus.phase === 'timeout' ? '⏱️' : '⚙️'}
                    </span>
                    <span style={{ fontSize: 13, color: cmdStatus.phase === 'acked' ? '#22c55e' : cmdStatus.phase === 'failed' ? '#ef4444' : '#64748b' }}>
                      {cmdStatus.phase === 'acked'
                        ? `Выполнено: переименован в «${cmdStatus.newName}»`
                        : cmdStatus.phase === 'failed'
                        ? `Ошибка: ${cmdStatus.result || 'unknown error'}`
                        : cmdStatus.phase === 'timeout'
                        ? 'Нет ответа (агент недоступен или не v1.0.3)'
                        : 'Ожидание выполнения…'}
                    </span>
                    {(cmdStatus.phase === 'sent' || cmdStatus.phase === 'queued' || cmdStatus.phase === 'pending') && (
                      <span style={{ marginLeft: 'auto', fontSize: 11, color: '#94a3b8' }}>⏳</span>
                    )}
                  </div>
                  {/* Result detail */}
                  {cmdStatus.phase === 'acked' && cmdStatus.result && (
                    <div style={{ marginTop: 8, fontSize: 11, color: '#64748b', borderTop: '1px solid #2a2d3a', paddingTop: 8 }}>
                      {cmdStatus.result}
                    </div>
                  )}
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button onClick={() => { setRenameOpen(false); stopPolling(); setCmdStatus(null); }}
                style={{ background: 'none', border: '1px solid #2a2d3a', borderRadius: 6, color: '#94a3b8', padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                {cmdStatus?.phase === 'acked' ? 'Закрыть' : 'Отмена'}
              </button>
              <button
                onClick={handleRename}
                disabled={renaming || !renameValue.trim() || !!cmdStatus}
                style={{ background: '#4a7cff', border: 'none', borderRadius: 6, color: '#fff', padding: '7px 18px', cursor: 'pointer', fontSize: 13, opacity: (renaming || !renameValue.trim() || !!cmdStatus) ? 0.5 : 1 }}>
                {renaming ? 'Отправка…' : 'Переименовать'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Telemetry Gauges ── */}
      <div className={styles.telemetryCard}>
        <div className={styles.telemetryHeader}>
          <span className={styles.cardIcon}>📊</span>
          <h2 className={styles.cardTitle}>Live Telemetry</h2>
          {hasMetrics && (
            <span className={styles.telemetryTs}>
              Updated {new Date(metrics!.recorded_at).toLocaleTimeString()}
            </span>
          )}
        </div>
        {hasMetrics ? (
          <>
            <div className={styles.gauges}>
              <Gauge
                label="CPU"
                value={Math.round(cpuPct ?? 0)}
                unit="%"
              />
              <Gauge
                label="RAM"
                value={ramPct}
                used={metrics?.ram_used_gb}
                total={metrics?.ram_total_gb}
                unit="GB"
              />
              <Gauge
                label="Disk C:"
                value={diskPct}
                used={metrics?.disk_used_gb}
                total={metrics?.disk_total_gb}
                unit="GB"
              />
              <div className={styles.uptimeCard}>
                <div className={styles.uptimeIcon}>⏱</div>
                <div className={styles.uptimeLabel}>Uptime</div>
                <div className={styles.uptimeValue}>{formatUptime(metrics?.uptime_seconds ?? null)}</div>
              </div>
            </div>
            {metrics.logical_disks.length > 0 && (
              <div className={styles.card} style={{ marginTop: 16 }}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardIcon}>💾</span>
                  <h2 className={styles.cardTitle}>Disk Telemetry</h2>
                </div>
                <dl className={styles.dl}>
                  {metrics.logical_disks.flatMap((disk) => ([
                    <div key={`${disk.name}-used`} className={styles.dlRow}>
                      <dt className={styles.dt}>{disk.name} Used</dt>
                      <dd className={styles.dd}>{formatGb(disk.used_gb)}</dd>
                    </div>,
                    <div key={`${disk.name}-free`} className={styles.dlRow}>
                      <dt className={styles.dt}>{disk.name} Free</dt>
                      <dd className={styles.dd}>{formatGb(disk.free_gb)}</dd>
                    </div>,
                    <div key={`${disk.name}-total`} className={styles.dlRow}>
                      <dt className={styles.dt}>{disk.name} Total</dt>
                      <dd className={styles.dd}>{formatGb(disk.size_gb)}</dd>
                    </div>,
                  ]))}
                </dl>
              </div>
            )}
          </>
        ) : (
          <div className={styles.noMetrics}>
            <span>📡</span>
            <p>No telemetry data yet.<br/>Metrics will appear after the next agent check-in (every 15 min).</p>
          </div>
        )}
      </div>

      {/* ── Info Sections ── */}
      <div className={styles.sections}>
        {sections.map(({ title, data }) => (
          <div key={title} className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardIcon}>{SECTION_ICONS[title] ?? '📋'}</span>
              <h2 className={styles.cardTitle}>{title}</h2>
            </div>
            <dl className={styles.dl}>
              {Object.entries(data).map(([k, v]) => (
                <div key={k} className={styles.dlRow}>
                  <dt className={styles.dt}>{k}</dt>
                  <dd className={`${styles.dd} ${k === 'UDID' || k.includes('Serial') ? styles.mono : ''}`}>
                    {k === 'MDM Status' ? (
                      <span className={`${styles.badge} ${statusClass}`}>{v}</span>
                    ) : v}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}
