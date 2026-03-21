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

export function HardwareTab({ asset }: { asset: DiscoveredAsset }) {
  if (!isServerLike(asset)) {
    return <GenericHardwareTab asset={asset} />;
  }

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
