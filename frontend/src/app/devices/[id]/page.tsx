'use client';
export const dynamic = 'force-dynamic';
import { useParams, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { getDevice, type DeviceDetail } from '@/lib/api';
import styles from './page.module.css';
import dynamicImport from 'next/dynamic';

const PtyTerminal = dynamicImport(() => import('@/components/PtyTerminal/PtyTerminal'), { ssr: false });

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

function formatStorage(valueGb: number | null | undefined) {
  if (valueGb == null) return '—';
  const abs = Math.abs(valueGb);
  if (abs >= 1024) return `${(valueGb / 1024).toFixed(2)} TB`;
  if (abs >= 1) return `${valueGb.toFixed(2)} GB`;
  return `${Math.round(valueGb * 1024)} MB`;
}

function formatEnrollmentMethod(platform: string | null | undefined, agentVersion: string | null | undefined) {
  const platformLabel = (platform || '').trim() || 'Windows';
  const versionLabel = (agentVersion || '').trim();
  return versionLabel ? `${platformLabel} Agent ${versionLabel}` : `${platformLabel} Agent`;
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
    ? `${formatStorage(used)} / ${formatStorage(total)}`
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
  'User Profiles':   '👥',
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
  const [softSearch, setSoftSearch] = useState('');

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

  // Silent background refresh — does NOT set loading=true so modals stay visible
  const refreshDeviceSilent = useCallback(async () => {
    try {
      const dev = await getDevice(id);
      setDevice(dev);
    } catch { /* ignore background errors */ }
  }, [id]);

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
        if (phase === 'acked') {
          stopPolling();
          // Re-fetch device so the name in the header reflects the new value from the server
          void loadDevice();
        } else if (phase === 'failed') {
          stopPolling();
        }
      } catch { /* keep polling */ }
    }, 5000);
  }, [stopPolling, loadDevice]);

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
      setRenameOpen(false); // close modal immediately
      startPolling(cid, nm);
    } catch (e: unknown) {
      const errMsg = e instanceof Error ? e.message : 'Error';
      setCmdStatus({ phase: 'failed', commandId: '', newName: renameValue, result: errMsg });
      setRenameOpen(false); // close modal even on error — show error inline
    } finally {
      setRenaming(false);
    }
  };

  // ── Update Agent state ─────────────────────────────────────────────────────
  const [updateOpen, setUpdateOpen]           = useState(false);
  const [updating, setUpdating]               = useState(false);
  const [latestAgentVersion, setLatestAgentVersion] = useState<string | null>(null);
  const [updateStatus, setUpdateStatus]       = useState<null | {
    phase: 'queued' | 'pending' | 'sent' | 'acked' | 'verifying' | 'updated' | 'failed' | 'timeout';
    commandId: string;
    result?: string | null;
    targetVersion: string;
  }>(null);
  const updatePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopUpdatePolling = useCallback(() => {
    if (updatePollRef.current) { clearInterval(updatePollRef.current); updatePollRef.current = null; }
  }, []);

  // Detect when agent version matches the targeted update version → mark as 'updated'
  useEffect(() => {
    if (!device || !updateStatus) return;
    if (updateStatus.phase === 'verifying' && device.agent_version === updateStatus.targetVersion) {
      stopUpdatePolling();
      setUpdateStatus(s => s ? { ...s, phase: 'updated' } : null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device?.agent_version, updateStatus?.phase]);

  const startUpdatePolling = useCallback((commandId: string, targetVersion: string) => {
    const startedAt = Date.now();
    updatePollRef.current = setInterval(async () => {
      if (Date.now() - startedAt > 5 * 60 * 1000) {
        stopUpdatePolling();
        setUpdateStatus(s => s ? { ...s, phase: 'timeout' } : null);
        return;
      }
      try {
        const r = await fetch(`/api/mdm/mdm/windows/portal/commands/${commandId}`);
        if (!r.ok) return;
        const d = await r.json();
        const phase = d.status as 'pending' | 'sent' | 'acked' | 'failed';
        setUpdateStatus({ phase, commandId, result: d.result, targetVersion });
        if (phase === 'failed') { stopUpdatePolling(); return; }
        if (phase === 'acked') {
          // Switch to version-verification polling — calls loadDevice every 10s
          stopUpdatePolling();
          setUpdateStatus({ phase: 'verifying', commandId, result: null, targetVersion });
          const verifyStart = Date.now();
          updatePollRef.current = setInterval(() => {
            if (Date.now() - verifyStart > 3 * 60 * 1000) {
              stopUpdatePolling();
              setUpdateStatus(s => s ? { ...s, phase: 'timeout' } : null);
              return;
            }
            void refreshDeviceSilent();  // silent poll — no loading spinner, modal stays visible
          }, 10000);
        }
      } catch { /* keep polling */ }
    }, 5000);
  }, [stopUpdatePolling, loadDevice, refreshDeviceSilent]);


  const handleUpdateAgent = async () => {
    if (!device) return;
    setUpdating(true);
    setUpdateStatus(null);
    stopUpdatePolling();
    try {
      const res = await fetch('/api/mdm/mdm/windows/portal/commands/update-agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: device.id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      const cid = data.command_id as string;
      const tv  = data.target_version as string;
      setLatestAgentVersion(tv); // confirm actual version sent
      setUpdateStatus({ phase: 'queued', commandId: cid, targetVersion: tv });
      startUpdatePolling(cid, tv);
    } catch (e: unknown) {
      setUpdateStatus({ phase: 'failed', commandId: '', targetVersion: '', result: e instanceof Error ? e.message : 'Error' });
    } finally {
      setUpdating(false);
    }
  };

  const openUpdateModal = async () => {
    setLatestAgentVersion(null);
    setUpdateOpen(true);
    try {
      const r = await fetch('/api/mdm/mdm/windows/portal/latest-version');
      if (r.ok) {
        const d = await r.json();
        setLatestAgentVersion(d.version || null);
      }
    } catch { /* non-fatal */ }
  };

  // ── Restart Agent state ───────────────────────────────────────────────────
  const [restartOpen, setRestartOpen]       = useState(false);
  const [restarting, setRestarting]         = useState(false);
  const [restartStatus, setRestartStatus]   = useState<null | {
    phase: 'queued' | 'pending' | 'sent' | 'acked' | 'failed' | 'timeout';
    commandId: string;
    result?: string | null;
  }>(null);
  const restartPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopRestartPolling = useCallback(() => {
    if (restartPollRef.current) { clearInterval(restartPollRef.current); restartPollRef.current = null; }
  }, []);

  const startRestartPolling = useCallback((commandId: string) => {
    const startedAt = Date.now();
    restartPollRef.current = setInterval(async () => {
      if (Date.now() - startedAt > 2 * 60 * 1000) {
        stopRestartPolling();
        setRestartStatus(s => s ? { ...s, phase: 'timeout' } : null);
        return;
      }
      try {
        const r = await fetch(`/api/mdm/mdm/windows/portal/commands/${commandId}`);
        if (!r.ok) return;
        const d = await r.json();
        const phase = d.status as 'pending' | 'sent' | 'acked' | 'failed';
        setRestartStatus({ phase, commandId, result: d.result });
        if (phase === 'acked') {
          stopRestartPolling();
          void loadDevice(); // refresh device info after restart
        } else if (phase === 'failed') {
          stopRestartPolling();
        }
      } catch { /* keep polling */ }
    }, 5000);
  }, [stopRestartPolling, loadDevice]);

  const handleRestartAgent = async () => {
    if (!device) return;
    setRestarting(true);
    setRestartStatus(null);
    stopRestartPolling();
    try {
      const res = await fetch('/api/mdm/mdm/windows/portal/commands/restart-agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: device.id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      const cid = data.command_id as string;
      setRestartStatus({ phase: 'queued', commandId: cid });
      startRestartPolling(cid);
    } catch (e: unknown) {
      setRestartStatus({ phase: 'failed', commandId: '', result: e instanceof Error ? e.message : 'Error' });
    } finally {
      setRestarting(false);
    }
  };

  // ── Actions dropdown ──────────────────────────────────────────────────────
  const [actionsOpen, setActionsOpen] = useState(false);
  const actionsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!actionsOpen) return;
    const handler = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node)) setActionsOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [actionsOpen]);

  useEffect(() => () => { stopPolling(); stopUpdatePolling(); stopRestartPolling(); }, [stopPolling, stopUpdatePolling, stopRestartPolling]);

  // ── Terminal state ────────────────────────────────────────────────────────
  const [authToken, setAuthToken] = useState<string | null>(null);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch('/api/auth/token').then(r => r.ok ? r.json() : null).then(d => {
      if (d?.token) setAuthToken(d.token);
    }).catch(() => {});
  }, []);

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
    'Memory Total': formatStorage(device.hardware_inventory.memory_total_gb),
    'Memory Slots': device.hardware_inventory.memory_slot_count != null ? String(device.hardware_inventory.memory_slot_count) : '—',
    'Memory Slots Used': device.hardware_inventory.memory_slots_used != null ? String(device.hardware_inventory.memory_slots_used) : '—',
    'Memory Modules': device.hardware_inventory.memory_module_count != null ? String(device.hardware_inventory.memory_module_count) : '—',
    'Machine Class': device.hardware_inventory.machine_class || '—',
    'Chassis Type': device.hardware_inventory.chassis_type || '—',
    ...(device.hardware_inventory.gpu_model ? {
      'GPU Model': device.hardware_inventory.gpu_model,
      'GPU Manufacturer': device.hardware_inventory.gpu_manufacturer || '—',
      'GPU VRAM': formatStorage(device.hardware_inventory.gpu_vram_gb),
      'GPU Driver': device.hardware_inventory.gpu_driver_version || '—',
    } : {}),
  } : { 'Hardware Info': 'No hardware inventory data available' };

  const mdmSec: Record<string, string> = {
    'Enrollment Method': formatEnrollmentMethod(device.platform, device.agent_version),
    'Enrolled Time':     device.enrolled_at ? new Date(device.enrolled_at).toLocaleString() : '—',
    'MDM Status':        device.status,
    'Agent Version':     device.agent_version || '—',
    'AnyDesk ID':        device.anydesk_id || '—',
    'Customer':          device.customer_name || customer,
  };

  const monitorSections = device.monitors.length === 0
    ? [{ title: 'Monitor Summary', data: { 'Monitor Info': 'No monitor data available' } }]
    : [{ title: 'Monitor Summary', data: {
        'Number of Displays': String(device.monitors.length),
        ...Object.fromEntries(device.monitors.flatMap((m) => [
          [`Monitor ${m.display_index} — Manufacturer`, (m as any).manufacturer || '—'],
          [`Monitor ${m.display_index} — Model`,         m.model || '—'],
          [`Monitor ${m.display_index} — Serial Number`, m.serial_number || '—'],
          [`Monitor ${m.display_index} — Size`,          m.display_size || '—'],
          [`Monitor ${m.display_index} — Resolution`,    m.resolution || '—'],
          [`Monitor ${m.display_index} — Connection`,    m.connection_type || '—'],
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
            [`Disk ${idx + 1} — Size`, formatStorage(disk.size_gb)],
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
            [`${disk.name} — Size`, formatStorage(disk.size_gb)],
            [`${disk.name} — Free`, formatStorage(disk.free_gb)],
            [`${disk.name} — Used`, formatStorage(disk.used_gb)],
          ])),
        },
      }];

  const printerSections = !device.printers?.length
    ? [{ title: 'Printers', data: { 'Printers': 'No printers found' } }]
    : [{
        title: 'Printers',
        data: {
          'Printer Count': String(device.printers.length),
          ...Object.fromEntries(device.printers.flatMap((p) => [
            [`${p.name} — Driver`, p.driver_name || '—'],
            [`${p.name} — Port`, p.port_name || '—'],
            [`${p.name} — Type`, p.is_network ? 'Network' : 'Local'],
            [`${p.name} — Connection`, p.connection_type || '—'],
            [`${p.name} — IP`, p.ip_address || '—'],
            [`${p.name} — Shared`, p.is_shared ? 'Yes' : 'No'],
            [`${p.name} — Offline`, p.work_offline ? 'Yes' : 'No'],
            [`${p.name} — Jobs`, p.job_count != null ? String(p.job_count) : '—'],
            [`${p.name} — Status`, (p.is_default ? '★ Default  ' : '') + (p.status || '—')],
          ])),
        },
      }];

  const profileSections = !device.user_profiles?.length
    ? [{ title: 'User Profiles', data: { 'User Profiles': 'No profile data available' } }]
    : [{
        title: 'User Profiles',
        data: {
          'Count': String(device.user_profiles.length),
          ...Object.fromEntries(device.user_profiles.flatMap((p) => [
            [`Profile — ${p.username}`, p.sid || '—'],
            [`${p.username} Path`, p.local_path || '—'],
            [`${p.username} Loaded`, p.loaded ? 'Yes' : 'No'],
            [`${p.username} Last Use`, p.last_use_time ? new Date(p.last_use_time).toLocaleString() : '—'],
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
    ...printerSections,
    ...profileSections,
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <h1 className={styles.pageTitle}>{device.device_name}</h1>

              {/* ── Inline rename status chip ── */}
              {cmdStatus && (() => {
                const phase = cmdStatus.phase;
                if (phase === 'queued' || phase === 'pending' || phase === 'sent') return (
                  <span title={`Renaming to "${cmdStatus.newName}"…`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#f59e0b', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 20, padding: '2px 10px', cursor: 'default' }}>
                    <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>⏳</span>
                    → {cmdStatus.newName}
                  </span>
                );
                if (phase === 'acked') return (
                  <span title="Rename complete" onClick={() => setCmdStatus(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#22c55e', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 20, padding: '2px 10px', cursor: 'pointer' }}>
                    ✅ Renamed
                  </span>
                );
                if (phase === 'failed' || phase === 'timeout') return (
                  <span title={cmdStatus.result || 'Error'} onClick={() => setCmdStatus(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 20, padding: '2px 10px', cursor: 'pointer' }}>
                    ❌ {phase === 'timeout' ? 'No response' : 'Error'}
                  </span>
                );
                return null;
              })()}

              {/* ── Restart status chip ── */}
              {restartStatus && (() => {
                const phase = restartStatus.phase;
                if (phase === 'queued' || phase === 'pending' || phase === 'sent') return (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#a78bfa', background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.3)', borderRadius: 20, padding: '2px 10px' }}>
                    <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>⏳</span>
                    Restarting agent…
                  </span>
                );
                if (phase === 'acked') return (
                  <span onClick={() => setRestartStatus(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#22c55e', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 20, padding: '2px 10px', cursor: 'pointer' }}>
                    ✅ Agent restarted
                  </span>
                );
                if (phase === 'failed' || phase === 'timeout') return (
                  <span title={restartStatus.result || 'Error'} onClick={() => setRestartStatus(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 20, padding: '2px 10px', cursor: 'pointer' }}>
                    ❌ Restart failed
                  </span>
                );
                return null;
              })()}

              {/* ── ⋯ Actions dropdown ── */}
              <div ref={actionsRef} style={{ position: 'relative', marginLeft: 4 }}>
                <button
                  onClick={() => setActionsOpen(o => !o)}
                  title="Device actions"
                  style={{ background: actionsOpen ? 'rgba(74,124,255,0.15)' : 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: '#94a3b8', padding: '4px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 2, fontSize: 18, lineHeight: 1, fontWeight: 700, letterSpacing: 1 }}
                >
                  ⋯
                </button>
                {actionsOpen && (
                  <div style={{ position: 'absolute', top: 'calc(100% + 6px)', right: 0, background: '#1a1d2e', border: '1px solid #2a2d3a', borderRadius: 10, boxShadow: '0 12px 40px rgba(0,0,0,0.5)', zIndex: 300, minWidth: 200, overflow: 'hidden' }}>
                    {/* Rename */}
                    <button
                      onClick={() => { setActionsOpen(false); setRenameOpen(true); setCmdStatus(null); stopPolling(); setRenameValue(''); }}
                      style={{ width: '100%', background: 'none', border: 'none', color: '#cbd5e1', padding: '11px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, textAlign: 'left' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(74,124,255,0.12)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                    >
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="#94a3b8"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 5.63l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83a1 1 0 000-1.41z"/></svg>
                      Rename Computer
                    </button>
                    <div style={{ height: 1, background: '#2a2d3a', margin: '0 12px' }} />
                    {/* Update Agent */}
                    <button
                      onClick={() => { setActionsOpen(false); setUpdateStatus(null); stopUpdatePolling(); openUpdateModal(); }}
                      style={{ width: '100%', background: 'none', border: 'none', color: '#cbd5e1', padding: '11px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, textAlign: 'left' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(74,124,255,0.12)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                    >
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="#f59e0b"><path d="M21 10.12h-6.78l2.74-2.82c-2.73-2.7-7.15-2.8-9.88-.1-2.73 2.71-2.73 7.08 0 9.79s7.15 2.71 9.88 0C18.32 15.65 19 14.08 19 12.1h2c0 1.98-.88 4.55-2.64 6.29-3.51 3.48-9.21 3.48-12.72 0-3.5-3.47-3.53-9.11-.02-12.58s9.14-3.47 12.65 0L21 3v7.12z"/></svg>
                      Update Agent
                    </button>
                    <div style={{ height: 1, background: '#2a2d3a', margin: '0 12px' }} />
                    {/* Restart Agent */}
                    <button
                      onClick={() => { setActionsOpen(false); setRestartOpen(true); setRestartStatus(null); stopRestartPolling(); }}
                      style={{ width: '100%', background: 'none', border: 'none', color: '#cbd5e1', padding: '11px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, textAlign: 'left' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(74,124,255,0.12)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                    >
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="#a78bfa"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                      Restart Agent
                    </button>
                    <div style={{ height: 1, background: '#2a2d3a', margin: '0 12px' }} />
                    {/* Terminal */}
                    <button
                      onClick={() => { setActionsOpen(false); terminalRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); terminalRef.current?.querySelector('input')?.focus(); }}
                      style={{ width: '100%', background: 'none', border: 'none', color: '#cbd5e1', padding: '11px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, textAlign: 'left' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(74,124,255,0.12)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                    >
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="#22c55e"><path d="M20 3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H4V5h16v14zM6 15l1.41 1.41L11 12.83V19h2v-6.17l3.59 3.58L18 15l-6-6-6 6z" style={{display:'none'}}/><path d="M20 3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H4V5h16v14zM6 11l1.41-1.41L9 11.17V8h2v3.17l1.59-1.59L14 11l-4 4-4-4z" style={{display:'none'}}/><path d="M7 15l1.41 1.41L11 13.83V19h2v-5.17l2.59 2.58L17 15l-5-5-5 5zm0-8h10v2H7z" style={{display:'none'}}/><path d="M20 3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H4V5h16v14zM6.41 15.59L8 17.17l6-6-6-6-1.41 1.42L11.17 11z"/></svg>
                      Terminal
                    </button>
                  </div>
                )}
              </div>
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

      {/* ── Update Agent Modal ── */}
      {updateOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={(e) => e.target === e.currentTarget && setUpdateOpen(false)}>
          <div style={{ background: '#1a1d2e', border: '1px solid #2a2d3a', borderRadius: 12, padding: 28, width: 420, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
            <h3 style={{ margin: '0 0 6px', color: '#f1f5f9', fontSize: 16 }}>🔄 Remote Agent Update</h3>
            <p style={{ margin: '0 0 20px', color: '#94a3b8', fontSize: 13 }}>
              Current version: <strong style={{ color: '#cbd5e1' }}>{device.agent_version || '—'}</strong><br/>
              {' → '}
              {latestAgentVersion === null
                ? <span style={{ color: '#64748b' }}>checking…</span>
                : <strong style={{ color: device.agent_version === latestAgentVersion ? '#94a3b8' : '#22c55e' }}>
                    {device.agent_version === latestAgentVersion ? `${latestAgentVersion} (already latest)` : latestAgentVersion}
                  </strong>
              }
              <br/>The agent will download and reinstall itself automatically.
            </p>
            {/* Live status tracker */}
            {updateStatus && (
              <div style={{ marginBottom: 16, borderRadius: 8, border: '1px solid #2a2d3a', padding: '12px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16 }}>📤</span>
                  <span style={{ fontSize: 13, color: '#cbd5e1' }}>Command sent to server</span>
                  <span style={{ marginLeft: 'auto', color: '#22c55e', fontSize: 12 }}>✓</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16 }}>
                    {['sent','acked','verifying','updated','failed'].includes(updateStatus.phase) ? '📡' : '🔄'}
                  </span>
                  <span style={{ fontSize: 13, color: ['queued','pending'].includes(updateStatus.phase) ? '#64748b' : '#cbd5e1' }}>
                    {['queued','pending'].includes(updateStatus.phase) ? 'Waiting for agent to pick up…' : 'Agent received command'}
                  </span>
                  {['sent','acked','verifying','updated','failed'].includes(updateStatus.phase) && <span style={{ marginLeft: 'auto', color: '#22c55e', fontSize: 12 }}>✓</span>}
                  {['queued','pending'].includes(updateStatus.phase) && <span style={{ marginLeft: 'auto', color: '#f59e0b', fontSize: 11 }}>⏳</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16 }}>
                    {['acked','verifying','updated'].includes(updateStatus.phase) ? '🔄' : updateStatus.phase === 'failed' ? '❌' : updateStatus.phase === 'timeout' ? '⏱️' : '⬇️'}
                  </span>
                  <span style={{ fontSize: 13, color: ['acked','verifying','updated'].includes(updateStatus.phase) ? '#22c55e' : updateStatus.phase === 'failed' ? '#ef4444' : '#64748b' }}>
                    {['acked','verifying','updated'].includes(updateStatus.phase)
                      ? `Installing v${updateStatus.targetVersion}… service restarting`
                      : updateStatus.phase === 'failed'
                      ? `Error: ${updateStatus.result || 'unknown error'}`
                      : updateStatus.phase === 'timeout'
                      ? 'No response from agent (may still be updating)'
                      : `Downloading v${updateStatus.targetVersion}…`}
                  </span>
                  {['acked','verifying','updated'].includes(updateStatus.phase) && <span style={{ marginLeft: 'auto', color: '#22c55e', fontSize: 12 }}>✓</span>}
                  {['queued','pending','sent'].includes(updateStatus.phase) && <span style={{ marginLeft: 'auto', fontSize: 11, color: '#94a3b8' }}>⏳</span>}
                </div>
                {/* Step 3: version confirmation */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 16 }}>
                    {updateStatus.phase === 'updated' ? '✅' : updateStatus.phase === 'timeout' ? '⏱️' : updateStatus.phase === 'failed' ? '❌' : '🔍'}
                  </span>
                  <span style={{ fontSize: 13, color: updateStatus.phase === 'updated' ? '#22c55e' : updateStatus.phase === 'timeout' ? '#f59e0b' : updateStatus.phase === 'failed' ? '#ef4444' : '#64748b' }}>
                    {updateStatus.phase === 'updated'
                      ? `✅ Updated to v${updateStatus.targetVersion} — agent is online!`
                      : updateStatus.phase === 'timeout'
                      ? `Agent may still be restarting. Refresh in a minute.`
                      : updateStatus.phase === 'failed'
                      ? `Update failed`
                      : `Waiting for agent to come back online…`}
                  </span>
                  {updateStatus.phase === 'verifying' && <span style={{ marginLeft: 'auto', color: '#f59e0b', fontSize: 11 }}>⏳</span>}
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              {!(['updated', 'failed', 'timeout'].includes(updateStatus?.phase || '')) && (
                <button onClick={() => { setUpdateOpen(false); stopUpdatePolling(); setUpdateStatus(null); }}
                  style={{ background: 'none', border: '1px solid #2a2d3a', borderRadius: 6, color: '#94a3b8', padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  Cancel
                </button>
              )}
              {['failed', 'timeout'].includes(updateStatus?.phase || '') ? (
                <button
                  onClick={() => { setUpdateStatus(null); stopUpdatePolling(); handleUpdateAgent(); }}
                  style={{ background: '#ef4444', border: 'none', borderRadius: 6, color: '#fff', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  🔄 Retry
                </button>
              ) : updateStatus?.phase === 'updated' ? (
                <button
                  onClick={() => { setUpdateOpen(false); stopUpdatePolling(); setUpdateStatus(null); }}
                  style={{ background: '#22c55e', border: 'none', borderRadius: 6, color: '#000', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  OK
                </button>
              ) : (
                <button
                  onClick={handleUpdateAgent}
                  disabled={updating || !!updateStatus}
                  style={{ background: '#f59e0b', border: 'none', borderRadius: 6, color: '#000', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13, opacity: (updating || !!updateStatus) ? 0.5 : 1 }}>
                  {updating ? 'Sending…' : '⬆️ Update Agent'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Restart Agent Modal ── */}
      {restartOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={(e) => e.target === e.currentTarget && setRestartOpen(false)}>
          <div style={{ background: '#1a1d2e', border: '1px solid #2a2d3a', borderRadius: 12, padding: 28, width: 420, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
            <h3 style={{ margin: '0 0 6px', color: '#f1f5f9', fontSize: 16 }}>🔁 Restart Agent</h3>
            <p style={{ margin: '0 0 20px', color: '#94a3b8', fontSize: 13 }}>
              The agent will push a fresh inventory snapshot, then restart itself.<br/>
              After restart, it will immediately re-send all device information to the portal.
            </p>
            {restartStatus && (
              <div style={{ marginBottom: 16, borderRadius: 8, border: '1px solid #2a2d3a', padding: '12px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16 }}>📤</span>
                  <span style={{ fontSize: 13, color: '#cbd5e1' }}>Command sent to server</span>
                  <span style={{ marginLeft: 'auto', color: '#22c55e', fontSize: 12 }}>✓</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16 }}>
                    {restartStatus.phase === 'sent' || restartStatus.phase === 'acked' || restartStatus.phase === 'failed' ? '📡' : '🔄'}
                  </span>
                  <span style={{ fontSize: 13, color: restartStatus.phase === 'queued' || restartStatus.phase === 'pending' ? '#64748b' : '#cbd5e1' }}>
                    {restartStatus.phase === 'queued' || restartStatus.phase === 'pending' ? 'Waiting for agent to pick up…' : 'Agent received command'}
                  </span>
                  {(restartStatus.phase === 'sent' || restartStatus.phase === 'acked' || restartStatus.phase === 'failed') && <span style={{ marginLeft: 'auto', color: '#22c55e', fontSize: 12 }}>✓</span>}
                  {(restartStatus.phase === 'queued' || restartStatus.phase === 'pending') && <span style={{ marginLeft: 'auto', color: '#f59e0b', fontSize: 11 }}>⏳</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 16 }}>
                    {restartStatus.phase === 'acked' ? '✅' : restartStatus.phase === 'failed' ? '❌' : restartStatus.phase === 'timeout' ? '⏱️' : '🔁'}
                  </span>
                  <span style={{ fontSize: 13, color: restartStatus.phase === 'acked' ? '#22c55e' : restartStatus.phase === 'failed' ? '#ef4444' : '#64748b' }}>
                    {restartStatus.phase === 'acked'
                      ? 'Agent restarted. Device info refreshed.'
                      : restartStatus.phase === 'failed'
                      ? `Error: ${restartStatus.result || 'unknown error'}`
                      : restartStatus.phase === 'timeout'
                      ? 'No response (agent offline or outdated)'
                      : 'Sending inventory snapshot, restarting…'}
                  </span>
                  {(restartStatus.phase === 'queued' || restartStatus.phase === 'pending' || restartStatus.phase === 'sent') && <span style={{ marginLeft: 'auto', fontSize: 11, color: '#94a3b8' }}>⏳</span>}
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              {!(['acked', 'failed', 'timeout'].includes(restartStatus?.phase || '')) && (
                <button onClick={() => { setRestartOpen(false); stopRestartPolling(); setRestartStatus(null); }}
                  style={{ background: 'none', border: '1px solid #2a2d3a', borderRadius: 6, color: '#94a3b8', padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  Cancel
                </button>
              )}
              {['failed', 'timeout'].includes(restartStatus?.phase || '') ? (
                <button
                  onClick={() => { setRestartStatus(null); stopRestartPolling(); handleRestartAgent(); }}
                  style={{ background: '#ef4444', border: 'none', borderRadius: 6, color: '#fff', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  🔄 Retry
                </button>
              ) : restartStatus?.phase === 'acked' ? (
                <button
                  onClick={() => { setRestartOpen(false); stopRestartPolling(); setRestartStatus(null); }}
                  style={{ background: '#22c55e', border: 'none', borderRadius: 6, color: '#000', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13 }}>
                  OK
                </button>
              ) : (
                <button
                  onClick={handleRestartAgent}
                  disabled={restarting || !!restartStatus}
                  style={{ background: '#a78bfa', border: 'none', borderRadius: 6, color: '#fff', fontWeight: 600, padding: '7px 18px', cursor: 'pointer', fontSize: 13, opacity: (restarting || !!restartStatus) ? 0.5 : 1 }}>
                  {restarting ? 'Sending…' : '🔁 Restart Agent'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

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

      {/* ── Hero strip ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {[
          { label: 'IP', value: device.ip_address || '—', color: '#89b4fa' },
          { label: 'Serial', value: device.serial_number || '—', color: '#cba6f7' },
          { label: 'Platform', value: device.platform || 'Windows', color: '#a6e3a1' },
          { label: 'Last Seen', value: device.last_seen ? new Date(device.last_seen).toLocaleString() : '—', color: '#f9e2af' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: '#13141c', border: '1px solid #1e2030', borderRadius: 8, padding: '7px 14px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, color: '#4a5568', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>{label}</span>
            <span style={{ fontSize: 12, color, fontFamily: label === 'IP' || label === 'Serial' ? 'monospace' : 'inherit', fontWeight: 500 }}>{value}</span>
          </div>
        ))}
      </div>

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
          </>
        ) : (
          <div className={styles.noMetrics}>
            <span>📡</span>
            <p>No telemetry data yet.<br/>Metrics will appear after the next agent check-in (every 15 min).</p>
          </div>
        )}
      </div>

      {/* ── Logical Disks Table ── */}
      {device.logical_disks.length > 0 && (
        <div className={styles.card} style={{ marginTop: 16 }}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIcon}>🗂️</span>
            <h2 className={styles.cardTitle}>Logical Disks</h2>
          </div>
          <div style={{ overflowX: 'auto', padding: '0 4px 12px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2d2d44' }}>
                  {['Device', 'Mount', 'FS', 'Size', 'Used', 'Free'].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: 'left', color: '#888', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {device.logical_disks.map((disk, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #1e1e2e' }}>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12, color: '#89b4fa', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={disk.name}>{disk.name}</td>
                    <td style={{ padding: '8px 12px', color: '#cdd6f4' }}>{disk.volume_name || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#a6e3a1' }}>{disk.file_system || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#cdd6f4', whiteSpace: 'nowrap' }}>{formatStorage(disk.size_gb)}</td>
                    <td style={{ padding: '8px 12px', color: '#f9e2af', whiteSpace: 'nowrap' }}>{formatStorage(disk.used_gb)}</td>
                    <td style={{ padding: '8px 12px', color: '#a6e3a1', whiteSpace: 'nowrap' }}>{formatStorage(disk.free_gb)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Printers ── */}
      {device.printers && device.printers.length > 0 && (
        <div className={styles.card} style={{ marginTop: 12 }}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIcon}>🖨️</span>
            <h2 className={styles.cardTitle}>Printers ({device.printers.length})</h2>
          </div>
          <div style={{ padding: '4px 0' }}>
            {device.printers.map((p, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '9px 14px',
                borderBottom: i < device.printers.length - 1 ? '1px solid #1a1c28' : 'none',
              }}>
                {/* Icon */}
                <div style={{ width: 30, height: 30, borderRadius: 7, background: p.is_network ? 'rgba(137,180,250,0.1)' : 'rgba(88,91,112,0.15)', border: `1px solid ${p.is_network ? 'rgba(137,180,250,0.2)' : 'rgba(88,91,112,0.2)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: 14 }}>
                  🖨️
                </div>
                {/* Name + driver */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    {p.is_default && (
                      <span style={{ fontSize: 10, color: '#f9e2af', background: 'rgba(249,226,175,0.1)', border: '1px solid rgba(249,226,175,0.2)', borderRadius: 4, padding: '1px 6px', fontWeight: 700, letterSpacing: '0.3px', textTransform: 'uppercase' }}>Default</span>
                    )}
                    <span style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }} title={p.name}>{p.name}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#4a5568', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.driver_name || ''}>
                    {p.driver_name || '—'}
                  </div>
                </div>
                {/* Chips: IP, Port, Type, Status */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  {p.ip_address && (
                    <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#cba6f7', background: 'rgba(203,166,247,0.08)', border: '1px solid rgba(203,166,247,0.18)', borderRadius: 5, padding: '2px 7px' }}>{p.ip_address}</span>
                  )}
                  {p.port_name && (
                    <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280', background: 'rgba(107,114,128,0.08)', border: '1px solid rgba(107,114,128,0.15)', borderRadius: 5, padding: '2px 7px', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.port_name}>{p.port_name}</span>
                  )}
                  <span style={{ fontSize: 10, color: p.is_network ? '#89b4fa' : '#585b70', background: p.is_network ? 'rgba(137,180,250,0.08)' : 'rgba(88,91,112,0.1)', border: `1px solid ${p.is_network ? 'rgba(137,180,250,0.2)' : 'rgba(88,91,112,0.2)'}`, borderRadius: 5, padding: '2px 7px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.3px' }}>
                    {p.is_network ? 'Network' : 'Local'}
                  </span>
                  <span style={{ fontSize: 10, color: p.work_offline ? '#ef4444' : '#22c55e', background: p.work_offline ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)', border: `1px solid ${p.work_offline ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.2)'}`, borderRadius: 5, padding: '2px 7px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.3px' }}>
                    {p.work_offline ? 'Offline' : (p.status || 'Idle')}
                  </span>
                  {p.job_count ? <span style={{ fontSize: 10, color: '#f9e2af', background: 'rgba(249,226,175,0.08)', border: '1px solid rgba(249,226,175,0.2)', borderRadius: 5, padding: '2px 7px' }}>{p.job_count} jobs</span> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Info Sections ── */}
      <div className={styles.sections}>
        {sections.filter(s => s.title !== 'Logical Disks' && s.title !== 'Printers').map(({ title, data }) => (
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

      {/* ── Installed Software Table ── */}
      {device.installed_software && device.installed_software.length > 0 && (
        <div className={styles.card} style={{ marginTop: 16 }}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIcon}>📦</span>
            <h2 className={styles.cardTitle}>Installed Software ({device.installed_software.length})</h2>
          </div>
          <div style={{ padding: '16px 20px' }}>
            <input 
              type="text" 
              placeholder="Search software by name or publisher..." 
              className={styles.searchInput}
              value={softSearch}
              onChange={e => setSoftSearch(e.target.value)}
            />
            <div className={styles.tableContainer} style={{ maxHeight: 600 }}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Version</th>
                    <th>Publisher</th>
                    <th>Install Date</th>
                  </tr>
                </thead>
                <tbody>
                  {device.installed_software
                    .filter(s => (s.name||'').toLowerCase().includes(softSearch.toLowerCase()) || (s.publisher||'').toLowerCase().includes(softSearch.toLowerCase()))
                    .map((s, i) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 500 }}>{s.name || '—'}</td>
                      <td>{s.version || '—'}</td>
                      <td>{s.publisher || '—'}</td>
                      <td className={styles.mono}>{s.install_date ? s.install_date.substring(0, 10) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── Terminal ── */}
      <div ref={terminalRef} style={{ marginTop: 16 }}>
        {authToken && device?.id ? (
          <PtyTerminal deviceId={device.id} token={authToken} />
        ) : (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardIcon}>💻</span>
              <h2 className={styles.cardTitle}>Remote Terminal</h2>
            </div>
            <div style={{ padding: '16px 20px', color: '#585b70', fontSize: 13 }}>
              Loading terminal…
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
