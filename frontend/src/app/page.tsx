import styles from './page.module.css';
import Link from 'next/link';
import { PlatformIcon } from '@/components/icons/PlatformIcons';

const STATS = [
  { label: 'Total Devices', value: '1,284', sub: '↑ 12% this month', color: 'blue',
    icon: <svg viewBox="0 0 24 24"><path d="M17 2H7a2 2 0 00-2 2v16a2 2 0 002 2h10a2 2 0 002-2V4a2 2 0 00-2-2zM12 20a1 1 0 110-2 1 1 0 010 2z"/></svg> },
  { label: 'Compliant', value: '1,150', sub: '89.6% compliance rate', color: 'green',
    icon: <svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg> },
  { label: 'Non-Compliant', value: '134', sub: 'Requires action', color: 'orange',
    icon: <svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg> },
  { label: 'Pending Enrollment', value: '47', sub: 'Awaiting activation', color: 'red',
    icon: <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20A10 10 0 0012 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg> },
];

const RECENT_DEVICES = [
  { name: 'iPhone 15 Pro', user: 'Akhmet Seitkali', platform: 'iOS', status: 'Compliant', lastSeen: '2 min ago' },
  { name: 'Samsung Galaxy S24', user: 'Dana Nurova', platform: 'Android', status: 'Non-Compliant', lastSeen: '15 min ago' },
  { name: 'MacBook Pro M3', user: 'Sergei Ivanov', platform: 'macOS', status: 'Compliant', lastSeen: '1 hour ago' },
  { name: 'iPad Pro 12.9', user: 'Asel Bekova', platform: 'iPadOS', status: 'Compliant', lastSeen: '3 hours ago' },
  { name: 'Windows 11 Laptop', user: 'Timur Omarov', platform: 'Windows', status: 'Pending', lastSeen: '1 day ago' },
];

const STATUS_COLOR: Record<string, string> = {
  Compliant: 'green', 'Non-Compliant': 'orange', Pending: 'blue',
};

export default function DashboardPage() {
  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Dashboard</h1>
          <p className={styles.subtitle}>Welcome back, Rakhat · March 14, 2026</p>
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
              {RECENT_DEVICES.map((d) => (
                <tr key={d.name}>
                  <td className={styles.deviceName}>{d.name}</td>
                  <td>{d.user}</td>
                  <td>
                    <span className={styles.platform}>
                      <PlatformIcon platform={d.platform} size={14} /> {d.platform}
                    </span>
                  </td>
                  <td>
                    <span className={`${styles.badge} ${styles[`badge_${STATUS_COLOR[d.status]}`]}`}>
                      {d.status}
                    </span>
                  </td>
                  <td className={styles.muted}>{d.lastSeen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Quick actions */}
        <div className={styles.sidebar}>
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardTitle}>Quick Actions</span>
            </div>
            <div className={styles.quickActions}>
              {[
                { icon: '📲', label: 'Enroll New Device', href: '/enrollment' },
                { icon: '🔒', label: 'Lock All Devices', href: '/devices' },
                { icon: '📋', label: 'Generate Report', href: '/reports/status' },
                { icon: '👤', label: 'Add User', href: '/admin/users' },
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

          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardTitle}>Platform Distribution</span>
            </div>
            <div className={styles.platforms}>
              {['📱', '📱', '💻', '📲'].map((icon, i) => {
                const names = ['iOS', 'Android', 'macOS', 'Windows'];
                const counts = [542, 389, 218, 135];
                const pcts = [42, 30, 17, 11];
                const colors = ['#4a7cff', '#22c55e', '#f59e0b', '#8b90a4'];
                const p = { name: names[i], count: counts[i], pct: pcts[i], color: colors[i] };
                void icon;
                return (
                  <div key={p.name} className={styles.platformRow}>
                    <div className={styles.platformInfo}>
                      <span style={{ display:'flex', alignItems:'center', gap: 5 }}><PlatformIcon platform={p.name} size={13} /> {p.name}</span>
                      <span className={styles.muted}>{p.count}</span>
                    </div>
                    <div className={styles.progressBar}>
                      <div className={styles.progressFill} style={{ width: `${p.pct}%`, background: p.color }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
