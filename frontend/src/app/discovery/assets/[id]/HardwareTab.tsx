'use client';

import { type AssetAlert, type AssetComponent, type DiscoveredAsset } from '@/lib/api';
import styles from './page.module.css';

type Tone = 'ok' | 'warn' | 'fail' | 'neutral';

function formatValue(value: unknown) {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value.trim() || '—';
  return JSON.stringify(value);
}

function fmtDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatRelativeTime(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.round(diffMs / 60000);
  if (Math.abs(diffMinutes) < 1) return 'just now';
  if (Math.abs(diffMinutes) < 60) return `${diffMinutes} min ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) return `${diffHours} hr ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays} day${Math.abs(diffDays) === 1 ? '' : 's'} ago`;
}

function rawObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function rawArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : [];
}

function componentStatus(component: AssetComponent) {
  return component.health || component.status || '';
}

function toneForStatus(status: string | null | undefined): Tone {
  const text = String(status || '').trim().toLowerCase();
  if (!text) return 'neutral';
  if (['ok', 'healthy', 'online', 'ready', 'optimal', 'running', 'info', 'informational'].includes(text)) return 'ok';
  if (['critical', 'failed', 'non-recoverable', 'missing', 'lost', 'down', 'offline'].includes(text)) return 'fail';
  if (['warning', 'warn', 'non-critical', 'degraded', 'ubunsp', 'unknown'].includes(text)) return 'warn';
  return 'neutral';
}

function badgeClassName(tone: Tone) {
  if (tone === 'ok') return `${styles.serverBadge} ${styles.serverBadgeOk}`;
  if (tone === 'warn') return `${styles.serverBadge} ${styles.serverBadgeWarn}`;
  if (tone === 'fail') return `${styles.serverBadge} ${styles.serverBadgeFail}`;
  return `${styles.serverBadge} ${styles.serverBadgeNeutral}`;
}

function isEsxiAsset(asset: DiscoveredAsset) {
  return asset.raw_facts?.template_key === 'vmware_esxi' || asset.raw_facts?.hypervisor === 'VMware ESXi';
}

function isIdracAsset(asset: DiscoveredAsset) {
  return asset.asset_class === 'idrac' || asset.raw_facts?.template_key === 'dell_idrac';
}

function isServerLike(asset: DiscoveredAsset) {
  return ['server', 'idrac'].includes(asset.asset_class) || asset.raw_facts?.template_key === 'vmware_esxi' || asset.raw_facts?.template_key === 'dell_idrac';
}

function componentTypeRows(asset: DiscoveredAsset, type: string) {
  return (asset.components ?? []).filter((component) => component.component_type === type);
}

function deriveAlertComponent(message: string, fallback: string) {
  if (/power supply\s*\d+/i.test(message)) {
    const match = message.match(/power supply\s*\d+/i);
    return match?.[0] || 'Power subsystem';
  }
  if (/redundancy/i.test(message) || /power/i.test(message)) return 'Power subsystem';
  if (/dimm|memory|ecc/i.test(message)) return 'Memory';
  if (/fan|cooling|thermal|temperature/i.test(message)) return 'Cooling';
  if (/disk|raid|storage|controller|virtual disk/i.test(message)) return 'Storage subsystem';
  return fallback || 'System';
}

function alertEventTime(alert: AssetAlert) {
  const extra = rawObject(alert.extra_json);
  const eventTime = typeof extra.event_time === 'string' ? extra.event_time : '';
  return eventTime || alert.first_seen_at || alert.last_seen_at || '';
}

function sortByDateDesc<T>(items: T[], getValue: (item: T) => string) {
  return [...items].sort((a, b) => {
    const left = getValue(a);
    const right = getValue(b);
    const leftTime = new Date(left).getTime();
    const rightTime = new Date(right).getTime();
    if (!Number.isNaN(leftTime) && !Number.isNaN(rightTime)) return rightTime - leftTime;
    return right.localeCompare(left);
  });
}

function normalizeSelEntries(asset: DiscoveredAsset) {
  const rawFacts = rawObject(asset.raw_facts);
  const racadmSelEntries = rawArray(rawFacts.racadm_sel_entries);
  const racadmEntries = rawArray(rawFacts.racadm_entries);
  const legacyDiag = rawObject(rawFacts.idrac_racadm_diagnostics);
  const legacyEntries = rawArray(legacyDiag.entries);
  const sourceEntries = racadmSelEntries.length ? racadmSelEntries : racadmEntries.length ? racadmEntries : legacyEntries;

  return sortByDateDesc(
    sourceEntries.map((entry, index) => {
      const message = String(entry.message || '').trim();
      const rawSeverity = String(entry.severity || '').trim() || 'Unknown';
      const scope = String(entry.scope || '').trim();
      const eventTime = String(entry.event_time || entry.timestamp || '').trim();
      const recordId = String(entry.record_id || '').trim();
      return {
        key: recordId || `${eventTime}-${message}-${index}`,
        eventTime,
        severity: rawSeverity,
        component: deriveAlertComponent(message, scope),
        message,
      };
    }).filter((entry) => entry.message),
    (entry) => entry.eventTime,
  );
}

function latestDiskObservations(
  entries: Array<{ key: string; eventTime: string; severity: string; component: string; message: string }>,
) {
  const latestByDisk = new Map<
    string,
    { key: string; diskLabel: string; state: string; tone: Tone; eventTime: string; message: string }
  >();

  for (const entry of entries) {
    const match = entry.message.match(/\bDrive\s+(\d+)\b/i);
    if (!match) continue;

    const diskLabel = `Drive ${match[1]}`;
    let state = 'Observed';
    let tone: Tone = 'neutral';
    const text = entry.message.toLowerCase();

    if (/failed|missing/.test(text)) {
      state = 'Failed / Missing';
      tone = 'fail';
    } else if (/removed/.test(text)) {
      state = 'Removed';
      tone = 'fail';
    } else if (/installed|restored|inserted/.test(text)) {
      state = 'Installed';
      tone = 'ok';
    } else if (/degraded|rebuild|rebuilding|predictive|warning/.test(text)) {
      state = 'Warning';
      tone = 'warn';
    } else if (/online|ready/.test(text)) {
      state = 'Online';
      tone = 'ok';
    }

    if (!latestByDisk.has(diskLabel)) {
      latestByDisk.set(diskLabel, {
        key: `${diskLabel}-${entry.key}`,
        diskLabel,
        state,
        tone,
        eventTime: entry.eventTime,
        message: entry.message,
      });
    }
  }

  return [...latestByDisk.values()];
}

function renderBadge(label: string, tone: Tone) {
  return <span className={badgeClassName(tone)}>{label || 'Unknown'}</span>;
}

function formatCapacityGb(value: unknown) {
  if (value == null) return '—';
  const numeric = typeof value === 'number' ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(numeric)) return formatValue(value);
  return Number.isInteger(numeric) ? `${numeric} GB` : `${numeric.toFixed(2)} GB`;
}

function toNumber(value: unknown) {
  if (value == null || value === '') return null;
  const numeric = typeof value === 'number' ? value : Number.parseFloat(String(value));
  return Number.isFinite(numeric) ? numeric : null;
}

function kbToGb(value: unknown) {
  const numeric = toNumber(value);
  return numeric == null ? null : numeric / (1024 * 1024);
}

function hrDeviceStatusLabel(value: unknown) {
  switch (String(value || '').trim()) {
    case '2':
      return 'OK';
    case '3':
      return 'Warning';
    case '4':
      return 'Testing';
    case '5':
      return 'Critical';
    default:
      return 'Unknown';
  }
}

function processorRows(rawFacts: Record<string, unknown>) {
  const esxiDetails = rawObject(rawFacts.esxi_details);
  const devices = rawArray(esxiDetails.devices);

  return devices
    .filter((device) => String(device.type || '').trim() === '1.3.6.1.2.1.25.3.1.3')
    .map((device, index) => {
      const description = String(device.description || '').trim();
      const pkgMatch = description.match(/Pkg\/ID\/Node:\s*([0-9]+)/i);
      const model = description.includes('Node:')
        ? description.split('Node:').slice(1).join('Node:').trim().replace(/^CPU\s+\d+\s+/i, '')
        : description;
      return {
        key: `${pkgMatch?.[1] || index}-${description}`,
        socket: pkgMatch?.[1] ? `CPU${Number(pkgMatch[1]) + 1}` : `CPU${index + 1}`,
        model: model || description || '—',
        status: hrDeviceStatusLabel(device.status),
      };
    });
}

function formatPowerValue(value: string) {
  if (!value) return '—';
  return /\bw\b/i.test(value) ? value : `${value} W`;
}

function esxiAlertRows(asset: DiscoveredAsset) {
  return sortByDateDesc(asset.alerts ?? [], (alert) => alertEventTime(alert)).map((alert, index) => ({
    key: `${alert.id}-${index}`,
    eventTime: alertEventTime(alert),
    severity: alert.severity || 'Unknown',
    component: deriveAlertComponent(alert.message || '', alert.source || 'System'),
    message: alert.message || '—',
  }));
}

function esxiDatastores(rawFacts: Record<string, unknown>) {
  const esxiDetails = rawObject(rawFacts.esxi_details);
  const storage = rawArray(esxiDetails.storage);

  return storage
    .filter((item) => String(item.description || '').trim().startsWith('/vmfs/volumes/'))
    .map((item, index) => {
      const description = String(item.description || '').trim();
      const allocationUnits = toNumber(item.allocation_units) ?? 0;
      const sizeUnits = toNumber(item.size) ?? 0;
      const usedUnits = toNumber(item.used) ?? 0;
      const totalBytes = allocationUnits * sizeUnits;
      const usedBytes = allocationUnits * usedUnits;
      const freeBytes = Math.max(totalBytes - usedBytes, 0);
      return {
        key: `${description}-${index}`,
        name: description.split('/').filter(Boolean).at(-1) || description,
        totalGb: totalBytes ? totalBytes / (1024 ** 3) : null,
        usedGb: usedBytes ? usedBytes / (1024 ** 3) : null,
        freeGb: freeBytes ? freeBytes / (1024 ** 3) : null,
      };
    });
}

function EsxiHardwareTab({ asset }: { asset: DiscoveredAsset }) {
  const rawFacts = rawObject(asset.raw_facts);
  const inventory = asset.inventory;
  const esxiDetails = rawObject(rawFacts.esxi_details);
  const vmwareMetrics = rawObject(esxiDetails.vmware_metrics);
  const physicalDisks = componentTypeRows(asset, 'physical_disk');
  const virtualDisks = componentTypeRows(asset, 'virtual_disk');
  const storageControllers = componentTypeRows(asset, 'storage_controller');
  const alerts = esxiAlertRows(asset);
  const datastores = esxiDatastores(rawFacts);
  const titleModel = asset.model || asset.display_name || asset.management_ip || asset.ip_address || 'ESXi host';
  const titleLabel = `${titleModel} (ESXi)`;
  const headerStatus = asset.health?.overall_status || asset.status || 'Unknown';
  const headerTone = toneForStatus(headerStatus);
  const primaryManagementIp = asset.management_ip || asset.ip_address;
  const serviceTag = asset.serial_number || '—';
  const logicalCpuCount = inventory?.logical_processors;
  const totalMemoryGb = inventory?.memory_total_gb ?? kbToGb(vmwareMetrics.memory_total_kb);
  const usedMemoryGb = kbToGb(vmwareMetrics.memory_used_kb);
  const freeMemoryGb = kbToGb(vmwareMetrics.memory_free_kb);
  const raidSummary = typeof inventory?.raid_summary === 'string' ? inventory.raid_summary : '';
  const esxiVersion = typeof rawFacts.esxi_version === 'string' ? rawFacts.esxi_version : asset.firmware_version;
  const hypervisorLabel = typeof rawFacts.hypervisor === 'string' ? rawFacts.hypervisor : 'VMware ESXi';
  const networkInterfaceCount = typeof inventory?.network_interface_count === 'number' ? inventory.network_interface_count : null;
  const processors = processorRows(rawFacts);
  const assignedSlots = new Set<string>();
  const virtualGroups = virtualDisks.map((virtualDisk) => {
    const extra = rawObject(virtualDisk.extra_json);
    const memberSlots = Array.isArray(extra.member_slots)
      ? extra.member_slots.map((item) => String(item || '').trim()).filter(Boolean)
      : [];
    memberSlots.forEach((slot) => assignedSlots.add(slot));
    const members = physicalDisks.filter((disk) => memberSlots.includes(String(disk.slot || '').trim()));
    return { virtualDisk, extra, members };
  });
  const unassignedDisks = physicalDisks.filter((disk) => !assignedSlots.has(String(disk.slot || '').trim()));
  const hasStorageData = virtualGroups.length > 0 || unassignedDisks.length > 0;
  const hasMemoryData = totalMemoryGb != null || usedMemoryGb != null || freeMemoryGb != null;

  return (
    <div className={styles.serverDash}>
      <div className={styles.serverDashHeader}>
        <div>
          <div className={styles.serverDashBreadcrumbs}>Inventory / Servers / {titleModel}</div>
          <div className={styles.serverDashTitleRow}>
            <h2 className={styles.serverDashTitle}>{titleLabel}</h2>
            {renderBadge(headerStatus, headerTone)}
          </div>
        </div>
        <div className={styles.serverDashPolling}>
          <span className={styles.serverDashPollingLabel}>Last Polled (SNMP)</span>
          <strong>{formatRelativeTime(asset.last_seen_at)}</strong>
        </div>
      </div>

      <div className={styles.serverDashGrid}>
        <section className={`${styles.serverCard} ${styles.serverCardSpan2}`}>
          <div className={styles.serverCardHeader}>Global Information</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>System Health</span>
                <span className={styles.serverKvValue}>{renderBadge(headerStatus, headerTone)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Model Name</span>
                <span className={styles.serverKvValue}>{formatValue(asset.model || asset.display_name)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Service Tag</span>
                <span className={styles.serverKvValue}><code className={styles.serverCode}>{formatValue(serviceTag)}</code></span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Management IP</span>
                <span className={styles.serverKvValue}>{formatValue(primaryManagementIp)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Hypervisor</span>
                <span className={styles.serverKvValue}>{formatValue(hypervisorLabel)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Version</span>
                <span className={styles.serverKvValue}>{formatValue(esxiVersion)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Environmental</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverEmptyNote}>
              Environmental telemetry such as inlet temperature, power draw, and PSU status is not exposed by the current ESXi SNMP collector.
            </div>
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>
            <div className={styles.serverHeaderSplit}>
              <span>Processors (CPU)</span>
              <span className={styles.serverHeaderMetric}>
                Logical CPUs: {logicalCpuCount ?? '—'}
              </span>
            </div>
          </div>
          <div className={styles.serverTableWrap}>
            <table className={styles.serverTable}>
              <thead>
                <tr>
                  <th>Socket</th>
                  <th>Processor Model</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {processors.length ? processors.map((processor) => (
                  <tr key={processor.key}>
                    <td>{processor.socket}</td>
                    <td>{processor.model}</td>
                    <td>{renderBadge(processor.status, toneForStatus(processor.status))}</td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={3}>CPU socket inventory is not exposed in the current ESXi SNMP payload.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>
            <div className={styles.serverHeaderSplit}>
              <span>Memory (RAM)</span>
              <span className={styles.serverHeaderMetric}>Total Capacity: {formatCapacityGb(totalMemoryGb)}</span>
            </div>
          </div>
          {hasMemoryData ? (
            <div className={styles.serverTableWrap}>
              <table className={styles.serverTable}>
                <thead>
                  <tr>
                    <th>Slot Label</th>
                    <th>Capacity</th>
                    <th>Type</th>
                    <th>Speed</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Host total</td>
                    <td>{formatCapacityGb(totalMemoryGb)}</td>
                    <td>Summary only</td>
                    <td>Not exposed</td>
                    <td>{renderBadge('OK', 'ok')}</td>
                  </tr>
                  <tr>
                    <td>Memory used</td>
                    <td>{formatCapacityGb(usedMemoryGb)}</td>
                    <td>Telemetry</td>
                    <td>—</td>
                    <td>{renderBadge('Observed', 'neutral')}</td>
                  </tr>
                  <tr>
                    <td>Memory free</td>
                    <td>{formatCapacityGb(freeMemoryGb)}</td>
                    <td>Telemetry</td>
                    <td>—</td>
                    <td>{renderBadge('Observed', 'neutral')}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.serverEmptyNote}>
              Host memory summary is not exposed in the current ESXi SNMP payload.
            </div>
          )}
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Storage Subsystem (RAID &amp; Disks)</div>
          <div className={styles.serverCardBody}>
            {hasStorageData ? (
              <>
                {virtualGroups.map(({ virtualDisk, extra, members }) => {
                  const virtualLabel = virtualDisk.name || 'Virtual Disk';
                  const raidType = typeof extra.raid_type === 'string' ? extra.raid_type : '';
                  const state = typeof extra.state === 'string' ? extra.state : virtualDisk.status || '';
                  return (
                    <div key={virtualDisk.id} className={styles.serverStorageGroup}>
                      <div className={styles.serverStorageHeader}>
                        <div className={styles.serverStorageTitle}>
                          <span>{virtualLabel.replace(/^VD/i, 'Virtual Disk ')}</span>
                          <span className={styles.serverStorageSubtitle}>{raidType || 'RAID'}</span>
                        </div>
                        <div>{renderBadge(state || virtualDisk.status || 'Unknown', toneForStatus(state || virtualDisk.status))}</div>
                      </div>
                      <ul className={styles.serverDiskList}>
                        {members.length ? members.map((disk) => {
                          const extraDisk = rawObject(disk.extra_json);
                          const sizeText = typeof extraDisk.size_text === 'string' ? extraDisk.size_text : formatCapacityGb(disk.capacity_gb);
                          const model = [disk.manufacturer, disk.model].filter(Boolean).join(' ').trim() || disk.name || 'Unknown / Missing';
                          const stateText = typeof extraDisk.state === 'string' ? extraDisk.state : disk.status || disk.health || 'Unknown';
                          return (
                            <li key={disk.id} className={styles.serverDiskItem}>
                              <div className={styles.serverDiskSlot}>Bay {disk.slot || '—'}</div>
                              <div>
                                <div className={styles.serverDiskModel}>{model} ({sizeText || '—'})</div>
                              </div>
                              <div>{renderBadge(stateText, toneForStatus(stateText))}</div>
                            </li>
                          );
                        }) : (
                          <li className={styles.serverDiskItem}>
                            <div className={styles.serverDiskSlot}>—</div>
                            <div>
                              <div className={styles.serverDiskModel}>No member disks exposed for this virtual disk.</div>
                            </div>
                            <div>{renderBadge('Unknown', 'neutral')}</div>
                          </li>
                        )}
                      </ul>
                    </div>
                  );
                })}

                {unassignedDisks.length ? (
                  <div className={styles.serverStorageGroup}>
                    <div className={styles.serverStorageHeader}>
                      <div className={styles.serverStorageTitle}>
                        <span>Unassigned Physical Disks</span>
                        <span className={styles.serverStorageSubtitle}>Non-RAID / Standalone</span>
                      </div>
                    </div>
                    <ul className={styles.serverDiskList}>
                      {unassignedDisks.map((disk) => {
                        const extraDisk = rawObject(disk.extra_json);
                        const sizeText = typeof extraDisk.size_text === 'string' ? extraDisk.size_text : formatCapacityGb(disk.capacity_gb);
                        const mediaSuffix = typeof extraDisk.media_type === 'string' && extraDisk.media_type ? ` ${extraDisk.media_type}` : '';
                        const model = [disk.manufacturer, disk.model].filter(Boolean).join(' ').trim() || disk.name || 'Unknown disk';
                        const stateText = typeof extraDisk.state === 'string' ? extraDisk.state : disk.status || disk.health || 'Unknown';
                        return (
                          <li key={disk.id} className={styles.serverDiskItem}>
                            <div className={styles.serverDiskSlot}>Bay {disk.slot || '—'}</div>
                            <div>
                              <div className={styles.serverDiskModel}>{model} ({sizeText || '—'}){mediaSuffix}</div>
                            </div>
                            <div>{renderBadge(stateText, toneForStatus(stateText))}</div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : datastores.length ? (
              <>
                <div className={styles.serverEmptyNote}>
                  RAID topology and bay-level disk states are not exposed by the current ESXi SNMP collector. The table below shows datastore capacity gathered from the host.
                </div>
                <div className={styles.serverTableWrap}>
                  <table className={styles.serverTable}>
                    <thead>
                      <tr>
                        <th>Datastore</th>
                        <th>Total</th>
                        <th>Used</th>
                        <th>Free</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datastores.map((datastore) => (
                        <tr key={datastore.key}>
                          <td>{datastore.name}</td>
                          <td>{formatCapacityGb(datastore.totalGb)}</td>
                          <td>{formatCapacityGb(datastore.usedGb)}</td>
                          <td>{formatCapacityGb(datastore.freeGb)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className={styles.serverKvList}>
                  <div className={styles.serverKvItem}>
                    <span className={styles.serverKvLabel}>Datastores</span>
                    <span className={styles.serverKvValue}>{datastores.length}</span>
                  </div>
                  <div className={styles.serverKvItem}>
                    <span className={styles.serverKvLabel}>Storage Controllers</span>
                    <span className={styles.serverKvValue}>{storageControllers.length || '—'}</span>
                  </div>
                  <div className={styles.serverKvItem}>
                    <span className={styles.serverKvLabel}>Network Interfaces</span>
                    <span className={styles.serverKvValue}>{networkInterfaceCount ?? '—'}</span>
                  </div>
                </div>
              </>
            ) : (
              <div className={styles.serverEmptyNote}>
                RAID, physical disk, and datastore inventory are not exposed in the current ESXi payload.
                {raidSummary ? ` Reported RAID summary: ${raidSummary}.` : ''}
              </div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3} ${styles.serverAlertCard}`}>
          <div className={styles.serverCardHeader}>Active System Alerts</div>
          <div className={styles.serverTableWrap}>
            <table className={styles.serverTable}>
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Timestamp</th>
                  <th>Component</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {alerts.length ? alerts.slice(0, 20).map((entry) => (
                  <tr key={entry.key}>
                    <td>{renderBadge(entry.severity, toneForStatus(entry.severity))}</td>
                    <td>{fmtDate(entry.eventTime)}</td>
                    <td>{entry.component || 'System'}</td>
                    <td>{entry.message}</td>
                  </tr>
                )) : (
                  <tr>
                    <td>{renderBadge('Info', 'neutral')}</td>
                    <td>—</td>
                    <td>System</td>
                    <td>No structured ESXi hardware alerts are collected by the current SNMP path.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className={styles.serverDashNotice}>
        This ESXi dashboard uses only currently collected SNMP data. CPU and memory are shown as host-level summaries, datastores appear when exposed by Host Resources, and RAID bay-level details appear only when separate disk inventory is present.
        {logicalCpuCount ? ` Current logical CPU count: ${logicalCpuCount}.` : ''}
      </div>
    </div>
  );
}

