'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';

const PLATFORM_EMOJI: Record<string, string> = {
    ios: '🍎', ipados: '📱', macos: '💻', android: '🤖', windows: '🪟',
};

const COMMAND_ACTIONS = [
    { id: 'DeviceLock', label: 'Lock Device', icon: '🔒', color: '' },
    { id: 'ClearPasscode', label: 'Reset PIN', icon: '🔑', color: '' },
    { id: 'DeviceInformation', label: 'Get Info', icon: '📋', color: '' },
    { id: 'EraseDevice', label: 'Remote Wipe', icon: '🗑️', color: 'danger' },
    { id: 'InstallApplication', label: 'Push App', icon: '📲', color: '' },
    { id: 'RemoveApplication', label: 'Remove App', icon: '❌', color: '' },
];

const ANDROID_ACTIONS = [
    { id: 'android_lock', label: 'Lock Device', icon: '🔒', color: '' },
    { id: 'android_reset_password', label: 'Reset PIN', icon: '🔑', color: '' },
    { id: 'android_wipe', label: 'Factory Reset', icon: '🗑️', color: 'danger' },
    { id: 'android_install_app', label: 'Push App', icon: '📲', color: '' },
    { id: 'android_remove_app', label: 'Remove App', icon: '❌', color: '' },
];

const WINDOWS_ACTIONS = [
    { id: 'LOCK', label: 'Lock Screen', icon: '🔒', color: '' },
    { id: 'MESSAGE', label: 'Send Message', icon: '💬', color: '' },
    { id: 'COLLECT_INFO', label: 'Refresh Info', icon: '📋', color: '' },
    { id: 'RESTART', label: 'Restart', icon: '🔄', color: '' },
    { id: 'SHUTDOWN', label: 'Shutdown', icon: '⏹️', color: '' },
];

