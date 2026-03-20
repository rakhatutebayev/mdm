'use client';

export const dynamic = 'force-dynamic';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import {
  createProxyAgentCommand,
  getCustomers,
  getDiscoveredAssets,
  getProxyAgent,
  getProxyAgentCommand,
  getProxyAgentCommands,
  registerProxyAgent,
  type Customer,
  type DiscoveredAsset,
  type ProxyAgent,
  type ProxyAgentCommand,
} from '@/lib/api';
import styles from './page.module.css';

function fmtDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

function sourceLabel(asset: DiscoveredAsset) {
  return (asset.asset_class || 'network').replace(/_/g, ' ');
}

function isEsxiAsset(asset: DiscoveredAsset) {
  return asset.raw_facts?.template_key === 'vmware_esxi' || asset.raw_facts?.hypervisor === 'VMware ESXi';
}


function isAvayaAsset(asset: DiscoveredAsset) {
  return asset.asset_class === 'voip' || asset.raw_facts?.template_key === 'avaya_1608';
}


function assetSecondaryLine(asset: DiscoveredAsset) {
  const firmware = (asset.firmware_version || '').trim();
  const extension = String(asset.raw_facts?.extension || '').trim();
  if (isAvayaAsset(asset) && extension) {
    return firmware ? `${firmware} (${extension})` : `(${extension})`;
  }
  return firmware || '—';
}


function formatCount(value: number | null | undefined, label: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  return `${value} ${label}`;
}

function formatCapacity(value: number | null | undefined, label: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  return `${value.toFixed(value >= 10 ? 0 : 2)} GB ${label}`;
}

function esxiSummary(asset: DiscoveredAsset) {
  if (!isEsxiAsset(asset)) return [];
  const inventory = asset.inventory;
  if (!inventory) return [];
  return [
    formatCount(inventory.logical_processors, 'vCPU'),
    formatCapacity(inventory.memory_total_gb, 'RAM'),
    formatCount(inventory.network_interface_count, 'NIC'),
    formatCount(inventory.storage_controller_count, 'controller'),
  ].filter((item): item is string => Boolean(item));
}

function esxiDatastoreSummary(asset: DiscoveredAsset) {
  if (!isEsxiAsset(asset)) return null;
  const datastores = asset.components.filter((component) => component.component_type === 'datastore');
  if (!datastores.length) return null;
  const totalCapacity = datastores.reduce((sum, component) => sum + (component.capacity_gb || 0), 0);
  const label = `${datastores.length} datastore${datastores.length === 1 ? '' : 's'}`;
  if (!totalCapacity) return label;
  return `${label} · ${totalCapacity.toFixed(totalCapacity >= 10 ? 0 : 2)} GB total`;
}

function esxiControllerSummary(asset: DiscoveredAsset) {
  if (!isEsxiAsset(asset)) return null;
  const controllers = asset.components.filter((component) => component.component_type === 'storage_controller');
  if (!controllers.length) return null;
  return controllers.map((component) => `${component.name}${component.status ? ` (${component.status})` : ''}`).join(', ');
}

function esxiHealthSummary(asset: DiscoveredAsset) {
  if (!isEsxiAsset(asset)) return null;
  const summary = asset.health?.summary?.trim();
  if (summary) return summary;
  const overall = asset.health?.overall_status || asset.status;
  return overall || null;
}

function serverName(agent: ProxyAgent | null) {
  if (!agent) return 'Proxy Agent';
  return agent.hostname || agent.ip_address || agent.name || 'Proxy Agent';
}

type PageState = {
  busy: boolean;
  info: string | null;
  lastCommand: ProxyAgentCommand | null;
};

