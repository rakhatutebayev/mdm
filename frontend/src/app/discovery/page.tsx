'use client';

export const dynamic = 'force-dynamic';

import Link from 'next/link';
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  createProxyAgent,
  createProxyAgentCommand,
  getCustomers,
  getProxyAgentCommand,
  getProxyAgents,
  registerProxyAgent,
  type Customer,
  type ProxyAgent,
  type ProxyAgentCommand,
} from '@/lib/api';
import styles from './page.module.css';

const CAPABILITY_OPTIONS = ['snmp', 'redfish', 'lldp', 'ssh'];
const ALL_CUSTOMERS = '__all__';

function fmtDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatCommandType(value: string | null | undefined) {
  return (value || 'command').replace(/_/g, ' ');
}

function formatCommandStatus(command: ProxyAgentCommand | null | undefined) {
  if (!command) return 'No commands yet';
  const result = (command.result || '').trim();
  if (!result) return `${formatCommandType(command.command_type)}: ${command.status}`;
  return `${formatCommandType(command.command_type)}: ${command.status} - ${result}`;
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function agentLabel(agent: ProxyAgent) {
  const version = (agent.version || '').trim();
  return version ? `Proxy Agent ${version}` : 'Proxy Agent';
}

function serverName(agent: ProxyAgent) {
  return agent.hostname || agent.ip_address || agent.name || 'Unnamed host';
}

type AgentCommandState = {
  busy: boolean;
  info: string | null;
  lastCommand: ProxyAgentCommand | null;
};

type StatusTone = 'green' | 'orange' | 'gray';

function statusTone(status: string): StatusTone {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'online') return 'green';
  if (normalized === 'not registered') return 'orange';
  return 'gray';
}

