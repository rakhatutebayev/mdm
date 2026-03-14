'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import Link from 'next/link';

const PLATFORM_EMOJI: Record<string, string> = {
    ios: '🍎', ipados: '📱', macos: '💻', android: '🤖', windows: '🪟',
};

const PLATFORMS = ['all', 'ios', 'android', 'macos', 'windows'];

export default function DevicesPage() {
    const [devices, setDevices] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [platform, setPlatform] = useState('all');
    const [search, setSearch] = useState('');

    const load = async () => {
        setLoading(true);
        try {
            const params: Record<string, string> = {};
            if (platform !== 'all') params.platform = platform;
            if (search) params.search = search;
            const res = await api.listDevices(params);
            setDevices(res.devices || []);
            setTotal(res.total || 0);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, [platform, search]);

    return (
        <>
            <div className="page-header">
                <div>
                    <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>Devices</h1>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{total} total devices</div>
                </div>
                <Link href="/dashboard/enrollment" className="btn btn-primary" id="btn-enroll-device">
                    + Enroll Device
                </Link>
            </div>

            <div className="page-content">
                <div className="table-wrapper">
                    <div className="table-header">
                        <div className="search-wrapper">
                            <span className="search-icon">🔍</span>
                            <input
                                id="input-search"
                                type="search"
                                placeholder="Search by name, serial, model..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                            />
                        </div>

                        <div className="filter-bar">
                            {PLATFORMS.map((p) => (
                                <button
                                    key={p}
                                    id={`filter-${p}`}
                                    className={`filter-btn ${platform === p ? 'active' : ''}`}
                                    onClick={() => setPlatform(p)}
                                >
                                    {p === 'all' ? 'All' : `${PLATFORM_EMOJI[p] || ''} ${p.charAt(0).toUpperCase() + p.slice(1)}`}
                                </button>
                            ))}
                        </div>
                    </div>

                    {loading ? (
                        <div className="loading-spinner" />
                    ) : devices.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-state-icon">📱</div>
                            <h3>No devices found</h3>
                            <p>Try changing filters or enroll a new device</p>
                        </div>
                    ) : (
                        <table>
                            <thead>
                                <tr>
                                    <th>Device Name</th>
                                    <th>Platform</th>
                                    <th>Model</th>
                                    <th>Serial</th>
                                    <th>Status</th>
                                    <th>Type</th>
                                    <th>Last Seen</th>
                                </tr>
                            </thead>
                            <tbody>
                                {devices.map((device) => (
                                    <tr key={device.id} onClick={() => window.location.href = `/dashboard/devices/${device.id}`}>
                                        <td className="primary">{device.name || '—'}</td>
                                        <td>
                                            <span className="platform-badge">
                                                {PLATFORM_EMOJI[device.platform]} {device.platform?.toUpperCase()}
                                            </span>
                                        </td>
                                        <td>{device.model || '—'}</td>
                                        <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{device.serial_number || '—'}</td>
                                        <td>
                                            <span className={`badge ${device.status}`}>
                                                <span className="badge-dot" />
                                                {device.status}
                                            </span>
                                        </td>
                                        <td>
                                            {device.is_byod ? (
                                                <span className="badge pending">BYOD</span>
                                            ) : (
                                                <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Corporate</span>
                                            )}
                                        </td>
                                        <td style={{ fontSize: '0.8rem' }}>
                                            {device.last_seen ? new Date(device.last_seen).toLocaleString() : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </>
    );
}