export default function ProxyAgentDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const agentId = params.id as string;
  const customerFromQuery = searchParams.get('customer') || '';

  const [agent, setAgent] = useState<ProxyAgent | null>(null);
  const [assets, setAssets] = useState<DiscoveredAsset[]>([]);
  const [commands, setCommands] = useState<ProxyAgentCommand[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<PageState>({ busy: false, info: null, lastCommand: null });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [agentData, assetsData, commandsData, customersData] = await Promise.all([
        getProxyAgent(agentId),
        getDiscoveredAssets({ proxyAgentId: agentId }),
        getProxyAgentCommands(agentId),
        getCustomers(),
      ]);
      setAgent(agentData);
      setAssets(assetsData);
      setCommands(commandsData);
      setCustomers(customersData);
      setState((prev) => ({
        ...prev,
        lastCommand: prev.lastCommand ?? commandsData[0] ?? null,
      }));
    } catch (err) {
      console.error(err);
      setError('Could not load proxy agent details.');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const customerName = useMemo(() => {
    if (!agent) return customerFromQuery || '—';
    return customers.find((customer) => customer.id === agent.customer_id)?.name || agent.customer_id;
  }, [agent, customerFromQuery, customers]);

  const onlineAssetCount = assets.filter((asset) => (asset.status || '').toLowerCase().includes('ok') || (asset.health?.overall_status || '').toLowerCase() === 'ok').length;
  const alertCount = assets.reduce((sum, asset) => sum + asset.alerts.length, 0);

  const runCommand = async (commandType: 'ping' | 'sync_now') => {
    if (!agent) return;
    setState({
      busy: true,
      info: `${formatCommandType(commandType)} queued...`,
      lastCommand: state.lastCommand,
    });
    try {
      const command = await createProxyAgentCommand(agent.id, {
        command_type: commandType,
        payload: {
          requested_from: 'portal',
          requested_at: new Date().toISOString(),
        },
      });
      setState({
        busy: true,
        info: `${formatCommandType(commandType)} sent to agent.`,
        lastCommand: command,
      });
      setCommands((prev) => [command, ...prev.filter((item) => item.id !== command.id)]);

      for (let attempt = 0; attempt < 18; attempt += 1) {
        const current = await getProxyAgentCommand(agent.id, command.id);
        setState({
          busy: !['acked', 'completed', 'failed'].includes(current.status),
          info: formatCommandStatus(current),
          lastCommand: current,
        });
        setCommands((prev) => [current, ...prev.filter((item) => item.id !== current.id)]);
        if (['acked', 'completed', 'failed'].includes(current.status)) {
          if (current.command_type === 'sync_now' && ['acked', 'completed'].includes(current.status)) {
            void load();
          }
          return;
        }
        await wait(2500);
      }

      setState((prev) => ({
        ...prev,
        busy: false,
        info: 'Command queued but no final response yet.',
      }));
    } catch (err) {
      console.error(err);
      setState((prev) => ({
        ...prev,
        busy: false,
        info: `Could not run ${formatCommandType(commandType)}.`,
      }));
    }
  };

  const handleRegister = async () => {
    if (!agent) return;
    setState((prev) => ({
      ...prev,
      busy: true,
      info: 'Registering agent in portal...',
    }));
    try {
      const updated = await registerProxyAgent(agent.id);
      setAgent(updated);
      setState((prev) => ({
        ...prev,
        busy: false,
        info: 'Agent marked as registered.',
      }));
    } catch (err) {
      console.error(err);
      setState((prev) => ({
        ...prev,
        busy: false,
        info: 'Could not register agent.',
      }));
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.topRow}>
        <Link
          href={`/discovery${customerFromQuery ? `?customer=${customerFromQuery}` : ''}`}
          className={styles.backLink}
        >
          ← Back to Discovery
        </Link>
      </div>

      {loading ? (
        <div className={styles.emptyState}>Loading proxy agent…</div>
      ) : error ? (
        <div className={styles.emptyState}>{error}</div>
      ) : !agent ? (
        <div className={styles.emptyState}>Proxy agent not found.</div>
      ) : (
        <>
          <div className={styles.header}>
            <div>
              <h1 className={styles.title}>{serverName(agent)}</h1>
              <p className={styles.subtitle}>
                {customerName} · {agent.name || 'Proxy Agent record'}
              </p>
            </div>
            <div className={styles.headerActions}>
              {!agent.is_registered ? (
                <button className={styles.primaryBtn} onClick={() => void handleRegister()} disabled={state.busy}>
                  Register
                </button>
              ) : (
                <>
                  <button className={styles.secondaryBtn} onClick={() => void runCommand('ping')} disabled={state.busy}>
                    Ping
                  </button>
                  <button className={styles.primaryBtn} onClick={() => void runCommand('sync_now')} disabled={state.busy}>
                    Sync Now
                  </button>
                </>
              )}
            </div>
          </div>

          <div className={styles.stats}>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>Status</span>
              <strong className={styles.statValue}>{agent.status}</strong>
              <span className={styles.statMeta}>Portal lifecycle state</span>
            </div>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>Assets</span>
              <strong className={styles.statValue}>{assets.length}</strong>
              <span className={styles.statMeta}>{onlineAssetCount} healthy or OK</span>
            </div>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>Alerts</span>
              <strong className={styles.statValue}>{alertCount}</strong>
              <span className={styles.statMeta}>Across all assets from this agent</span>
            </div>
          </div>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2>Agent Information</h2>
              <span>Self-reported metadata and portal registration</span>
            </div>
            <div className={styles.infoGrid}>
              <div className={styles.infoCard}>
                <div className={styles.infoRow}><span>Company</span><strong>{customerName}</strong></div>
                <div className={styles.infoRow}><span>Display Name</span><strong>{agent.name || '—'}</strong></div>
                <div className={styles.infoRow}><span>Server Name</span><strong>{agent.hostname || '—'}</strong></div>
                <div className={styles.infoRow}><span>Agent IP</span><strong>{agent.ip_address || '—'}</strong></div>
                <div className={styles.infoRow}><span>Agent MAC</span><strong>{agent.mac_address || '—'}</strong></div>
                <div className={styles.infoRow}><span>Agent</span><strong>{agent.version ? `Proxy Agent ${agent.version}` : 'Proxy Agent'}</strong></div>
              </div>
              <div className={styles.infoCard}>
                <div className={styles.infoRow}><span>Portal Host</span><strong>{agent.portal_url || '—'}</strong></div>
                <div className={styles.infoRow}><span>Site</span><strong>{agent.site_name || '—'}</strong></div>
                <div className={styles.infoRow}><span>Registered At</span><strong>{fmtDate(agent.registered_at)}</strong></div>
                <div className={styles.infoRow}><span>Last Update</span><strong>{fmtDate(agent.last_checkin)}</strong></div>
                <div className={styles.infoRow}><span>Capabilities</span><strong>{agent.capabilities.length ? agent.capabilities.join(', ') : '—'}</strong></div>
              </div>
            </div>
            <div className={styles.commandState}>{state.info || formatCommandStatus(state.lastCommand)}</div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2>Recent Commands</h2>
              <span>{commands.length} total</span>
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Command</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Acked</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {commands.length === 0 ? (
                    <tr><td colSpan={5} className={styles.emptyCell}>No commands yet.</td></tr>
                  ) : (
                    commands.slice(0, 10).map((command) => (
                      <tr key={command.id}>
                        <td>{formatCommandType(command.command_type)}</td>
                        <td>{command.status}</td>
                        <td>{fmtDate(command.created_at)}</td>
                        <td>{fmtDate(command.acked_at)}</td>
                        <td>{command.result || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2>Discovered Assets</h2>
              <span>{assets.length} linked to this agent</span>
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Serial Number</th>
                    <th>MAC Address</th>
                    <th>Class</th>
                    <th>Vendor / Model</th>
                    <th>IP Address</th>
                    <th>Health</th>
                    <th>Alerts</th>
                    <th>Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.length === 0 ? (
                    <tr><td colSpan={9} className={styles.emptyCell}>No discovered assets reported by this agent yet.</td></tr>
                  ) : (
                    assets.map((asset) => (
                      <tr key={asset.id}>
                        <td>
                          <div className={styles.assetNameCell}>
                            <Link
                              href={`/discovery/assets/${asset.id}?agent=${agentId}${customerFromQuery ? `&customer=${encodeURIComponent(customerFromQuery)}` : ''}`}
                              className={styles.assetLink}
                            >
                              {asset.display_name || asset.serial_number || asset.management_ip || asset.ip_address || 'Unnamed asset'}
                            </Link>
                            <span>{assetSecondaryLine(asset)}</span>
                            {isEsxiAsset(asset) ? (
                              <>
                                {esxiSummary(asset).length ? (
                                  <div className={styles.assetMetaList}>
                                    {esxiSummary(asset).map((item) => (
                                      <span key={item} className={styles.assetMetaPill}>{item}</span>
                                    ))}
                                  </div>
                                ) : null}
                                {esxiDatastoreSummary(asset) ? (
                                  <span className={styles.assetHint}>{esxiDatastoreSummary(asset)}</span>
                                ) : null}
                              </>
                            ) : null}
                          </div>
                        </td>
                        <td>{asset.serial_number || '—'}</td>
                        <td>{asset.mac_address || '—'}</td>
                        <td>{sourceLabel(asset)}</td>
                        <td>
                          <div className={styles.assetNameCell}>
                            <strong>{[asset.vendor, asset.model].filter(Boolean).join(' / ') || '—'}</strong>
                            {isEsxiAsset(asset) && esxiControllerSummary(asset) ? (
                              <span className={styles.assetHint} title={esxiControllerSummary(asset) || ''}>
                                {esxiControllerSummary(asset)}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td>{asset.management_ip || asset.ip_address || '—'}</td>
                        <td>
                          <div className={styles.assetNameCell}>
                            <strong>{asset.health?.overall_status || asset.status || '—'}</strong>
                            {isEsxiAsset(asset) && esxiHealthSummary(asset) ? (
                              <span className={styles.assetHint}>{esxiHealthSummary(asset)}</span>
                            ) : null}
                          </div>
                        </td>
                        <td>{asset.alerts.length}</td>
                        <td>{fmtDate(asset.last_seen_at)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
