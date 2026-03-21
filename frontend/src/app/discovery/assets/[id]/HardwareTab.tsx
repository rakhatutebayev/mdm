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

function rawIdracTables(asset: DiscoveredAsset) {
  const rawFacts = rawObject(asset.raw_facts);
  const tables = rawObject(rawFacts.idrac_component_tables);
  return {
    powerSupplies: rawArray(tables.power_supplies),
    temperatureProbes: rawArray(tables.temperature_probes),
    memoryDevices: rawArray(tables.memory_devices),
    coolingDevices: rawArray(tables.cooling_devices),
  };
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
  const inventory = asset.inventory;
  const components = asset.components ?? [];
  const cpus = componentTypeRows(asset, 'cpu');
  const memoryModules = componentTypeRows(asset, 'memory_module');
  const physicalDisks = componentTypeRows(asset, 'physical_disk');
  const virtualDisks = componentTypeRows(asset, 'virtual_disk');
  const raidControllers = componentTypeRows(asset, 'raid_controller');
  const managementController = componentTypeRows(asset, 'management_controller')[0];
  const networkInterfaces = componentTypeRows(asset, 'network_interface').concat(componentTypeRows(asset, 'nic'));
  const powerSupplies = componentTypeRows(asset, 'power_supply');
  const idracTables = rawIdracTables(asset);
  const managementExtra = rawObject(managementController?.extra_json);
  const racadmDetails = rawObject(rawFacts.idrac_racadm_details);
  const racadmGetsysinfo = rawObject(racadmDetails.getsysinfo);
  const racadmSections = rawObject(racadmGetsysinfo.sections);
  const racadmGetniccfg = rawObject(racadmDetails.getniccfg);
  const racadmNiccfgSections = rawObject(racadmGetniccfg.sections);
  const racadmIpv4 = rawObject(racadmNiccfgSections.ipv4_settings);
  const racadmLomStatus = rawObject(racadmNiccfgSections.lom_status);
  const temperatureStatus = asset.health?.thermal_status || '';
  const temperatureProbe = idracTables.temperatureProbes[0] ?? null;
  const powerTone = toneForStatus(asset.health?.power_status || rawFacts.critical_source_summary as string | undefined);
  const headerStatus = asset.health?.overall_status || asset.status || 'Unknown';
  const headerTone = toneForStatus(headerStatus);
  const serviceTag = details.service_tag || asset.serial_number;
  const modelName = asset.model || String(details.controller_model || '').trim() || 'Unknown model';
  const globalCode = String(rawFacts.global_status_code || details.global_status || '').trim();
  const totalMemory = inventory?.memory_total_gb;
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

  const diskMembership = new Map<string, AssetComponent[]>();
  for (const disk of physicalDisks) {
    const extra = rawObject(disk.extra_json);
    const members = Array.isArray(extra.member_slots) ? extra.member_slots.map((value) => String(value)) : [];
    for (const member of members) {
      const current = diskMembership.get(member) || [];
      current.push(disk);
      diskMembership.set(member, current);
    }
  }
  const assignedDiskKeys = new Set<string>();
  const primaryManagementIp = asset.management_ip || asset.ip_address || String(racadmIpv4.ip_address || '').trim();
  const managementUrl = String(details.management_url || rawFacts.management_url || managementExtra.management_url || '').trim();

  return (
    <div className={styles.serverDash}>
      <div className={styles.serverDashHeader}>
        <div>
          <div className={styles.serverDashBreadcrumbs}>Inventory / Servers / {asset.display_name || asset.management_ip || asset.ip_address}</div>
          <div className={styles.serverDashTitleRow}>
            <h2 className={styles.serverDashTitle}>
              {asset.display_name || asset.management_ip || asset.ip_address}
              {asset.model ? ` (${asset.model})` : ''}
            </h2>
            {renderBadge(globalCode ? `${headerStatus} (${globalCode})` : headerStatus, headerTone)}
          </div>
        </div>
        <div className={styles.serverDashPolling}>
          <span className={styles.serverDashPollingLabel}>Last polled</span>
          <strong>{formatRelativeTime(asset.last_seen_at)}</strong>
          <span className={styles.serverDashPollingSub}>{fmtDate(asset.last_seen_at)}</span>
        </div>
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
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Firmware</span>
                <span className={styles.serverKvValue}>{formatValue(details.controller_firmware || asset.firmware_version)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>BIOS Version</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.bios_version)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>iDRAC Version</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.idrac_version)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>USC Version</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.usc_version)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Power State</span>
                <span className={styles.serverKvValue}>{formatValue(asset.health?.power_state || managementExtra.power_status)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Managed OS</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.managed_os_name || rawObject(racadmSections.system_information).os_name)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Managed Host</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.managed_os_hostname || rawObject(racadmSections.system_information).host_name)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Management URL</span>
                <span className={styles.serverKvValue}>{formatValue(managementUrl)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Environmental</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverThermalBlock}>
              <div className={styles.serverKvLabel}>System Board Inlet Temp</div>
              <div className={styles.serverTempRow}>
                <div className={styles.serverTempValue}>
                  {formatValue(temperatureProbe ? temperatureProbe.reading ?? temperatureProbe.current_reading ?? temperatureProbe.value : null)}
                </div>
                <div className={styles.serverTempBarTrack}>
                  <div className={`${styles.serverTempBarFill} ${toneForStatus(temperatureStatus) === 'fail' ? styles.serverTempBarFail : toneForStatus(temperatureStatus) === 'warn' ? styles.serverTempBarWarn : styles.serverTempBarOk}`} />
                </div>
              </div>
              <div className={styles.serverKvValueSub}>
                {temperatureProbe ? formatValue(temperatureProbe.name || temperatureProbe.probe || temperatureProbe.index) : 'Current iDRAC6 payload does not expose temperature probe values.'}
              </div>
            </div>
            <div className={styles.serverKvList}>
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
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Current Draw</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.actual_power_consumption)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Peak Draw</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.peak_power_consumption)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Peak Timestamp</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.peak_power_timestamp)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Power Cap</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.power_cap_watts)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Redundancy Policy</span>
                <span className={styles.serverKvValue}>{formatValue(managementExtra.sensor_redundancy_policy)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Processors (CPU)</div>
          <div className={styles.serverTableWrap}>
            {cpus.length ? (
              <table className={styles.serverTable}>
                <thead>
                  <tr>
                    <th>Socket</th>
                    <th>Processor Model</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {cpus.map((cpu) => (
                    <tr key={cpu.id}>
                      <td>{cpu.slot || cpu.name || '—'}</td>
                      <td>{cpu.model || cpu.name || '—'}</td>
                      <td>{renderBadge(componentStatus(cpu) || 'Unknown', toneForStatus(componentStatus(cpu)))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className={styles.serverEmptyNote}>Current iDRAC6 SNMP/SEL payload does not expose per-socket CPU inventory.</div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>
            <div className={styles.serverHeaderSplit}>
              <span>Memory (RAM)</span>
              <span className={styles.serverHeaderMetric}>Total Capacity: {formatValue(totalMemory != null ? `${totalMemory} GB` : null)}</span>
            </div>
          </div>
          <div className={styles.serverTableWrap}>
            {memoryModules.length ? (
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
                  {memoryModules.map((module) => {
                    const extra = rawObject(module.extra_json);
                    return (
                      <tr key={module.id}>
                        <td>{module.slot || module.name || '—'}</td>
                        <td>{module.capacity_gb != null ? `${module.capacity_gb} GB` : '—'}</td>
                        <td>{formatValue(extra.memory_type || module.model)}</td>
                        <td>{formatValue(extra.speed_ns ? `${extra.speed_ns} ns` : extra.operating_speed_mhz ? `${extra.operating_speed_mhz} MT/s` : '')}</td>
                        <td>{renderBadge(componentStatus(module) || 'Unknown', toneForStatus(componentStatus(module)))}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : idracTables.memoryDevices.length ? (
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
                  {idracTables.memoryDevices.map((row, index) => (
                    <tr key={`${String(row.index || index)}`}>
                      <td>{formatValue(row.location_name || row.display_name || row.index)}</td>
                      <td>{formatValue(row.size_mb ? `${row.size_mb} MB` : row.capacity)}</td>
                      <td>{formatValue(row.memory_type || row.type)}</td>
                      <td>{formatValue(row.speed_ns ? `${row.speed_ns} ns` : row.speed_mhz ? `${row.speed_mhz} MT/s` : row.speed)}</td>
                      <td>{renderBadge(String(row.status || row.health || row.status_code || 'Unknown'), toneForStatus(String(row.status || row.health || row.status_code || '')))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className={styles.serverEmptyNote}>Current iDRAC6 source does not expose DIMM-level RAM inventory in this asset payload.</div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Storage Subsystem (RAID &amp; Disks)</div>
          <div className={styles.serverCardBody}>
            {virtualDisks.length ? virtualDisks.map((vd) => {
              const extra = rawObject(vd.extra_json);
              const memberSlots = Array.isArray(extra.member_slots) ? extra.member_slots.map((value) => String(value)) : [];
              const memberDisks = physicalDisks.filter((disk) => {
                const slot = disk.slot || disk.name;
                return memberSlots.includes(slot);
              });
              memberDisks.forEach((disk) => assignedDiskKeys.add(String(disk.id)));
              return (
                <div key={vd.id} className={styles.serverStorageGroup}>
                  <div className={styles.serverStorageHeader}>
                    <div className={styles.serverStorageTitle}>
                      <span>{vd.name || 'Virtual Disk'}</span>
                      <span className={styles.serverStorageSubtitle}>{formatValue(extra.raid_type || vd.model)}</span>
                    </div>
                    {renderBadge(componentStatus(vd) || 'Unknown', toneForStatus(componentStatus(vd)))}
                  </div>
                  {memberDisks.length ? (
                    <ul className={styles.serverDiskList}>
                      {memberDisks.map((disk) => (
                        <li key={disk.id} className={styles.serverDiskItem}>
                          <div className={styles.serverDiskSlot}>{disk.slot || disk.name || '—'}</div>
                          <div>
                            <div className={styles.serverDiskModel}>{[disk.manufacturer, disk.model].filter(Boolean).join(' ') || disk.name || 'Physical Disk'}</div>
                            <div className={styles.serverKvValueSub}>{[disk.serial_number, disk.capacity_gb != null ? `${disk.capacity_gb} GB` : ''].filter(Boolean).join(' · ') || 'No additional disk metadata'}</div>
                          </div>
                          <div>{renderBadge(componentStatus(disk) || 'Unknown', toneForStatus(componentStatus(disk)))}</div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className={styles.serverEmptyNote}>Current payload does not expose virtual-disk to physical-disk membership mapping.</div>
                  )}
                </div>
              );
            }) : null}

            {physicalDisks.filter((disk) => !assignedDiskKeys.has(String(disk.id))).length ? (
              <div className={styles.serverStorageGroup}>
                <div className={styles.serverStorageHeader}>
                  <div className={styles.serverStorageTitle}>
                    <span>Unassigned Physical Disks</span>
                    <span className={styles.serverStorageSubtitle}>Direct component view</span>
                  </div>
                </div>
                <ul className={styles.serverDiskList}>
                  {physicalDisks.filter((disk) => !assignedDiskKeys.has(String(disk.id))).map((disk) => {
                    const extra = rawObject(disk.extra_json);
                    return (
                      <li key={disk.id} className={styles.serverDiskItem}>
                        <div className={styles.serverDiskSlot}>{disk.slot || disk.name || '—'}</div>
                        <div>
                          <div className={styles.serverDiskModel}>{[disk.manufacturer, disk.model].filter(Boolean).join(' ') || disk.name || 'Physical Disk'}</div>
                          <div className={styles.serverKvValueSub}>{[disk.serial_number, typeof extra.reason === 'string' ? extra.reason : '', disk.capacity_gb != null ? `${disk.capacity_gb} GB` : ''].filter(Boolean).join(' · ') || 'No additional disk metadata'}</div>
                        </div>
                        <div>{renderBadge(componentStatus(disk) || 'Unknown', toneForStatus(componentStatus(disk)))}</div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}

            {!virtualDisks.length && !physicalDisks.length && !raidControllers.length ? (
              <div className={styles.serverEmptyNote}>
                {asset.raw_facts?.storage_via_snmp === false
                  ? 'This iDRAC6 returned no storage rows via SNMP. RAID, disk, and topology blocks can be rendered only after the current source exposes them.'
                  : 'No storage subsystem rows are available from the current asset source yet.'}
              </div>
            ) : null}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3} ${styles.serverAlertCard}`}>
          <div className={styles.serverCardHeader}>Active System Alerts</div>
          <div className={styles.serverTableWrap}>
            {displayAlerts.length ? (
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
                  {displayAlerts.slice(0, 20).map((entry) => (
                    <tr key={entry.key}>
                      <td>{renderBadge(entry.severity, toneForStatus(entry.severity))}</td>
                      <td>{fmtDate(entry.eventTime)}</td>
                      <td>{entry.component || 'System'}</td>
                      <td>{entry.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className={styles.serverEmptyNote}>No structured alert history in the current payload yet.</div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Power Supplies</div>
          <div className={styles.serverTableWrap}>
            {powerSupplies.length ? (
              <table className={styles.serverTable}>
                <thead>
                  <tr>
                    <th>PSU</th>
                    <th>Status</th>
                    <th>Type</th>
                    <th>Firmware</th>
                    <th>Capacity</th>
                    <th>Current Draw</th>
                  </tr>
                </thead>
                <tbody>
                  {powerSupplies.map((psu) => {
                    const extra = rawObject(psu.extra_json);
                    return (
                      <tr key={psu.id}>
                        <td>{psu.slot || psu.name || '—'}</td>
                        <td>{renderBadge(componentStatus(psu) || 'Unknown', toneForStatus(componentStatus(psu)))}</td>
                        <td>{formatValue(extra.power_supply_type || psu.model)}</td>
                        <td>{formatValue(psu.firmware_version || extra.firmware_version)}</td>
                        <td>{formatValue(extra.max_output_power || extra.max_input_power)}</td>
                        <td>{formatValue(extra.current_draw)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className={styles.serverEmptyNote}>No structured power supply rows are available in the current payload.</div>
            )}
          </div>
        </section>

        <section className={`${styles.serverCard} ${styles.serverCardSpan3}`}>
          <div className={styles.serverCardHeader}>Embedded Network Interfaces</div>
          <div className={styles.serverTableWrap}>
            {networkInterfaces.length ? (
              <table className={styles.serverTable}>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Slot</th>
                    <th>MAC Address</th>
                    <th>Status</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {networkInterfaces.map((nic) => {
                    const extra = rawObject(nic.extra_json);
                    return (
                      <tr key={nic.id}>
                        <td>{nic.name || '—'}</td>
                        <td>{nic.slot || '—'}</td>
                        <td>{formatValue(extra.mac_address)}</td>
                        <td>{renderBadge(componentStatus(nic) || 'Unknown', toneForStatus(componentStatus(nic)))}</td>
                        <td>{formatValue(extra.source)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className={styles.serverEmptyNote}>No embedded NIC rows are available in the current payload.</div>
            )}
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Controllers</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Controllers detected</span>
                <span className={styles.serverKvValue}>{formatValue(raidControllers.length || inventory?.storage_controller_count)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>RAID summary</span>
                <span className={styles.serverKvValue}>{formatValue(inventory?.raid_summary)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Networking</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Interfaces</span>
                <span className={styles.serverKvValue}>{formatValue(networkInterfaces.length || inventory?.network_interface_count)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Primary MAC</span>
                <span className={styles.serverKvValue}>{formatValue(asset.mac_address)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Link Speed</span>
                <span className={styles.serverKvValue}>{formatValue(racadmLomStatus.speed)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Duplex</span>
                <span className={styles.serverKvValue}>{formatValue(racadmLomStatus.duplex_mode)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Active LOM</span>
                <span className={styles.serverKvValue}>{formatValue(racadmLomStatus.active_lom_in_shared_mode)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>NIC Selection</span>
                <span className={styles.serverKvValue}>{formatValue(racadmLomStatus.nic_selection)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Gateway</span>
                <span className={styles.serverKvValue}>{formatValue(racadmIpv4.gateway)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.serverCard}>
          <div className={styles.serverCardHeader}>Collector Freshness</div>
          <div className={styles.serverCardBody}>
            <div className={styles.serverKvList}>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Health snapshot</span>
                <span className={styles.serverKvValue}>{fmtDate(asset.health?.updated_at)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Inventory snapshot</span>
                <span className={styles.serverKvValue}>{fmtDate(inventory?.updated_at)}</span>
              </div>
              <div className={styles.serverKvItem}>
                <span className={styles.serverKvLabel}>Last asset sync</span>
                <span className={styles.serverKvValue}>{fmtDate(asset.last_seen_at)}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
