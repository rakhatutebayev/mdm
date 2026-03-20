/**
 * Typed API helpers for NOCKO MDM frontend.
 * All calls go through Next.js Route Handlers (BFF) which proxy to FastAPI.
 */

const BASE = "/api/mdm";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Customer {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface DeviceListItem {
  id: string;
  customer_id: string;
  device_name: string;
  platform: string;
  os_version: string;
  owner: string;
  enrollment_method: string;
  agent_version: string;
  status: string;
  enrolled_at: string | null;
  last_checkin: string | null;
}

export interface NetworkInfo {
  ip_address: string;
  mac_address: string;
  hostname: string;
  wifi_ssid: string;
  connection_type: string;
  dns_server: string;
  default_gateway: string;
}

export interface MonitorInfo {
  display_index: number;
  manufacturer: string;
  model: string;
  serial_number: string;
  display_size: string;
  resolution: string;
  refresh_rate: string;
  color_depth: string;
  connection_type: string;
  hdr_support: boolean;
}

export interface HardwareInventory {
  processor_model: string;
  processor_vendor: string;
  physical_cores: number | null;
  logical_processors: number | null;
  memory_total_gb: number | null;
  memory_slot_count: number | null;
  memory_slots_used: number | null;
  memory_module_count: number | null;
  machine_class: string;
  chassis_type: string;
  gpu_model: string;
  gpu_manufacturer: string;
  gpu_vram_gb: number | null;
  gpu_driver_version: string;
}

export interface PhysicalDiskInfo {
  disk_index: number | null;
  model: string;
  serial_number: string;
  media_type: string;
  interface_type: string;
  size_gb: number | null;
}

export interface LogicalDiskInfo {
  name: string;
  volume_name: string;
  file_system: string;
  drive_type: string;
  size_gb: number | null;
  free_gb: number | null;
  used_gb: number | null;
}

export interface PrinterInfo {
  name: string;
  driver_name: string;
  port_name: string;
  ip_address: string;
  is_default: boolean;
  is_network: boolean;
  is_shared: boolean;
  work_offline: boolean;
  job_count: number | null;
  connection_type: string;
  status: string;
}

export interface DeviceDetail extends DeviceListItem {
  device_type: string;
  model: string;
  manufacturer: string;
  serial_number: string;
  udid: string;
  os_version: string;
  architecture: string;
  shared_device: boolean;
  last_checkin: string | null;
  agent_version: string;
  network: NetworkInfo | null;
  monitors: MonitorInfo[];
  hardware_inventory: HardwareInventory | null;
  physical_disks: PhysicalDiskInfo[];
  logical_disks: LogicalDiskInfo[];
  printers: PrinterInfo[];
  customer_name: string;
}

export interface EnrollmentToken {
  token: string;
  customer_id: string;
  created_at: string;
}

export interface ProxyAgent {
  id: string;
  customer_id: string;
  name: string;
  site_name: string;
  hostname: string;
  ip_address: string;
  mac_address: string;
  portal_url: string;
  version: string;
  status: string;
  is_registered: boolean;
  capabilities: string[];
  auth_token: string;
  last_checkin: string | null;
  registered_at: string | null;
  created_at: string;
}

export interface ProxyAgentCommand {
  id: string;
  proxy_agent_id: string;
  command_type: string;
  payload: Record<string, unknown>;
  status: string;
  result: string | null;
  created_at: string;
  acked_at: string | null;
}

export interface AssetInventory {
  processor_model: string;
  processor_vendor: string;
  processor_count: number | null;
  physical_cores: number | null;
  logical_processors: number | null;
  memory_total_gb: number | null;
  memory_slot_count: number | null;
  memory_slots_used: number | null;
  memory_module_count: number | null;
  storage_controller_count: number | null;
  physical_disk_count: number | null;
  virtual_disk_count: number | null;
  disk_total_gb: number | null;
  network_interface_count: number | null;
  power_supply_count: number | null;
  raid_summary: string;
  updated_at: string;
}

export interface AssetComponent {
  id: number;
  component_type: string;
  name: string;
  slot: string;
  model: string;
  manufacturer: string;
  serial_number: string;
  firmware_version: string;
  capacity_gb: number | null;
  status: string;
  health: string;
  extra_json: Record<string, unknown>;
}

export interface AssetHealth {
  overall_status: string;
  processor_status: string;
  memory_status: string;
  storage_status: string;
  power_status: string;
  network_status: string;
  thermal_status: string;
  power_state: string;
  alert_count: number | null;
  summary: string;
  updated_at: string;
}

export interface AssetAlert {
  id: number;
  source: string;
  severity: string;
  code: string;
  message: string;
  status: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  cleared_at: string | null;
  extra_json: Record<string, unknown>;
}

export interface DiscoveredAsset {
  id: string;
  customer_id: string;
  proxy_agent_id: string | null;
  asset_class: string;
  source_type: string;
  display_name: string;
  vendor: string;
  model: string;
  serial_number: string;
  firmware_version: string;
  ip_address: string;
  management_ip: string;
  mac_address: string;
  status: string;
  raw_facts: Record<string, unknown>;
  inventory: AssetInventory | null;
  components: AssetComponent[];
  health: AssetHealth | null;
  alerts: AssetAlert[];
  first_seen_at: string;
  last_seen_at: string | null;
  created_at: string;
}

export interface PackageArtifact {
  format: "zip" | "exe";
  arch: "x64" | "x86";
  version: string;
  filename: string;
  download_url: string;
  sha256: string | null;
  size_bytes: number | null;
  notes: string | null;
}

export interface PackageCatalog {
  customer_id: string;
  customer_name: string;
  server_url: string;
  enrollment_token: string;
  release_channel: string;
  release_version: string | null;
  generated_at: string | null;
  artifacts: PackageArtifact[];
  bootstrap_formats: string[];
}

// ── Customers ─────────────────────────────────────────────────────────────────

export const getCustomers = () => req<Customer[]>("/customers");

export const createCustomer = (name: string, slug: string) =>
  req<Customer>("/customers", {
    method: "POST",
    body: JSON.stringify({ name, slug }),
  });

export const deleteCustomer = (id: string) =>
  req<void>(`/customers/${id}`, { method: "DELETE" });

// ── Devices ───────────────────────────────────────────────────────────────────

export const getDevices = (customerId?: string) =>
  req<DeviceListItem[]>(`/devices${customerId ? `?customer_id=${customerId}` : ""}`);

export const getDevice = (id: string) =>
  req<DeviceDetail>(`/devices/${id}`);

export const updateDeviceStatus = (id: string, status: string) =>
  req<DeviceListItem>(`/devices/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const deleteDevice = (id: string) =>
  fetch(`${BASE}/devices/${id}`, { method: "DELETE" }).then((r) => {
    if (!r.ok && r.status !== 204) throw new Error(`API ${r.status}`);
  });

// ── Enrollment Tokens ─────────────────────────────────────────────────────────

export const getEnrollmentToken = (customerId: string) =>
  req<EnrollmentToken>(`/enrollment/token?customer_id=${customerId}`);

export const regenerateToken = (customerId: string) =>
  req<EnrollmentToken>(`/enrollment/token/${customerId}/regenerate`, { method: "POST" });

// ── Proxy Agent / Discovery ───────────────────────────────────────────────────

export const getProxyAgents = (customerId?: string) =>
  req<ProxyAgent[]>(`/discovery/agents${customerId ? `?customer_id=${customerId}` : ""}`);

export const getProxyAgent = (agentId: string) =>
  req<ProxyAgent>(`/discovery/agents/${agentId}`);

export const createProxyAgent = (body: {
  customer_id: string;
  name: string;
  site_name?: string;
  hostname?: string;
  ip_address?: string;
  version?: string;
  capabilities?: string[];
  auth_token?: string;
}) =>
  req<ProxyAgent>("/discovery/agents", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const registerProxyAgent = (agentId: string) =>
  req<ProxyAgent>(`/discovery/agents/${agentId}/register`, {
    method: "POST",
  });

export const getProxyAgentCommands = (agentId: string) =>
  req<ProxyAgentCommand[]>(`/discovery/agents/${agentId}/commands`);

export const getProxyAgentCommand = (agentId: string, commandId: string) =>
  req<ProxyAgentCommand>(`/discovery/agents/${agentId}/commands/${commandId}`);

export const createProxyAgentCommand = (
  agentId: string,
  body: {
    command_type: string;
    payload?: Record<string, unknown>;
  }
) =>
  req<ProxyAgentCommand>(`/discovery/agents/${agentId}/commands`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getDiscoveredAssets = (params?: { customerId?: string; proxyAgentId?: string }) => {
  const query = new URLSearchParams();
  if (params?.customerId) query.set("customer_id", params.customerId);
  if (params?.proxyAgentId) query.set("proxy_agent_id", params.proxyAgentId);
  const suffix = query.toString();
  return req<DiscoveredAsset[]>(`/discovery/assets${suffix ? `?${suffix}` : ""}`);
};

export const getDiscoveredAsset = (id: string, signal?: AbortSignal) =>
  req<DiscoveredAsset>(`/discovery/assets/${id}`, signal ? { signal } : undefined);

// ── Agent Packages ────────────────────────────────────────────────────────────

export const getPackageCatalog = (customerId: string) =>
  req<PackageCatalog>(`/packages/catalog?customer_id=${customerId}`);