export default function DeviceDetailPage() {
    const { id } = useParams();
    const router = useRouter();
    const [device, setDevice] = useState<any>(null);
    const [commands, setCommands] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [cmdLoading, setCmdLoading] = useState<string | null>(null);
    const [confirm, setConfirm] = useState<string | null>(null);
    const [message, setMessage] = useState('');

    useEffect(() => {
        Promise.all([
            api.getDevice(id as string),
            api.listCommands(id as string),
        ])
            .then(([dev, cmds]) => { setDevice(dev); setCommands(cmds); })
            .catch(() => router.push('/dashboard/devices'))
            .finally(() => setLoading(false));
    }, [id]);

    const sendCommand = async (cmdType: string) => {
        if (['EraseDevice', 'android_wipe'].includes(cmdType) && confirm !== cmdType) {
            setConfirm(cmdType);
            return;
        }
        setCmdLoading(cmdType);
        setConfirm(null);
        try {
            await api.sendCommand(id as string, cmdType);
            setMessage(`✅ Command "${cmdType}" queued successfully`);
            const cmds = await api.listCommands(id as string);
            setCommands(cmds);
        } catch (e: any) {
            setMessage(`❌ Error: ${e.message}`);
        } finally {
            setCmdLoading(null);
        }
    };

    const unenroll = async () => {
        if (!confirm) { setConfirm('unenroll'); return; }
        await api.unenrollDevice(id as string);
        router.push('/dashboard/devices');
    };

    if (loading) return <div className="loading-spinner" style={{ marginTop: '4rem' }} />;
    if (!device) return null;

    const isWindows = device.platform === 'windows';
    const actions = isWindows ? WINDOWS_ACTIONS : device.platform === 'android' ? ANDROID_ACTIONS : COMMAND_ACTIONS;
    const hw = device.device_info || {};
    const monitors: any[] = hw.monitors || [];

    return (
        <>
            <div className="page-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <button onClick={() => router.back()} className="btn btn-ghost btn-icon" id="btn-back">←</button>
                    <div>
                        <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>
                            {PLATFORM_EMOJI[device.platform]} {device.name || device.model || 'Device Detail'}
                        </h1>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            {device.serial_number || device.udid || device.android_id || '—'}
                        </div>
                    </div>
                </div>
                <span className={`badge ${device.status}`}>
                    <span className="badge-dot" />{device.status}
                </span>
            </div>

            <div className="page-content">
                {message && (
                    <div className={`alert ${message.startsWith('✅') ? 'alert-info' : 'alert-warning'}`} style={{ marginBottom: '1.5rem' }}>
                        {message}
                        <button onClick={() => setMessage('')} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit' }}>✕</button>
                    </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                    {/* Device info */}
                    <div className="card">
                        <div className="card-title">Device Information</div>
                        {[
                            ['Platform', device.platform?.toUpperCase()],
                            ['Model', device.model || '—'],
                            ['OS Version', device.os_version || '—'],
                            ['Serial Number', device.serial_number || '—'],
                            ['Enrollment Type', device.enrollment_type],
                            ['BYOD', device.is_byod ? 'Yes' : 'No'],
                            ['Enrolled', device.enrolled_at ? new Date(device.enrolled_at).toLocaleString() : '—'],
                            ['Last Seen', device.last_seen ? new Date(device.last_seen).toLocaleString() : '—'],
                        ].map(([label, value]) => (
                            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.4rem 0', borderBottom: '1px solid var(--border)', fontSize: '0.875rem' }}>
                                <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                                <span>{value}</span>
                            </div>
                        ))}
                    </div>

                    {/* Actions */}
                    <div className="card">
                        <div className="card-title">Remote Commands</div>
                        <div className="action-grid">
                            {actions.map((action) => (
                                <button
                                    key={action.id}
                                    id={`btn-cmd-${action.id}`}
                                    className={`action-btn ${action.color}`}
                                    onClick={() => sendCommand(action.id)}
                                    disabled={cmdLoading !== null}
                                >
                                    <div className="action-icon" style={{ fontSize: '1.2rem' }}>
                                        {cmdLoading === action.id ? '⏳' : action.icon}
                                    </div>
                                    {action.label}
                                </button>
                            ))}
                        </div>

                        {confirm && (
                            <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                                <div>
                                    <strong>⚠️ Confirm {confirm === 'unenroll' ? 'Unenroll' : 'Wipe'}?</strong>
                                    <p style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
                                        {confirm === 'unenroll' ? 'This will remove MDM management from the device.' : 'This will erase all data on the device.'}
                                    </p>
                                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                                        <button
                                            id="btn-confirm-yes"
                                            className="btn btn-danger btn-sm"
                                            onClick={() => confirm === 'unenroll' ? unenroll() : sendCommand(confirm)}
                                        >
                                            Confirm
                                        </button>
                                        <button className="btn btn-ghost btn-sm" onClick={() => setConfirm(null)}>Cancel</button>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                            <button
                                id="btn-unenroll"
                                className="btn btn-ghost"
                                style={{ width: '100%', justifyContent: 'center', color: 'var(--danger)' }}
                                onClick={unenroll}
                            >
                                🚫 Unenroll Device
                            </button>
                        </div>
                    </div>
                </div>

                {/* Windows hardware inventory */}
                {isWindows && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginTop: '1.5rem' }}>
                        <div className="card">
                            <div className="card-title">🖥️ Hardware Inventory</div>
                            {[
                                ['Serial Number', hw.serial_number || '—'],
                                ['Manufacturer', hw.manufacturer || '—'],
                                ['CPU', hw.cpu_model || '—'],
                                ['RAM', hw.ram_gb ? `${hw.ram_gb} GB` : '—'],
                                ['Disk (C:)', hw.disk_gb ? `${hw.disk_gb} GB` : '—'],
                                ['BIOS', hw.bios_version || '—'],
                                ['IP Address', hw.ip_address || '—'],
                                ['MAC Address', hw.mac_address || '—'],
                                ['Current User', hw.current_user || '—'],
                                ['Entra Joined', hw.entra_joined ? '✅ Yes' : '❌ No'],
                                ['Domain Joined', hw.domain_joined ? '✅ Yes' : '❌ No'],
                            ].map(([label, value]) => (
                                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.4rem 0', borderBottom: '1px solid var(--border)', fontSize: '0.8rem' }}>
                                    <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                                    <span style={{ fontFamily: label === 'MAC Address' || label === 'Serial Number' ? 'monospace' : undefined }}>{value}</span>
                                </div>
                            ))}
                        </div>

                        <div className="card">
                            <div className="card-title">🖥️ Connected Monitors ({monitors.length})</div>
                            {monitors.length === 0 ? (
                                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', padding: '1rem 0' }}>No monitor data yet — agent will report on next check-in</div>
                            ) : monitors.map((m: any, i: number) => (
                                <div key={i} style={{ padding: '0.75rem 0', borderBottom: '1px solid var(--border)' }}>
                                    <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.35rem' }}>Monitor {i + 1}: {m.model || 'Unknown'}</div>
                                    {[
                                        ['Manufacturer', m.manufacturer || '—'],
                                        ['Serial Number', m.serial || '—'],
                                    ].map(([label, value]) => (
                                        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                                            <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                                            <span style={{ fontFamily: 'monospace' }}>{value}</span>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Command history */}
                {commands.length > 0 && (
                    <div className="table-wrapper" style={{ marginTop: '1.5rem' }}>
                        <div className="table-header">
                            <h3 style={{ margin: 0, fontSize: '0.95rem' }}>Command History</h3>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>Command</th>
                                    <th>Status</th>
                                    <th>Issued At</th>
                                    <th>Acknowledged</th>
                                </tr>
                            </thead>
                            <tbody>
                                {commands.map((cmd) => (
                                    <tr key={cmd.id}>
                                        <td className="primary" style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{cmd.command_type}</td>
                                        <td>
                                            <span className={`badge ${cmd.status === 'acknowledged' ? 'enrolled' : cmd.status === 'error' ? 'wiped' : 'pending'}`}>
                                                <span className="badge-dot" />{cmd.status}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: '0.8rem' }}>{new Date(cmd.created_at).toLocaleString()}</td>
                                        <td style={{ fontSize: '0.8rem' }}>{cmd.acknowledged_at ? new Date(cmd.acknowledged_at).toLocaleString() : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </>
    );
}
