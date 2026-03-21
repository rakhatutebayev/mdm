'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { type AssetAlert, type AssetComponent, type DiscoveredAsset } from '@/lib/api';
import { HardwareTab } from './HardwareTab';
import styles from './page.module.css';

function fmtDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function prettyLabel(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatValue(value: unknown) {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value.trim() || '—';
  return JSON.stringify(value);
}

function sourceLabel(asset: DiscoveredAsset) {
  return (asset.asset_class || 'network').replace(/_/g, ' ');
}

function isEsxiAsset(asset: DiscoveredAsset) {
  return asset.raw_facts?.template_key === 'vmware_esxi' || asset.raw_facts?.hypervisor === 'VMware ESXi';
}

function isIdracAsset(asset: DiscoveredAsset) {
  return asset.asset_class === 'idrac' || asset.raw_facts?.template_key === 'dell_idrac';
}

function isAvayaAsset(asset: DiscoveredAsset) {
  return asset.asset_class === 'voip' || asset.raw_facts?.template_key === 'avaya_1608';
}

function prefersHardwareDashboard(asset: DiscoveredAsset) {
  return asset.asset_class === 'server' || isIdracAsset(asset) || isEsxiAsset(asset);
}

function inventoryRows(asset: DiscoveredAsset) {
  const inventory = asset.inventory;
  if (!inventory) return [];
  return [
    ['Processor Model', inventory.processor_model],
    ['Processor Vendor', inventory.processor_vendor],
    ['Processor Count', inventory.processor_count],
    ['Physical Cores', inventory.physical_cores],
    ['Logical Processors', inventory.logical_processors],
    ['Memory Total (GB)', inventory.memory_total_gb],
    ['Storage Controllers', inventory.storage_controller_count],
    ['Physical Disks', inventory.physical_disk_count],
    ['Virtual Disks', inventory.virtual_disk_count],
    ['Disk Total (GB)', inventory.disk_total_gb],
    ['Network Interfaces', inventory.network_interface_count],
    ['Power Supplies', inventory.power_supply_count],
    ['RAID Summary', inventory.raid_summary],
    ['Updated At', fmtDate(inventory.updated_at)],
  ].filter(([, value]) => {
    if (value == null) return false;
    if (typeof value === 'string') return value.trim().length > 0;
    return true;
  });
}

function importantFacts(asset: DiscoveredAsset) {
  const rows: Array<[string, unknown]> = [
    ['Firmware Version', asset.firmware_version],
    ['Management IP', asset.management_ip],
    ['System IP', asset.ip_address],
    ['Phone Extension', asset.raw_facts?.extension],
    ['Phone Number', asset.raw_facts?.phone_number],
    ['Portal URL', asset.raw_facts?.portal_url],
    ['Management URL', asset.raw_facts?.management_url],
    ['System Name', asset.raw_facts?.sys_name],
    ['System Description', asset.raw_facts?.sys_descr],
    ['Hypervisor', asset.raw_facts?.hypervisor],
    ['ESXi Version', asset.raw_facts?.esxi_version],
    ['Global Status', asset.raw_facts?.global_status],
    ['Storage status (health)', asset.health?.storage_status],
    ['Template', asset.raw_facts?.template_name],
    ['Protocol', asset.raw_facts?.protocol],
    ['Source Type', asset.source_type],
  ];
  return rows.filter(([, value]) => {
    if (value == null) return false;
    if (typeof value === 'string') return value.trim().length > 0;
    return true;
  });
}

function componentSubtitle(component: AssetComponent) {
  const extra = component.extra_json ?? {};
  const sizeRaw = typeof extra.size_raw === 'string' ? extra.size_raw : '';
  const raidType = typeof extra.raid_type === 'string' ? extra.raid_type : '';
  const source = typeof extra.source === 'string' ? extra.source : '';
  return [
    component.model,
    component.manufacturer,
    component.serial_number,
    component.firmware_version,
    component.capacity_gb != null ? `${component.capacity_gb} GB` : '',
    sizeRaw ? `Size: ${sizeRaw}` : '',
    raidType ? `RAID: ${raidType}` : '',
    source ? `(${source})` : '',
  ].filter(Boolean).join(' · ');
}

function alertSubtitle(alert: AssetAlert) {
  return [alert.source, alert.code, alert.status].filter(Boolean).join(' · ');
}

function alertEventTime(alert: AssetAlert) {
  const extra = alert.extra_json ?? {};
  const eventTime = typeof extra.event_time === 'string' ? extra.event_time : '';
  return fmtDate(eventTime || alert.first_seen_at || alert.last_seen_at);
}

function alertObservedTime(alert: AssetAlert) {
  const extra = alert.extra_json ?? {};
  const eventTime = typeof extra.event_time === 'string' ? extra.event_time : '';
  if (eventTime && alert.last_seen_at && eventTime !== alert.last_seen_at) {
    return fmtDate(alert.last_seen_at);
  }
  return '—';
}

function profileSections(asset: DiscoveredAsset) {
  const sections: Array<{ title: string; rows: Array<[string, unknown]> }> = [];

  if (isIdracAsset(asset)) {
    const details = (asset.raw_facts?.dell_details ?? {}) as Record<string, unknown>;
    const idracRows: Array<[string, unknown]> = [
      ['Controller', details.controller_name ?? asset.display_name],
      ['Model', details.controller_model ?? asset.model],
      ['Firmware', details.controller_firmware ?? asset.firmware_version],
      ['Service Tag', details.service_tag ?? asset.serial_number],
      ['Management URL', details.management_url ?? asset.raw_facts?.management_url],
      ['Overall Status', details.global_status ?? asset.health?.overall_status ?? asset.status],
    ];
    sections.push({
      title: 'iDRAC Profile',
      rows: idracRows.filter(([, value]) => value != null && String(value).trim() !== ''),
    });
  }

  if (isEsxiAsset(asset)) {
    const comps = asset.components ?? [];
    const datastores = comps.filter((component) => component.component_type === 'datastore');
    const controllers = comps.filter((component) => component.component_type === 'storage_controller');
    const controllerSummary = controllers.map((component) => `${component.name} (${component.status || 'unknown'})`).join(', ');
    const esxiRows: Array<[string, unknown]> = [
      ['Hypervisor', asset.raw_facts?.hypervisor ?? 'VMware ESXi'],
      ['Version', asset.raw_facts?.esxi_version ?? asset.firmware_version],
      ['CPU', asset.inventory?.processor_model],
      ['Logical Processors', asset.inventory?.logical_processors],
      ['Memory Total (GB)', asset.inventory?.memory_total_gb],
      ['Network Interfaces', asset.inventory?.network_interface_count],
      ['Storage Controllers', asset.inventory?.storage_controller_count],
      ['Datastores', datastores.length],
      ['Controller Status', controllerSummary],
    ];
    sections.push({
      title: 'ESXi Profile',
      rows: esxiRows.filter(([, value]) => value != null && String(value).trim() !== ''),
    });
  }

  if (isAvayaAsset(asset)) {
    const avayaRows: Array<[string, unknown]> = [
      ['Extension', asset.raw_facts?.extension],
      ['Phone Number', asset.raw_facts?.phone_number],
      ['Model', asset.model],
      ['Firmware', asset.firmware_version],
      ['Hostname', asset.raw_facts?.sys_name ?? asset.display_name],
      ['Protocol', asset.raw_facts?.protocol],
    ];
    sections.push({
      title: 'Phone Profile',
      rows: avayaRows.filter(([, value]) => value != null && String(value).trim() !== ''),
    });
  }

  return sections.filter((section) => section.rows.length > 0);
}

type AssetDetailClientProps = {
  assetId: string;
  agentId: string;
  customer: string;
  initialAsset: DiscoveredAsset | null;
  initialError: string | null;
};

export default function AssetDetailClient({
  assetId,
  agentId,
  customer,
  initialAsset,
  initialError,
}: AssetDetailClientProps) {
  const [asset] = useState<DiscoveredAsset | null>(initialAsset);
  const [activeTab, setActiveTab] = useState<'overview' | 'hardware'>(
    () => (initialAsset && prefersHardwareDashboard(initialAsset) ? 'hardware' : 'overview'),
  );
  const [error] = useState<string | null>(initialError);

  const backHref = useMemo(() => {
    if (agentId) {
      return `/discovery/agents/${agentId}${customer ? `?customer=${encodeURIComponent(customer)}` : ''}`;
    }
    return `/discovery${customer ? `?customer=${encodeURIComponent(customer)}` : ''}`;
  }, [agentId, customer]);

  const overviewRows = asset ? [
    ['Name', asset.display_name || '—'],
    ['Class', sourceLabel(asset)],
    ['Vendor / Model', [asset.vendor, asset.model].filter(Boolean).join(' / ') || '—'],
    ['Serial Number', asset.serial_number || '—'],
    ['MAC Address', asset.mac_address || '—'],
    ['IP Address', asset.management_ip || asset.ip_address || '—'],
    ['Health', asset.health?.overall_status || asset.status || '—'],
    ['Alerts', asset.alerts.length],
    ['First Seen', fmtDate(asset.first_seen_at)],
    ['Last Seen', fmtDate(asset.last_seen_at)],
  ] : [];
  const profileCards = asset ? profileSections(asset) : [];
  const showDedicatedServerPage = asset ? prefersHardwareDashboard(asset) : false;

  return (
    <div className={styles.page}>
      <div className={styles.topRow}>
        <Link href={backHref} className={styles.backLink}>
          ← Back to Discovery Assets
        </Link>
      </div>

      {!asset ? (
        <div className={styles.emptyState}>{error || `Asset ${assetId} not found.`}</div>
      ) : showDedicatedServerPage ? (
        <HardwareTab asset={asset} />
      ) : (
        <>
          <div className={styles.header}>
            <div>
              <h1 className={styles.title}>{asset.display_name || asset.management_ip || asset.ip_address || 'Discovered asset'}</h1>
              <p className={styles.subtitle}>
                {sourceLabel(asset)} · {[asset.vendor, asset.model].filter(Boolean).join(' / ') || 'Unknown device'}
              </p>
            </div>
          </div>

          <div className={styles.tabs}>
            <button
              className={`${styles.tabButton} ${activeTab === 'overview' ? styles.tabButtonActive : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              General Overview
            </button>
            <button
              className={`${styles.tabButton} ${activeTab === 'hardware' ? styles.tabButtonActive : ''}`}
              onClick={() => setActiveTab('hardware')}
            >
              Hardware Profile
            </button>
          </div>

          {activeTab === 'overview' ? (
            <>
              <div className={styles.stats}>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Health</span>
                  <strong className={styles.statValue}>{asset.health?.overall_status || asset.status || '—'}</strong>
                  <span className={styles.statMeta}>{asset.health?.summary || 'Current asset state'}</span>
                </div>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Alerts</span>
                  <strong className={styles.statValue}>{asset.alerts.length}</strong>
                  <span className={styles.statMeta}>Active alert records</span>
                </div>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Components</span>
                  <strong className={styles.statValue}>{(asset.components ?? []).length}</strong>
                  <span className={styles.statMeta}>Inventory components linked to this asset</span>
                </div>
              </div>

              {profileCards.length ? (
                <section className={styles.section}>
                  <div className={styles.sectionHeader}>
                    <h2>Device Profile</h2>
                    <span>Type-specific details</span>
                  </div>
                  <div className={styles.profileGrid}>
                    {profileCards.map((section) => (
                      <div key={section.title} className={styles.infoCard}>
                        <h3 className={styles.profileTitle}>{section.title}</h3>
                        {section.rows.map(([label, value]) => (
                          <div key={label} className={styles.infoRow}>
                            <span>{label}</span>
                            <strong>{formatValue(value)}</strong>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Overview</h2>
                </div>
                <div className={styles.infoGrid}>
                  <div className={styles.infoCard}>
                    {overviewRows.map(([label, value]) => (
                      <div key={label} className={styles.infoRow}>
                        <span>{label}</span>
                        <strong>{formatValue(value)}</strong>
                      </div>
                    ))}
                  </div>
                  <div className={styles.infoCard}>
                    {importantFacts(asset).map(([label, value]) => (
                      <div key={label} className={styles.infoRow}>
                        <span>{label}</span>
                        <strong>{formatValue(value)}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Inventory</h2>
                </div>
                {inventoryRows(asset).length ? (
                  <div className={styles.infoCard}>
                    {inventoryRows(asset).map(([label, value]) => (
                      <div key={label} className={styles.infoRow}>
                        <span>{label}</span>
                        <strong>{formatValue(value)}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className={styles.emptyCard}>No structured inventory for this asset yet.</div>
                )}
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Components</h2>
                  <span>{(asset.components ?? []).length} total</span>
                </div>
                {asset.components.length ? (
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Name</th>
                          <th>Status</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {asset.components.map((component) => (
                          <tr key={component.id}>
                            <td>{prettyLabel(component.component_type)}</td>
                            <td>{component.name || '—'}</td>
                            <td>{component.health || component.status || '—'}</td>
                            <td>{componentSubtitle(component) || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className={styles.emptyCard}>No component details for this asset.</div>
                )}
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Alerts</h2>
                  <span>{asset.alerts.length} total</span>
                </div>
                {asset.alerts.length ? (
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Severity</th>
                          <th>Message</th>
                          <th>Source</th>
                          <th>Event Time</th>
                          <th>Observed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {asset.alerts.map((alert) => (
                          <tr key={alert.id}>
                            <td>{alert.severity || '—'}</td>
                            <td>{alert.message || '—'}</td>
                            <td>{alertSubtitle(alert) || '—'}</td>
                            <td>{alertEventTime(alert)}</td>
                            <td>{alertObservedTime(alert)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className={styles.emptyCard}>No alerts recorded for this asset.</div>
                )}
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Raw Facts</h2>
                </div>
                <div className={styles.codeCard}>
                  <pre>{JSON.stringify(asset.raw_facts, null, 2)}</pre>
                </div>
              </section>
            </>
          ) : (
            <HardwareTab asset={asset} />
          )}
        </>
      )}
    </div>
  );
}
