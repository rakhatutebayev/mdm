'use client';
export const dynamic = 'force-dynamic';
import { useParams, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getDevice, type DeviceDetail } from '@/lib/api';
import styles from './page.module.css';

const SECTION_ICONS: Record<string, string> = {
  'Device Summary':  '🖥️',
  'Network Summary': '🌐',
  'MDM Info':        '🔒',
  'Monitor Summary': '🖱️',
};

export default function DeviceDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params.id as string;
  const customer = searchParams.get('customer') || 'default';

  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getDevice(id)
      .then(setDevice)
      .catch((e) => setError(e.message || 'Failed to load device'))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div className={styles.notFound}><p>Loading device…</p></div>;
  }

  if (error || !device) {
    return (
      <div className={styles.notFound}>
        <h2>{error || 'Device not found'}</h2>
        <Link href={`/enrollment?customer=${customer}`} className={styles.backLink}>← Back to Enrollment</Link>
      </div>
    );
  }

  // Build section data from API response
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

  const mdmSec: Record<string, string> = {
    'Enrollment Method': device.enrollment_method,
    'Enrolled Time':     device.enrolled_at ? new Date(device.enrolled_at).toLocaleString() : '—',
    'MDM Status':        device.status,
    'Agent Version':     device.agent_version || '—',
    'Customer':          device.customer_name || customer,
  };

  // Build monitor sections — one per monitor if multiple
  const monitorSections = device.monitors.length === 0
    ? [{ title: 'Monitor Summary', data: { 'Monitor Info': 'No monitor data available' } }]
    : device.monitors.length === 1
      ? [{
          title: 'Monitor Summary',
          data: {
            'Model':          device.monitors[0].model || '—',
            'Serial Number':  device.monitors[0].serial_number || '—',
            'Display Size':   device.monitors[0].display_size || '—',
            'Resolution':     device.monitors[0].resolution || '—',
            'Refresh Rate':   device.monitors[0].refresh_rate || '—',
            'Color Depth':    device.monitors[0].color_depth || '—',
            'Connection':     device.monitors[0].connection_type || '—',
            'HDR Support':    device.monitors[0].hdr_support ? 'Yes' : 'No',
          }
        }]
      : [{
          title: 'Monitor Summary',
          data: {
            'Number of Displays': String(device.monitors.length),
            ...Object.fromEntries(
              device.monitors.flatMap((m) => [
                [`Monitor ${m.display_index} — Model`,      m.model || '—'],
                [`Monitor ${m.display_index} — Serial`,     m.serial_number || '—'],
                [`Monitor ${m.display_index} — Size`,       m.display_size || '—'],
                [`Monitor ${m.display_index} — Resolution`, m.resolution || '—'],
                [`Monitor ${m.display_index} — Refresh`,    m.refresh_rate || '—'],
                [`Monitor ${m.display_index} — Connection`, m.connection_type || '—'],
                [`Monitor ${m.display_index} — HDR`,        m.hdr_support ? 'Yes' : 'No'],
              ])
            )
          }
        }];

  const sections = [
    { title: 'Device Summary',  data: summarySec },
    { title: 'Network Summary', data: networkSec },
    { title: 'MDM Info',        data: mdmSec },
    ...monitorSections,
  ];

  const statusClass =
    device.status === 'Enrolled'     ? styles.badgeGreen  :
    device.status === 'Pending'      ? styles.badgeOrange :
    device.status === 'Deprovisioned' ? styles.badgeRed   : styles.badgeRed;

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
            <h1 className={styles.pageTitle}>{device.device_name}</h1>
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

      {/* ── Sections ── */}
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
