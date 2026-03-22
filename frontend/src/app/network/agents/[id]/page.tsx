'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import styles from './agent.module.css';

interface AgentDetail {
  id: number;
  name: string;
  hostname: string;
  ip: string;
  version: string;
  admin_status: string;
  online: boolean;
  last_seen: number | null;
  created_at: string;
  device_count: number;
}

interface Command {
  command_id: string;
  command_type: string;
  status: string;
  issued_at: number;
  issued_by: string;
}

const CMD_TYPES = ['reload_config', 'restart', 'update', 'ping', 'set_log_level'];

function timeAgo(ts: number | null): string {
  if (!ts) return 'Never';
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'blue', success: 'green', failed: 'red', timeout: 'orange',
};

export default function AgentDetailPage({ params }: { params: { id: string } }) {
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [commands, setCommands] = useState<Command[]>([]);
  const [loading, setLoading] = useState(true);
  const [cmdType, setCmdType] = useState('reload_config');
  const [sending, setSending] = useState(false);
  const [sentMsg, setSentMsg] = useState('');
  const [adminStatus, setAdminStatus] = useState('');

  useEffect(() => {
    Promise.all([
      fetch(`/api/agent/agents/${params.id}`).then(r => r.json()),
      fetch(`/api/agent/agents/${params.id}/commands`).then(r => r.json()),
    ]).then(([a, c]) => {
      setAgent(a);
      setCommands(Array.isArray(c) ? c : []);
      setAdminStatus(a?.admin_status || '');
    }).finally(() => setLoading(false));
  }, [params.id]);

  async function sendCommand(e: React.FormEvent) {
    e.preventDefault();
    setSending(true);
    const r = await fetch(`/api/agent/agents/${params.id}/command`, {
      method: 'POST',
      body: JSON.stringify({ command_type: cmdType, payload: {} }),
    });
    setSending(false);
    if (r.ok) {
      setSentMsg(`Command "${cmdType}" sent ✓`);
      setTimeout(() => setSentMsg(''), 4000);
      const c = await fetch(`/api/agent/agents/${params.id}/commands`).then(r => r.json());
      setCommands(Array.isArray(c) ? c : []);
    } else {
      setSentMsg('Failed to send command');
    }
  }

  async function updateStatus(status: string) {
    const r = await fetch(`/api/agent/agents/${params.id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ admin_status: status }),
    });
    if (r.ok) setAgent(prev => prev ? { ...prev, admin_status: status } : prev);
  }

  if (loading) return <div className={styles.loading}>Loading agent…</div>;
  if (!agent) return <div className={styles.loading}>Agent not found.</div>;

  return (
    <div className={styles.page}>
      <div className={styles.breadcrumb}>
        <Link href="/network/agents">← Proxy Agents</Link>
        <span> / </span>
        <span>{agent.name || agent.hostname}</span>
      </div>

      {/* Header */}
      <div className={styles.header}>
        <div>
          <div className={styles.agentType}>Proxy Agent</div>
          <h1 className={styles.title}>{agent.name || agent.hostname}</h1>
          <div className={styles.headerMeta}>
            <span>{agent.hostname}</span>
            <span>·</span>
            <span>{agent.ip}</span>
            <span>·</span>
            <span>v{agent.version}</span>
            <span>·</span>
            <span>{agent.device_count} device{agent.device_count !== 1 ? 's' : ''}</span>
          </div>
        </div>
        <div className={styles.headerRight}>
          <span className={styles.onlineBadge} data-online={agent.online}>
            {agent.online ? '● Online' : '● Offline'}
          </span>
          <span className={`${styles.statusBadge} ${styles[`status_${agent.admin_status}`]}`}>
            {agent.admin_status}
          </span>
        </div>
      </div>

      <div className={styles.layout}>
        {/* Agent info */}
        <div className={styles.infoCol}>
          <div className={styles.card}>
            <div className={styles.cardTitle}>Info</div>
            {[
              ['Hostname', agent.hostname],
              ['IP', agent.ip],
              ['Version', agent.version],
              ['Last Seen', timeAgo(agent.last_seen)],
              ['Registered', agent.created_at],
              ['Devices', String(agent.device_count)],
            ].map(([k, v]) => (
              <div key={k} className={styles.infoRow}>
                <span className={styles.infoLabel}>{k}</span>
                <span className={styles.infoValue}>{v}</span>
              </div>
            ))}
          </div>

          {/* Admin status control */}
          <div className={styles.card}>
            <div className={styles.cardTitle}>Admin Status</div>
            <div className={styles.statusBtns}>
              {['active', 'disabled', 'revoked'].map(s => (
                <button
                  key={s}
                  className={`${styles.statusBtn} ${agent.admin_status === s ? styles.statusBtnActive : ''}`}
                  onClick={() => updateStatus(s)}
                  disabled={agent.admin_status === s}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Commands */}
        <div className={styles.commandsCol}>
          <div className={styles.card}>
            <div className={styles.cardTitle}>Send Command</div>
            <form className={styles.cmdForm} onSubmit={sendCommand}>
              <select
                className={styles.select}
                value={cmdType}
                onChange={e => setCmdType(e.target.value)}
              >
                {CMD_TYPES.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <button type="submit" className={styles.sendBtn} disabled={sending}>
                {sending ? 'Sending…' : 'Send →'}
              </button>
            </form>
            {sentMsg && <div className={styles.sentMsg}>{sentMsg}</div>}
          </div>

          <div className={styles.card}>
            <div className={styles.cardTitle}>Command History</div>
            {commands.length === 0 ? (
              <div className={styles.empty}>No commands issued yet.</div>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Issued by</th>
                    <th>Issued</th>
                  </tr>
                </thead>
                <tbody>
                  {commands.map(cmd => (
                    <tr key={cmd.command_id}>
                      <td className={styles.mono}>{cmd.command_type}</td>
                      <td>
                        <span className={`${styles.cmdBadge} ${styles[`badge_${STATUS_COLOR[cmd.status] || 'blue'}`]}`}>
                          {cmd.status}
                        </span>
                      </td>
                      <td className={styles.muted}>{cmd.issued_by}</td>
                      <td className={styles.muted}>{timeAgo(cmd.issued_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
