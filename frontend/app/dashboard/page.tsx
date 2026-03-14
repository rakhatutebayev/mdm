'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import Link from 'next/link';

const PLATFORM_EMOJI: Record<string, string> = {
    ios: '🍎',
    ipados: '📱',
    macos: '💻',
    android: '🤖',
    windows: '🪟',
};

export default function DashboardPage() {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        api.listDevices({ limit: '200' })
            .then((res) => setData(res))
            .catch(() => setData(null))
            .finally(() => setLoading(false));
    }, []);

    const devices: any[] = data?.devices || [];
    const total = data?.total || 0;

    const byStatus = (s: string) => devices.filter((d) => d.status === s).length;
    const byPlatform = (p: string) => devices.filter((d) => d.platform === p).length;
    const byod = devices.filter((d) => d.is_byod).length;

    return (
        <>
            <div className="page-header">
                <div>
                    <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>Overview</h1>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                        Device Management Dashboard
                    </div>
                </div>
                <Link href="/dashboard/enrollment" className="btn btn-primary" id="btn-new-enrollment">
                    + Enroll Device
                </Link>
            </div>

            <div className="page-content">
                {loading ? (
                    <div className="loading-spinner" />
                ) : (
                    <>
                        {/* Stat cards */}
                        <div className="stat-grid">
                            <div className="stat-card blue">
                                <div className="stat-icon blue" style={{ fontSize: '1.4rem' }}>📱</div>
                                <div>
                                    <div className="stat-value">{total}</div>
                                    <div className="stat-label">Total Devices</div>
                                </div>
                            </div>
                            <div className="stat-card green">
                                <div className="stat-icon green" style={{ fontSize: '1.4rem' }}>✅</div>
                                <div>
                                    <div className="stat-value" style={{ color: 'var(--success)' }}>
                                        {byStatus('enrolled') + byStatus('supervised')}
                                    </div>
                                    <div className="stat-label">Enrolled & Active</div>
                                </div>
                            </div>
                            <div className="stat-card orange">
                                <div className="stat-icon orange" style={{ fontSize: '1.4rem' }}>⏳</div>
                                <div>
                                    <div className="stat-value" style={{ color: 'var(--warning)' }}>
                                        {byStatus('pending')}
                                    </div>
                                    <div className="stat-label">Pending Enrollment</div>
                                </div>
                            </div>
                            <div className="stat-card blue">
                                <div className="stat-icon blue" style={{ fontSize: '1.4rem' }}>🔒</div>
                                <div>
                                    <div className="stat-value">{byod}</div>
                                    <div className="stat-label">BYOD Devices</div>
                                </div>
                            </div>
                        </div>

                        {/* Platform breakdown */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '2rem' }}>
                            <div className="card">
                                <div className="card-title">Devices by Platform</div>
                                {[
                                    ['iOS / iPadOS', byPlatform('ios') + byPlatform('ipados'), 'var(--accent)'],
                                    ['macOS', byPlatform('macos'), 'var(--info)'],
                                    ['Android', byPlatform('android'), 'var(--success)'],
                                    ['Windows', byPlatform('windows'), 'var(--warning)'],
                                ].map(([label, count, color]) => (
                                    <div key={label as string} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0', borderBottom: '1px solid var(--border)' }}>
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{label as string}</span>
                                        <span style={{ fontWeight: 700, color: color as string }}>{count as number}</span>
                                    </div>
                                ))}
                            </div>

                            <div className="card">
                                <div className="card-title">Quick Actions</div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                    <Link href="/dashboard/enrollment" className="btn btn-secondary" id="btn-quick-enroll">📲 New Enrollment</Link>
                                    <Link href="/dashboard/devices" className="btn btn-secondary" id="btn-quick-devices">📋 View All Devices</Link>
                                    <Link href="/dashboard/apps" className="btn btn-secondary" id="btn-quick-apps">🗂️ Manage App Catalog</Link>
                                </div>
                            </div>
                        </div>

                        {/* Recent devices */}
                        {devices.length > 0 && (
                            <div className="table-wrapper">
                                <div className="table-header">
                                    <h3 style={{ margin: 0, fontSize: '0.95rem' }}>Recent Devices</h3>
                                    <Link href="/dashboard/devices" style={{ fontSize: '0.8rem', color: 'var(--accent)' }}>View all →</Link>
                                </div>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Device</th>
                                            <th>Platform</th>
                                            <th>Status</th>
                                            <th>Last Seen</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {devices.slice(0, 8).map((device) => (
                                            <tr key={device.id} onClick={() => window.location.href = `/dashboard/devices/${device.id}`}>
                                                <td className="primary">{device.name || device.model || 'Unknown'}</td>
                                                <td>
                                                    <span className="platform-badge">
                                                        {PLATFORM_EMOJI[device.platform]} {device.platform?.toUpperCase()}
                                                    </span>
                                                </td>
                                                <td>
                                                    <span className={`badge ${device.status}`}>
                                                        <span className="badge-dot" />
                                                        {device.status}
                                                    </span>
                                                </td>
                                                <td>{device.last_seen ? new Date(device.last_seen).toLocaleString() : '—'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {total === 0 && (
                            <div className="empty-state">
                                <div className="empty-state-icon">📱</div>
                                <h3>No devices yet</h3>
                                <p style={{ marginBottom: '1.5rem' }}>Get started by enrolling your first device</p>
                                <Link href="/dashboard/enrollment" className="btn btn-primary" id="btn-enroll-first">
                                    Enroll First Device
                                </Link>
                            </div>
                        )}
                    </>
                )}
            </div>
        </>
    );
}
