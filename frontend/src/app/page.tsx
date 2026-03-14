import styles from './page.module.css';
import Link from 'next/link';
import { PlatformIcon } from '@/components/icons/PlatformIcons';

export const dynamic = 'force-dynamic';

// ── Types ──────────────────────────────────────────────────────────────────────
interface DashboardStats {
  total: number;
  compliant: number;
  non_compliant: number;
  pending: number;
  platforms: { name: string; count: number; pct: number }[];
  recent_devices: {
    id: string;
    name: string;
    user: string;
    platform: string;
    status: string;
    last_seen: string;
  }[];
}

// ── Fetch from backend API (server-side) ───────────────────────────────────────
async function getDashboardStats(): Promise<DashboardStats> {
  const apiUrl = process.env.API_URL || 'http://localhost:8000';
  try {
    const res = await fetch(`${apiUrl}/api/v1/dashboard/stats`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API error ${res.status}`);
    return res.json();
  } catch {
    // Return empty state on error — don't crash the dashboard
    return {
      total: 0, compliant: 0, non_compliant: 0, pending: 0,
      platforms: [], recent_devices: [],
    };
  }
}

const STATUS_COLOR: Record<string, string> = {
  Compliant: 'green',
  'Non-Compliant': 'orange',
  Pending: 'blue',
  'Pending Enrollment': 'blue',
  Unknown: 'red',
};

const PLATFORM_COLORS = ['#4a7cff', '#22c55e', '#f59e0b', '#8b90a4', '#a855f7'];

// ── Page ───────────────────────────────────────────────────────────────────────
export default async function DashboardPage() {
  const stats = await getDashboardStats();

  const complianceRate = stats.total > 0
    ? Math.round(stats.compliant / stats.total * 100)
    : 0;

  const STATS = [
    {
      label: 'Total Devices', value: stats.total.toLocaleString(),
      sub: stats.total === 0 ? 'No devices enrolled yet' : `Across all customers`,
      color: 'blue',
      icon: <svg viewBox="0 0 24 24"><path d="M17 2H7a2 2 0 00-2 2v16a2 2 0 002 2h10a2 2 0 002-2V4a2 2 0 00-2-2zM12 20a1 1 0 110-2 1 1 0 010 2z"/></svg>,
    },
    {
      label: 'Compliant', value: stats.compliant.toLocaleString(),
      sub: stats.total > 0 ? `${complianceRate}% compliance rate` : '—',
      color: 'green',
      icon: <svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>,
    },
    {
      label: 'Non-Compliant', value: stats.non_compliant.toLocaleString(),
      sub: stats.non_compliant > 0 ? 'Requires action' : 'All devices compliant ✓',
      color: 'orange',
      icon: <svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>,
    },
    {
      label: 'Pending Enrollment', value: stats.pending.toLocaleString(),
      sub: stats.pending > 0 ? 'Awaiting activation' : 'No pending devices',
      color: 'red',
      icon: <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20A10 10 0 0012 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>,
    },
  ];

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Dashboard</h1>
          <p className={styles.subtitle}>
            Welcome back · {new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
          </p>
        </div>
        <Link href="/enrollment" className={styles.enrollBtn}>
          + Enroll Device
        </Link>
      </div>

      {/* Stats */}
      <div className={styles.statsGrid}>
        {STATS.map((s) => (
          <div key={s.label} className={styles.statCard}>
            <div className={`${styles.statIcon} ${styles[s.color]}`}>{s.icon}</div>
            <div className={styles.statLabel}>{s.label}</div>
            <div className={styles.statValue}>{s.value}</div>
            <div className={styles.statSub}>{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Content row */}
      <div className={styles.contentRow}>
        {/* Recent devices */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <span className={styles.cardTitle}>Recent Devices</span>
            <Link href="/devices" className={styles.cardLink}>View all →</Link>
          </div>

          {stats.recent_devices.length === 0 ? (
            <div className={styles.empty}>
              <p>No devices enrolled yet.</p>
              <Link href="/enrollment" className={styles.enrollBtn} style={{ marginTop: 12, display: 'inline-block' }}>
                Enroll your first device →
              </Link>
            </div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Device</th>
                  <th>User</th>
                  <th>Platform</th>
                  <th>Status</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_devices.map((d) => (
                  <tr key={d.id}>
                    <td className={styles.deviceName}>
                      <Link href={`/devices/${d.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                        {d.name}
                      </Link>
                    </td>
                    <td>{d.user}</td>
                    <td>
                      <span className={styles.platform}>
                        <PlatformIcon platform={d.platform} size={14} /> {d.platform}
                      </span>
                    </td>
                    <td>
                      <span className={`${styles.badge} ${styles[`badge_${STATUS_COLOR[d.status] ?? 'blue'}`]}`}>
                        {d.status}
                      </span>
                    </td>
                    <td className={styles.muted}>{d.last_seen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Sidebar */}
        <div className={styles.sidebar}>
          {/* Quick Actions */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardTitle}>Quick Actions</span>
            </div>
            <div className={styles.quickActions}>
              {[
                { icon: '📲', label: 'Enroll New Device', href: '/enrollment' },
                { icon: '🖥️', label: 'View All Devices', href: '/devices' },
                { icon: '👥', label: 'Manage Customers', href: '/customers' },
                { icon: '👤', label: 'Admin Panel', href: '/admin' },
                { icon: '⚙️', label: 'Settings', href: '/admin/settings' },
              ].map((a) => (
                <Link key={a.label} href={a.href} className={styles.quickAction}>
                  <span className={styles.qaIcon}>{a.icon}</span>
                  <span>{a.label}</span>
                  <svg viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
                </Link>
              ))}
            </div>
          </div>

          {/* Platform Distribution */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardTitle}>Platform Distribution</span>
            </div>
            {stats.platforms.length === 0 ? (
              <div className={styles.empty} style={{ fontSize: 13 }}>No devices yet</div>
            ) : (
              <div className={styles.platforms}>
                {stats.platforms.map((p, i) => (
                  <div key={p.name} className={styles.platformRow}>
                    <div className={styles.platformInfo}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <PlatformIcon platform={p.name} size={13} /> {p.name}
                      </span>
                      <span className={styles.muted}>{p.count}</span>
                    </div>
                    <div className={styles.progressBar}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${p.pct}%`, background: PLATFORM_COLORS[i % PLATFORM_COLORS.length] }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