function DiscoveryPageClient() {
  const searchParams = useSearchParams();
  const requestedCustomerId = searchParams.get('customer');

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [agents, setAgents] = useState<ProxyAgent[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState(requestedCustomerId || ALL_CUSTOMERS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [portalUrl, setPortalUrl] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdAgent, setCreatedAgent] = useState<ProxyAgent | null>(null);
  const [agentCommandState, setAgentCommandState] = useState<Record<string, AgentCommandState>>({});
  const [form, setForm] = useState({
    customer_id: requestedCustomerId || '',
    name: '',
    site_name: '',
    hostname: '',
    ip_address: '',
    version: '0.1.0',
    capabilities: ['snmp', 'redfish', 'lldp'],
  });

  useEffect(() => {
    if (typeof window !== 'undefined' && !portalUrl) {
      setPortalUrl(window.location.origin);
    }
  }, [portalUrl]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [customersData, agentsData] = await Promise.all([getCustomers(), getProxyAgents()]);
      setCustomers(customersData);
      setAgents(agentsData);
      setAgentCommandState((prev) => {
        const next: Record<string, AgentCommandState> = {};
        for (const agent of agentsData) {
          next[agent.id] = prev[agent.id] || { busy: false, info: null, lastCommand: null };
        }
        return next;
      });

      if (!customersData.length) {
        setError('Create a customer first to use discovery.');
      }

      if (requestedCustomerId) {
        setSelectedCustomerId(requestedCustomerId);
        setForm((prev) => ({ ...prev, customer_id: prev.customer_id || requestedCustomerId }));
      } else if (customersData.length) {
        setForm((prev) => ({ ...prev, customer_id: prev.customer_id || customersData[0].id }));
      }
    } catch (err) {
      console.error(err);
      setError('Could not load proxy agents.');
    } finally {
      setLoading(false);
    }
  }, [requestedCustomerId]);

  useEffect(() => {
    void load();
  }, [load]);

  const customerNameById = useMemo(
    () => Object.fromEntries(customers.map((customer) => [customer.id, customer.name])),
    [customers]
  );

  const filteredAgents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return agents.filter((agent) => {
      if (selectedCustomerId !== ALL_CUSTOMERS && agent.customer_id !== selectedCustomerId) {
        return false;
      }
      if (!query) return true;
      return [
        agent.name,
        agent.hostname,
        agent.ip_address,
        agent.version,
        agent.status,
        customerNameById[agent.customer_id] || '',
        agent.site_name,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query);
    });
  }, [agents, customerNameById, search, selectedCustomerId]);

  const onlineCount = filteredAgents.filter((agent) => agent.status.toLowerCase() === 'online').length;
  const registeredCount = filteredAgents.filter((agent) => agent.is_registered).length;
  const pendingCount = filteredAgents.filter((agent) => !agent.is_registered).length;

  const bootstrapCommand = createdAgent
    ? `python3 -m proxy_agent.main register --server "${portalUrl || 'https://portal.example.com'}" --agent-id "${createdAgent.id}" --token "${createdAgent.auth_token}" --name "${createdAgent.name}" --site "${createdAgent.site_name || 'default'}" --hostname "${createdAgent.hostname || 'proxy-agent-host'}" --ip "${createdAgent.ip_address || '192.168.11.153'}" --version "${createdAgent.version || '0.1.0'}"`
    : '';

  const bootstrapConfig = createdAgent
    ? JSON.stringify(
        {
          portal_url: portalUrl || 'https://portal.example.com',
          agent_id: createdAgent.id,
          agent_token: createdAgent.auth_token,
          agent_name: createdAgent.name,
          site_name: createdAgent.site_name,
          hostname: createdAgent.hostname,
          ip_address: createdAgent.ip_address,
          version: createdAgent.version,
          mqtt_enabled: true,
          mqtt_transport: 'websockets',
          mqtt_path: '/mqtt',
          collectors_enabled: createdAgent.capabilities,
        },
        null,
        2
      )
    : '';

  const updateForm = (
    key: 'customer_id' | 'name' | 'site_name' | 'hostname' | 'ip_address' | 'version',
    value: string
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleCapability = (capability: string) => {
    setForm((prev) => {
      const exists = prev.capabilities.includes(capability);
      return {
        ...prev,
        capabilities: exists
          ? prev.capabilities.filter((item) => item !== capability)
          : [...prev.capabilities, capability],
      };
    });
  };

  const handleCreate = async () => {
    if (!form.customer_id.trim()) {
      setCreateError('Company is required.');
      return;
    }
    if (!form.name.trim()) {
      setCreateError('Proxy Agent display name is required.');
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const agent = await createProxyAgent({
        customer_id: form.customer_id.trim(),
        name: form.name.trim(),
        site_name: form.site_name.trim(),
        hostname: form.hostname.trim(),
        ip_address: form.ip_address.trim(),
        version: form.version.trim(),
        capabilities: form.capabilities,
      });
      setAgents((prev) => [agent, ...prev.filter((item) => item.id !== agent.id)]);
      setCreatedAgent(agent);
      setShowCreateForm(true);
      setForm((prev) => ({
        ...prev,
        name: '',
        hostname: '',
        ip_address: '',
      }));
    } catch (err) {
      console.error(err);
      setCreateError('Could not create proxy agent.');
    } finally {
      setCreating(false);
    }
  };

  const setCommandState = (agentId: string, patch: Partial<AgentCommandState>) => {
    setAgentCommandState((prev) => ({
      ...prev,
      [agentId]: {
        ...prev[agentId],
        busy: prev[agentId]?.busy ?? false,
        info: prev[agentId]?.info ?? null,
        lastCommand: prev[agentId]?.lastCommand ?? null,
        ...patch,
      },
    }));
  };

  const replaceAgent = (updated: ProxyAgent) => {
    setAgents((prev) => prev.map((agent) => (agent.id === updated.id ? updated : agent)));
    if (createdAgent?.id === updated.id) {
      setCreatedAgent(updated);
    }
  };

  const pollCommand = async (agentId: string, commandId: string) => {
    for (let attempt = 0; attempt < 18; attempt += 1) {
      const current = await getProxyAgentCommand(agentId, commandId);
      setCommandState(agentId, { lastCommand: current });
      if (['acked', 'completed', 'failed'].includes(current.status)) {
        setCommandState(agentId, {
          busy: false,
          info: formatCommandStatus(current),
          lastCommand: current,
        });
        if (current.command_type === 'sync_now' && ['acked', 'completed'].includes(current.status)) {
          void load();
        }
        return;
      }
      await wait(2500);
    }

    setCommandState(agentId, {
      busy: false,
      info: 'Command queued but no final response yet.',
    });
  };

  const handleAgentCommand = async (agent: ProxyAgent, commandType: 'ping' | 'sync_now') => {
    setCommandState(agent.id, {
      busy: true,
      info: `${formatCommandType(commandType)} queued...`,
    });
    try {
      const command = await createProxyAgentCommand(agent.id, {
        command_type: commandType,
        payload: {
          requested_from: 'portal',
          requested_at: new Date().toISOString(),
        },
      });
      setCommandState(agent.id, {
        busy: true,
        info: `${formatCommandType(commandType)} sent to agent.`,
        lastCommand: command,
      });
      void pollCommand(agent.id, command.id);
    } catch (err) {
      console.error(err);
      setCommandState(agent.id, {
        busy: false,
        info: `Could not run ${formatCommandType(commandType)}.`,
      });
    }
  };

  const handlePortalRegister = async (agent: ProxyAgent) => {
    setCommandState(agent.id, {
      busy: true,
      info: 'Registering agent in portal...',
    });
    try {
      const updated = await registerProxyAgent(agent.id);
      replaceAgent(updated);
      setCommandState(agent.id, {
        busy: false,
        info: 'Agent marked as registered.',
      });
    } catch (err) {
      console.error(err);
      setCommandState(agent.id, {
        busy: false,
        info: 'Could not register agent.',
      });
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Discovery</h1>
          <p className={styles.subtitle}>
            Proxy Agent registry by company with registration lifecycle, agent self-information, and per-server drill-down.
          </p>
        </div>
        <div className={styles.customerBadge}>
          {selectedCustomerId === ALL_CUSTOMERS ? 'All companies' : customerNameById[selectedCustomerId] || selectedCustomerId}
        </div>
      </div>

      <div className={styles.note}>
        The table below tracks Proxy Agents themselves: where they are installed, which company they belong to, whether they are registered in the portal, and when they last reported.
      </div>

      <div className={styles.stats}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>Proxy Agents</span>
          <strong className={styles.statValue}>{filteredAgents.length}</strong>
          <span className={styles.statMeta}>Visible in current filter</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>Registered</span>
          <strong className={styles.statValue}>{registeredCount}</strong>
          <span className={styles.statMeta}>{pendingCount} pending registration</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>Online</span>
          <strong className={styles.statValue}>{onlineCount}</strong>
          <span className={styles.statMeta}>Reported recently</span>
        </div>
      </div>

      <div className={styles.toolbar}>
        <select
          className={styles.select}
          value={selectedCustomerId}
          onChange={(e) => setSelectedCustomerId(e.target.value)}
        >
          <option value={ALL_CUSTOMERS}>All companies</option>
          {customers.map((customer) => (
            <option key={customer.id} value={customer.id}>
              {customer.name}
            </option>
          ))}
        </select>
        <input
          className={styles.search}
          type="text"
          placeholder="Search agents, hosts, companies, versions..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className={styles.refreshBtn} onClick={() => void load()}>
          Refresh
        </button>
        <button className={styles.primaryBtn} onClick={() => setShowCreateForm((prev) => !prev)}>
          {showCreateForm ? 'Hide Create Form' : 'Create Proxy Agent'}
        </button>
      </div>

      {showCreateForm ? (
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Create Proxy Agent</h2>
            <span>Issue token and bootstrap settings for a new agent</span>
          </div>
          <div className={styles.registerGrid}>
            <div className={styles.formCard}>
              <div className={styles.formGrid}>
                <label className={styles.field}>
                  <span>Company</span>
                  <select
                    className={styles.fieldSelect}
                    value={form.customer_id}
                    onChange={(e) => updateForm('customer_id', e.target.value)}
                  >
                    <option value="">Select company</option>
                    {customers.map((customer) => (
                      <option key={customer.id} value={customer.id}>
                        {customer.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span>Display Name</span>
                  <input value={form.name} onChange={(e) => updateForm('name', e.target.value)} placeholder="HQ Proxy Agent" />
                </label>
                <label className={styles.field}>
                  <span>Site</span>
                  <input value={form.site_name} onChange={(e) => updateForm('site_name', e.target.value)} placeholder="HQ" />
                </label>
                <label className={styles.field}>
                  <span>Server Name</span>
                  <input value={form.hostname} onChange={(e) => updateForm('hostname', e.target.value)} placeholder="proxy-branch-01" />
                </label>
                <label className={styles.field}>
                  <span>Agent IP</span>
                  <input value={form.ip_address} onChange={(e) => updateForm('ip_address', e.target.value)} placeholder="192.168.11.153" />
                </label>
                <label className={styles.field}>
                  <span>Version</span>
                  <input value={form.version} onChange={(e) => updateForm('version', e.target.value)} placeholder="0.1.0" />
                </label>
              </div>

              <div className={styles.field}>
                <span>Capabilities</span>
                <div className={styles.capabilities}>
                  {CAPABILITY_OPTIONS.map((capability) => (
                    <label key={capability} className={styles.capability}>
                      <input
                        type="checkbox"
                        checked={form.capabilities.includes(capability)}
                        onChange={() => toggleCapability(capability)}
                      />
                      {capability}
                    </label>
                  ))}
                </div>
              </div>

              {createError ? <div className={styles.error}>{createError}</div> : null}

              <div className={styles.actions}>
                <button className={styles.primaryBtn} onClick={() => void handleCreate()} disabled={creating}>
                  {creating ? 'Creating…' : 'Create Proxy Agent'}
                </button>
              </div>
            </div>

            <div className={styles.bootstrapCard}>
              <div className={styles.bootstrapHeader}>
                <strong>Bootstrap</strong>
                <span>{createdAgent ? 'Use this on the server that will run the agent' : 'Create an agent to generate bootstrap data'}</span>
              </div>

              {createdAgent ? (
                <>
                  <div className={styles.bootstrapMeta}>
                    <div><span>Company</span><strong>{customerNameById[createdAgent.customer_id] || createdAgent.customer_id}</strong></div>
                    <div><span>Agent</span><strong>{createdAgent.name}</strong></div>
                    <div><span>Token</span><strong>{createdAgent.auth_token}</strong></div>
                  </div>

                  <div className={styles.codeLabel}>Register command</div>
                  <pre className={styles.codeBlock}>{bootstrapCommand}</pre>

                  <div className={styles.codeLabel}>Config example</div>
                  <pre className={styles.codeBlock}>{bootstrapConfig}</pre>
                </>
              ) : (
                <div className={styles.emptyBootstrap}>
                  Create a new Proxy Agent record to generate the bootstrap command and config.
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Proxy Agent Registry</h2>
          <span>{filteredAgents.length} shown</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Server Name</th>
                <th>Company</th>
                <th>Agent IP</th>
                <th>Agent</th>
                <th>Registration Date</th>
                <th>Last Update</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className={styles.empty}>Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={8} className={styles.empty}>{error}</td></tr>
              ) : filteredAgents.length === 0 ? (
                <tr><td colSpan={8} className={styles.empty}>No proxy agents found.</td></tr>
              ) : (
                filteredAgents.map((agent) => {
                  const tone = statusTone(agent.status);
                  return (
                    <tr key={agent.id}>
                      <td>
                        <div className={styles.serverCell}>
                          <Link
                            href={`/discovery/agents/${agent.id}${selectedCustomerId !== ALL_CUSTOMERS ? `?customer=${selectedCustomerId}` : ''}`}
                            className={styles.serverLink}
                          >
                            {serverName(agent)}
                          </Link>
                          <span className={styles.cellSub}>{agent.site_name || agent.name}</span>
                        </div>
                      </td>
                      <td>{customerNameById[agent.customer_id] || agent.customer_id}</td>
                      <td>{agent.ip_address || '—'}</td>
                      <td>{agentLabel(agent)}</td>
                      <td>{fmtDate(agent.registered_at)}</td>
                      <td>{fmtDate(agent.last_checkin)}</td>
                      <td>
                        <span
                          className={[
                            styles.badge,
                            tone === 'green' ? styles.badgeOnline : '',
                            tone === 'orange' ? styles.badgePending : '',
                            tone === 'gray' ? styles.badgeMuted : '',
                          ].filter(Boolean).join(' ')}
                        >
                          {agent.status}
                        </span>
                      </td>
                      <td>
                        <div className={styles.commandActions}>
                          {!agent.is_registered ? (
                            <button
                              className={styles.secondaryBtn}
                              disabled={agentCommandState[agent.id]?.busy}
                              onClick={() => void handlePortalRegister(agent)}
                            >
                              Register
                            </button>
                          ) : (
                            <>
                              <button
                                className={styles.secondaryBtn}
                                disabled={agentCommandState[agent.id]?.busy}
                                onClick={() => void handleAgentCommand(agent, 'ping')}
                              >
                                Ping
                              </button>
                              <button
                                className={styles.secondaryBtn}
                                disabled={agentCommandState[agent.id]?.busy}
                                onClick={() => void handleAgentCommand(agent, 'sync_now')}
                              >
                                Sync
                              </button>
                            </>
                          )}
                        </div>
                        <div className={styles.commandState}>
                          {agentCommandState[agent.id]?.info || formatCommandStatus(agentCommandState[agent.id]?.lastCommand)}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default function DiscoveryPage() {
  return (
    <Suspense fallback={<div className={styles.page}>Loading discovery…</div>}>
      <DiscoveryPageClient />
    </Suspense>
  );
}
