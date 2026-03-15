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
  owner: string;
  enrollment_method: string;
  status: string;
  enrolled_at: string | null;
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
  model: string;
  serial_number: string;
  display_size: string;
  resolution: string;
  refresh_rate: string;
  color_depth: string;
  connection_type: string;
  hdr_support: boolean;
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
  customer_name: string;
}

export interface EnrollmentToken {
  token: string;
  customer_id: string;
  created_at: string;
}

export interface PackageArtifact {
  format: "zip" | "msi" | "exe";
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

// ── Agent Packages ────────────────────────────────────────────────────────────

export const getPackageCatalog = (customerId: string) =>
  req<PackageCatalog>(`/packages/catalog?customer_id=${customerId}`);
