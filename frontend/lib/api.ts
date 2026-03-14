/**
 * API client — wraps fetch with auth token injection.
 */

const BASE = '/api/v1';

function getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('access_token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = getToken();
    const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers as Record<string, string> || {}),
    };

    const res = await fetch(`${BASE}${path}`, { ...options, headers });

    if (res.status === 401) {
        localStorage.removeItem('access_token');
        throw new Error('UNAUTHORIZED');
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }

    if (res.status === 204) return undefined as T;
    return res.json();
}

// Auth
export const api = {
    async login(email: string, password: string) {
        const form = new URLSearchParams({ username: email, password });
        const res = await fetch(`${BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: form.toString(),
        });
        if (!res.ok) throw new Error('Invalid credentials');
        const data = await res.json();
        localStorage.setItem('access_token', data.access_token);
        return data;
    },

    async register(email: string, password: string, full_name: string, org_name: string) {
        const data = await request<any>('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, password, full_name, org_name }),
        });
        localStorage.setItem('access_token', data.access_token);
        return data;
    },

    async me() { return request<any>('/auth/me'); },

    logout() {
        localStorage.removeItem('access_token');
        window.location.href = '/login';
    },

    // Devices
    async listDevices(params: Record<string, string> = {}) {
        const q = new URLSearchParams(params).toString();
        return request<any>(`/devices${q ? `?${q}` : ''}`);
    },
    async getDevice(id: string) { return request<any>(`/devices/${id}`); },
    async sendCommand(deviceId: string, command: string, payload: object = {}) {
        return request<any>(`/devices/${deviceId}/command`, {
            method: 'POST',
            body: JSON.stringify({ command, payload }),
        });
    },
    async unenrollDevice(id: string) {
        return request<any>(`/devices/${id}`, { method: 'DELETE' });
    },
    async listCommands(deviceId: string) {
        return request<any>(`/devices/${deviceId}/commands`);
    },

    // Apps
    async listApps() { return request<any[]>('/apps'); },
    async createApp(data: object) {
        return request<any>('/apps', { method: 'POST', body: JSON.stringify(data) });
    },
    async deleteApp(id: string) { return request<any>(`/apps/${id}`, { method: 'DELETE' }); },
    async pushApp(app_id: string, device_ids: string[]) {
        return request<any>('/apps/push', {
            method: 'POST',
            body: JSON.stringify({ app_id, device_ids }),
        });
    },

    // Enrollment
    async listTokens() { return request<any[]>('/enrollment/token'); },
    async createToken(data: object) {
        return request<any>('/enrollment/token', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
    async revokeToken(id: string) {
        return request<any>(`/enrollment/token/${id}`, { method: 'DELETE' });
    },
    qrCodeUrl(token: string) {
        return `${BASE}/enrollment/token/${token}/qrcode?auth=${getToken()}`;
    },

    // Users & Roles
    async listUsers() { return request<any[]>('/users'); },
    async inviteUser(data: { email: string; full_name: string; password: string; role: string }) {
        return request<any>('/users', { method: 'POST', body: JSON.stringify(data) });
    },
    async changeRole(userId: string, role: string) {
        return request<any>(`/users/${userId}/role`, {
            method: 'PATCH',
            body: JSON.stringify({ role }),
        });
    },
    async deactivateUser(userId: string) {
        return request<any>(`/users/${userId}/deactivate`, { method: 'PATCH' });
    },
    async activateUser(userId: string) {
        return request<any>(`/users/${userId}/activate`, { method: 'PATCH' });
    },
    async deleteUser(userId: string) {
        return request<any>(`/users/${userId}`, { method: 'DELETE' });
    },

    // Microsoft Entra
    async entraStatus(): Promise<{ enabled: boolean }> {
        return request<{ enabled: boolean }>('/auth/entra-status');
    },
    async entraConfig(): Promise<any> {
        return request<any>('/windows-enrollment/entra-config');
    },

    // Windows enrollment — generate one-liner + script URL for a token
    async windowsScript(tokenId: string): Promise<{ one_liner: string; script_url: string }> {
        const token = getToken();
        const script_url = `${BASE}/enrollment/package/windows/${tokenId}/download`;
        const one_liner = `powershell -ExecutionPolicy Bypass -Command "Invoke-WebRequest '${script_url}' -OutFile $env:TEMP\\nocko-agent.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\\nocko-agent.ps1 -Install"`;
        return { one_liner, script_url };
    },

    // ── Generic HTTP helpers ──────────────────────────────────────────────
    async get<T = any>(path: string): Promise<T> {
        return request<T>(path);
    },
    async post<T = any>(path: string, body?: object): Promise<T> {
        return request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
    },
    async patch<T = any>(path: string, body?: object): Promise<T> {
        return request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined });
    },
    async delete<T = any>(path: string): Promise<T> {
        return request<T>(path, { method: 'DELETE' });
    },

    // ── Organizations ─────────────────────────────────────────────────────
    async listOrganizations() { return request<any[]>('/organizations'); },
    async createOrganization(data: { name: string; domain?: string }) {
        return request<any>('/organizations', { method: 'POST', body: JSON.stringify(data) });
    },
    async updateOrganization(id: string, data: object) {
        return request<any>(`/organizations/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    },
    async deleteOrganization(id: string) {
        return request<any>(`/organizations/${id}`, { method: 'DELETE' });
    },
    async orgStats(id: string) { return request<any>(`/organizations/${id}/stats`); },

    // ── Package Builder ───────────────────────────────────────────────────
    async createWindowsPackage(data: {
        org_id: string;
        package_name?: string;
        max_uses: number;
        expires_in_days: number;
    }) {
        return request<any>('/enrollment/package/windows', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
    packageDownloadUrl(token_id: string): string {
        return `${BASE}/enrollment/package/windows/${token_id}/download`;
    },
};
