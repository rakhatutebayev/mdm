import styles from './page.module.css';
import Link from 'next/link';
import { PlatformIcon } from '@/components/icons/PlatformIcons';

const DEVICES = [
  { id: 1, name: 'iPhone 15 Pro', serial: 'F2LQK19KX4', user: 'Akhmet Seitkali', platform: 'iOS', os: '17.3.1', status: 'Compliant', enrolled: '2024-01-15', lastSeen: '2 min ago' },
  { id: 2, name: 'Samsung Galaxy S24', serial: 'R58N93MHZK', user: 'Dana Nurova', platform: 'Android', os: '14.0', status: 'Non-Compliant', enrolled: '2024-02-03', lastSeen: '15 min ago' },
  { id: 3, name: 'MacBook Pro M3', serial: 'C02XG1JDHV2L', user: 'Sergei Ivanov', platform: 'macOS', os: '14.3', status: 'Compliant', enrolled: '2023-11-20', lastSeen: '1 hour ago' },
  { id: 4, name: 'iPad Pro 12.9', serial: 'DLXPQ7MTTF', user: 'Asel Bekova', platform: 'iPadOS', os: '17.2', status: 'Compliant', enrolled: '2024-01-28', lastSeen: '3 hours ago' },
  { id: 5, name: 'Dell Latitude 5540', serial: 'WIN-4FH3K2P', user: 'Timur Omarov', platform: 'Windows', os: '11 22H2', status: 'Pending', enrolled: '2024-03-01', lastSeen: '1 day ago' },
  { id: 6, name: 'Pixel 8 Pro', serial: 'GX8B2KN7YT', user: 'Marat Zhukov', platform: 'Android', os: '14.0', status: 'Compliant', enrolled: '2024-02-14', lastSeen: '30 min ago' },
  { id: 7, name: 'iPhone 14', serial: 'F2MXY3KPD1', user: 'Zarina Kasymova', platform: 'iOS', os: '17.3', status: 'Compliant', enrolled: '2023-12-01', lastSeen: '5 min ago' },
  { id: 8, name: 'MacBook Air M2', serial: 'C02YH8JLMD6T', user: 'Alexei Petrov', platform: 'macOS', os: '14.2', status: 'Non-Compliant', enrolled: '2023-10-15', lastSeen: '2 days ago' },
];

const STATUS_COLOR: Record<string, string> = {
  Compliant: 'green', 'Non-Compliant': 'orange', Pending: 'blue',
};

export default function DevicesPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Device Management</h1>
          <p className={styles.subtitle}>{DEVICES.length} devices total</p>
        </div>
        <Link href="/enrollment" className={styles.primaryBtn}>+ Enroll Device</Link>
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <input className={styles.filterSearch} type="text" placeholder="🔍  Search device name, user, serial…" />
        <select className={styles.filterSelect}>
          <option>All Platforms</option>
          <option>iOS</option>
          <option>Android</option>
          <option>macOS</option>
          <option>iPadOS</option>
          <option>Windows</option>
        </select>
        <select className={styles.filterSelect}>
          <option>All Statuses</option>
          <option>Compliant</option>
          <option>Non-Compliant</option>
          <option>Pending</option>
        </select>
      </div>

      {/* Table */}
      <div className={styles.card}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th><input type="checkbox" /></th>
              <th>Device</th>
              <th>User</th>
              <th>Platform</th>
              <th>OS Version</th>
              <th>Status</th>
              <th>Enrolled</th>
              <th>Last Seen</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {DEVICES.map((d) => (
              <tr key={d.id}>
                <td><input type="checkbox" /></td>
                <td>
                  <div className={styles.deviceCell}>
                    <span className={styles.deviceName}>{d.name}</span>
                    <span className={styles.serial}>{d.serial}</span>
                  </div>
                </td>
                <td>{d.user}</td>
                <td>
                  <span className={styles.platform}>
                    <PlatformIcon platform={d.platform} size={14} /> {d.platform}
                  </span>
                </td>
                <td className={styles.muted}>{d.os}</td>
                <td>
                  <span className={`${styles.badge} ${styles[`badge_${STATUS_COLOR[d.status]}`]}`}>
                    {d.status}
                  </span>
                </td>
                <td className={styles.muted}>{d.enrolled}</td>
                <td className={styles.muted}>{d.lastSeen}</td>
                <td>
                  <div className={styles.actions}>
                    <button className={styles.actionBtn} title="Lock">🔒</button>
                    <button className={styles.actionBtn} title="Wipe">🗑️</button>
                    <button className={styles.actionBtn} title="Details">→</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
