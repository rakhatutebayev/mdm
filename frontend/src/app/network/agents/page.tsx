import Link from 'next/link';
import styles from './agents.module.css';

export const dynamic = 'force-dynamic';

const API = process.env.API_URL || 'http://localhost:8000';
const TENANT_ID = process.env.DEFAULT_TENANT_ID || '1';

interface AgentRow {
  id: number;
  name: string;
  hostname: string;
  ip: string;
  version: string;
  admin_status: string;
  online: boolean;
  last_seen: number | null;
  created_at: string;
}

async function fetchAgents(): Promise<AgentRow[]> {
  try {
    const r = await fetch(`${API}/api/v1/portal/agents`, {
      headers: { 'X-Tenant-Id': TENANT_ID },
      cache: 'no-store',
    });
    if (!r.ok) return [];
    return r.json();
  } catch { return []; }
}

function timeAgo(ts: number | null): string {
  if (!ts) return 'Never';
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default async function AgentsPage() {
  const agents = await fetchAgents();
  const online = agents.filter(a => a.online).length;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Proxy Agents</h1>
          <p className={styles.subtitle}>{online} online · {agents.length} total</p>
        </div>
      </div>

      <div className={styles.statsRow}>
        {[
          { label: 'Total', value: agents.length, color: 'blue' },
          { label: 'Online', value: online, color: 'green' },
          { label: 'Offline', value: agents.length - online, color: 'orange' },
          { label: 'Revoked', value: agents.filter(a => a.admin_status === 'revoked').length, color: 'red' },
        ].map(s => (
          <div key={s.label} className={`${styles.statCard} ${styles[s.color]}`}>
            <div className={styles.statValue}>{s.value}</div>
            <div className={styles.statLabel}>{s.label}</div>
          </div>
        ))}
      </div>

      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <span className={styles.cardTitle}>All Agents</span>
        </div>

        {agents.length === 0 ? (
          <div className={styles.empty}>
            <p>No agents registered yet. Install the proxy agent on a Linux server.</p>
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Status</th>
                <th>Name / Hostname</th>
                <th>IP Address</th>
                <th>Version</th>
                <th>Admin Status</th>
                <th>Last Seen</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {agents.map(agent => (
                <tr key={agent.id}>
                  <td>
                    <span className={`${styles.dot} ${agent.online ? styles.dotOnline : styles.dotOffline}`} />
                  </td>
                  <td className={styles.deviceName}>
                    <Link href={`/network/agents/${agent.id}`}>
                      {agent.name || agent.hostname || `Agent #${agent.id}`}
                    </Link>
                    <span className={styles.muted}>{agent.hostname}</span>
                  </td>
                  <td className={styles.mono}>{agent.ip || '—'}</td>
                  <td className={styles.mono}>{agent.version}</td>
                  <td>
                    <span className={`${styles.badge} ${styles[`badge_${agent.admin_status}`]}`}>
                      {agent.admin_status}
                    </span>
                  </td>
                  <td className={styles.muted}>{timeAgo(agent.last_seen)}</td>
                  <td>
                    <Link href={`/network/agents/${agent.id}`} className={styles.actionBtn}>
                      View →
                    </Link>
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
