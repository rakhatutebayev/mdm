import Link from 'next/link';

const NAV_ITEMS = [
  { href: '/network/agents', label: 'Proxy Agents', icon: '📡' },
  { href: '/network/devices', label: 'Devices', icon: '🖥️' },
  { href: '/network/alerts', label: 'Alerts', icon: '🔔' },
  { href: '/network/profiles', label: 'SNMP Profiles', icon: '🗂️' },
];


export default function NetworkLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - var(--nav-height, 60px))' }}>
      <aside style={{
        width: 220, background: '#13151e', borderRight: '1px solid #1e2030',
        padding: '24px 0', flexShrink: 0,
      }}>
        <div style={{
          padding: '0 20px 16px', fontSize: 11, fontWeight: 600,
          textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b90a4',
        }}>
          Network Monitoring
        </div>
        {NAV_ITEMS.map(item => (
          <Link
            key={item.href}
            href={item.href}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 20px', color: '#c8cce0', textDecoration: 'none',
              fontSize: 14, transition: 'all 0.15s',
            }}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}
      </aside>
      <main style={{ flex: 1, overflow: 'auto' }}>
        {children}
      </main>
    </div>
  );
}