function GenericHardwareTab({ asset }: { asset: DiscoveredAsset }) {
  const inv = asset.inventory;
  const components = asset.components ?? [];

  const memoryModules = components.filter((c) => c.component_type === 'memory_module');
  const physicalDisks = components.filter((c) => c.component_type === 'physical_disk');
  const networkInterfaces = components.filter((c) => c.component_type === 'network_interface');
  const powerSupplies = components.filter((c) => c.component_type === 'power_supply');

  const sysOverview = [
    ['Vendor', asset.vendor],
    ['Model', asset.model],
    ['Serial Number', asset.serial_number],
    ['BIOS / Firmware', asset.firmware_version],
    ['Asset Class', asset.asset_class],
  ];

  const computeData = [
    ['Processor Vendor', inv?.processor_vendor],
    ['Processor Model', inv?.processor_model],
    ['Processor Count', inv?.processor_count],
    ['Physical Cores', inv?.physical_cores],
    ['Logical Processors', inv?.logical_processors],
  ];

  const memData = [
    ['Total Memory (GB)', inv?.memory_total_gb],
    ['Memory Slots Count', inv?.memory_slot_count],
    ['Memory Slots Used', inv?.memory_slots_used],
    ['Modules Detected', memoryModules.length || null],
  ];

  const storageData = [
    ['Total Disk Space (GB)', inv?.disk_total_gb],
    ['Physical Disk Count', inv?.physical_disk_count],
    ['Virtual Disk Count', inv?.virtual_disk_count],
    ['Storage Controllers', inv?.storage_controller_count],
    ['RAID Summary', inv?.raid_summary],
  ];

  return (
    <div className={styles.section} style={{ gap: '20px' }}>
      <div className={styles.infoGrid}>
        <div className={styles.infoCard}>
          <h3 className={styles.profileTitle}>System Overview</h3>
          {sysOverview.map(([label, value]) => (
            <div key={label} className={styles.infoRow}>
              <span>{label}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>

        <div className={styles.infoCard}>
          <h3 className={styles.profileTitle}>Compute</h3>
          {computeData.map(([label, value]) => (
            <div key={label} className={styles.infoRow}>
              <span>{label}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>

        <div className={styles.infoCard}>
          <h3 className={styles.profileTitle}>Memory</h3>
          {memData.map(([label, value]) => (
            <div key={label} className={styles.infoRow}>
              <span>{label}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>

        <div className={styles.infoCard}>
          <h3 className={styles.profileTitle}>Storage Subsystem</h3>
          {storageData.map(([label, value]) => (
            <div key={label} className={styles.infoRow}>
              <span>{label}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>
      </div>

      {networkInterfaces.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Network Interfaces</h2>
            <span>{networkInterfaces.length} found</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>MAC / Details</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {networkInterfaces.map((c) => {
                  const extra = c.extra_json ?? {};
                  const mac = typeof extra.mac_address === 'string' ? extra.mac_address : c.serial_number;
                  const speed = typeof extra.speed === 'string' || typeof extra.speed === 'number' ? `Speed: ${extra.speed}` : '';
                  return (
                    <tr key={c.id}>
                      <td>{c.name || c.model || '—'}</td>
                      <td>{[mac, speed].filter(Boolean).join(' · ') || '—'}</td>
                      <td>{c.status || c.health || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {physicalDisks.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Physical Disks</h2>
            <span>{physicalDisks.length} found</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Slot / Name</th>
                  <th>Model & Manufacturer</th>
                  <th>Capacity</th>
                  <th>Serial / Details</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {physicalDisks.map((c) => {
                  const extra = c.extra_json ?? {};
                  const type = typeof extra.media_type === 'string' ? extra.media_type : typeof extra.raid_type === 'string' ? extra.raid_type : '';
                  return (
                    <tr key={c.id}>
                      <td>{c.slot || c.name || '—'}</td>
                      <td>{[c.manufacturer, c.model].filter(Boolean).join(' ') || '—'}</td>
                      <td>{c.capacity_gb != null ? `${c.capacity_gb} GB` : '—'}</td>
                      <td>{[c.serial_number, type].filter(Boolean).join(' · ') || '—'}</td>
                      <td>{c.status || c.health || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {powerSupplies.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Power Supplies</h2>
            <span>{powerSupplies.length} found</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Slot / Name</th>
                  <th>Model / Details</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {powerSupplies.map((c) => (
                  <tr key={c.id}>
                    <td>{c.slot || c.name || '—'}</td>
                    <td>{[c.manufacturer, c.model, c.serial_number].filter(Boolean).join(' ') || '—'}</td>
                    <td>{c.status || c.health || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function IdracHardwareTab({ asset }: { asset: DiscoveredAsset }) {
  const rawFacts = rawObject(asset.raw_facts);
  const details = rawObject(rawFacts.dell_details);
  const powerSupplies = componentTypeRows(asset, 'power_supply');
  const headerStatus = asset.health?.overall_status || asset.status || 'Unknown';
  const headerTone = toneForStatus(headerStatus);
  const serviceTag = details.service_tag || asset.serial_number;
  const modelName = asset.model || String(details.controller_model || '').trim() || 'Unknown model';
  const globalCode = String(rawFacts.global_status_code || details.global_status || '').trim();
  const selEntries = normalizeSelEntries(asset);
  const displayAlerts = selEntries.length
    ? selEntries
    : sortByDateDesc(asset.alerts, (alert) => alertEventTime(alert)).map((alert, index) => ({
        key: `${alert.id}-${index}`,
        eventTime: alertEventTime(alert),
        severity: alert.severity || 'Unknown',
        component: deriveAlertComponent(alert.message || '', alert.source || 'System'),
        message: alert.message || '—',
      }));

  const primaryManagementIp = asset.management_ip || asset.ip_address;
  const titleModel = modelName || asset.display_name || asset.management_ip || asset.ip_address || 'Server';
  const titleLabel = rawFacts.template_key === 'dell_idrac' || asset.asset_class === 'idrac'
    ? `${titleModel} (iDRAC6)`
    : titleModel;
  const managementController = asset.components?.find((component) => component.component_type === 'management_controller');
  const managementExtra = rawObject(managementController?.extra_json);
  const currentPowerDraw = typeof managementExtra.actual_power_consumption === 'string' ? managementExtra.actual_power_consumption : '';
  const peakPowerDraw = typeof managementExtra.peak_power_consumption === 'string' ? managementExtra.peak_power_consumption : '';
  const diskObservations = latestDiskObservations(displayAlerts);

  return (
    <div className={styles.serverDash}>
      <div className={styles.serverDashHeader}>
        <div>
          <div className={styles.serverDashBreadcrumbs}>Inventory / Servers / {titleModel}</div>
          <div className={styles.serverDashTitleRow}>
            <h2 className={styles.serverDashTitle}>{titleLabel}</h2>
            {renderBadge(globalCode ? `${headerStatus} (${globalCode})` : headerStatus, headerTone)}
          </div>
        </div>
        <div className={styles.serverDashPolling}>
          <span className={styles.serverDashPollingLabel}>Last Polled (SNMP)</span>
          <strong>{formatRelativeTime(asset.last_seen_at)}</strong>
        </div>
      </div>

      <div className={styles.serverDashNotice}>
        Legacy iDRAC6 exposes limited hardware inventory. CPU and RAM sections stay hidden, and storage below is derived from disk events in SEL history rather than live RAID SNMP tables.
      </div>

      <div className={styles.serverDashGrid}>
        <section className={`${styles.serverCard} ${styles.serverCardSpan2}`}>
          <div className={styles.serverCardHeader}>Global Information</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>System Health</span>
                <span className={styles.serverKvValue}>{renderBadge(globalCode ? `${headerStatus} (${globalCode})` : headerStatus, headerTone)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Model Name</span>
                <span className={styles.serverKvValue}>{formatValue(modelName)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Service Tag</span>
                <span className={styles.serverKvValue}><code className={styles.serverCode}>{formatValue(serviceTag)}</code></span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Management IP</span>
                <span className={styles.serverKvValue}>{formatValue(primaryManagementIp)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Environmental</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              {currentPowerDraw ? (
                <div className={styles.serverKvItem}>
                  <span className={styles.serverKvLabel}>Current Power Draw</span>
                  <span className={styles.serverKvValue}>{currentPowerDraw}</span>
                </div>
              ) : null}
              {peakPowerDraw ? (
                <div className={styles.serverKvItem}>
                  <span className={styles.serverKvLabel}>Peak Power Draw</span>
                  <span className={styles.serverKvValue}>{peakPowerDraw}</span>
                </div>
              ) : null}
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>PSU 1 Status</span>
                <span className={styles.serverKvValue}>
                  {powerSupplies[0] ? renderBadge(componentStatus(powerSupplies[0]) || 'Unknown', toneForStatus(componentStatus(powerSupplies[0]))) : renderBadge('Not exposed', 'neutral')}
                </span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>PSU 2 Status</span>
                <span className={styles.serverKvValue}>
                  {/power supply 2 is lost/i.test(String(rawFacts.alert_detail_summary || '')) || displayAlerts.some((entry) => /power supply 2 is lost/i.test(entry.message))
                    ? renderBadge('Critical', 'fail')
                    : powerSupplies[1]
                      ? renderBadge(componentStatus(powerSupplies[1]) || 'Unknown', toneForStatus(componentStatus(powerSupplies[1])))
                      : renderBadge('Not exposed', 'neutral')}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Storage Subsystem (RAID &amp; Disks)</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverEmptyNote}>
              Live RAID inventory is not exposed by this iDRAC6. The rows below show the latest observed disk states derived from SEL history using the same disk-oriented mapping categories as the Zabbix template.
            </div>

            {diskObservations.length ? (
              <div className={styles.serverStorageGroup}>
                <div className={styles.serverStorageHeader}>
                  <div className={styles.serverStorageTitle}>
                    <span>Observed Physical Disks</span>
                    <span className={styles.serverStorageSubtitle}>SEL-derived state</span>
                  </div>
                </div>
                <ul className={styles.serverDiskList}>
                  {diskObservations.map((disk) => (
                    <li key={disk.key} className={styles.serverDiskItem}>
                      <div className={styles.serverDiskSlot}>{disk.diskLabel}</div>
                      <div>
                        <div className={styles.serverDiskModel}>{disk.message}</div>
                        <div className={styles.serverKvValueSub}>{fmtDate(disk.eventTime)}</div>
                      </div>
                      <div>{renderBadge(disk.state, disk.tone)}</div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className={styles.serverEmptyNote}>
                No disk-related SEL events are currently available from this iDRAC6.
              </div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3} ${styles.serverAlertCard}`}>
          <div className={styles.serverCardHeader}>Active System Alerts</div>
          <div className={styles.serverTableWrap}>
            <table className={styles.serverTable}>
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Timestamp</th>
                  <th>Component</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {displayAlerts.length ? displayAlerts.slice(0, 20).map((entry) => (
                  <tr key={entry.key}>
                    <td>{renderBadge(entry.severity, toneForStatus(entry.severity))}</td>
                    <td>{fmtDate(entry.eventTime)}</td>
                    <td>{entry.component || 'System'}</td>
                    <td>{entry.message}</td>
                  </tr>
                )) : (
                  <tr>
                    <td>{renderBadge('Info', 'neutral')}</td>
                    <td>—</td>
                    <td>System</td>
                    <td>No structured alert history in the current payload yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

export function HardwareTab({ asset }: { asset: DiscoveredAsset }) {
  if (!isServerLike(asset)) {
    return <GenericHardwareTab asset={asset} />;
  }

  if (isEsxiAsset(asset)) {
    return <EsxiHardwareTab asset={asset} />;
  }

  if (isIdracAsset(asset)) {
    return <IdracHardwareTab asset={asset} />;
  }

  return <GenericHardwareTab asset={asset} />;
}
