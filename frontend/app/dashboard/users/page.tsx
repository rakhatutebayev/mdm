'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

const ROLE_COLORS: Record<string, string> = {
    super_admin: 'enrolled',
    admin: 'enrolled',
    it_manager: 'pending',
    viewer: '',
};

const ROLE_LABELS: Record<string, string> = {
    super_admin: 'Super Admin',
    admin: 'Admin',
    it_manager: 'IT Manager',
    viewer: 'Viewer',
};

const ALL_ROLES = ['admin', 'it_manager', 'viewer'];

function timeSince(iso?: string) {
    if (!iso) return 'Never';
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

export default function UsersPage() {
    const [me, setMe] = useState<any>(null);
    const [users, setUsers] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    // Invite modal state
    const [showInvite, setShowInvite] = useState(false);
    const [inviteForm, setInviteForm] = useState({ email: '', full_name: '', password: '', role: 'viewer' });
    const [inviting, setInviting] = useState(false);
    const [inviteError, setInviteError] = useState('');

    // Role popover
    const [rolePopover, setRolePopover] = useState<string | null>(null);

    // Action loading states
    const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

    const load = async () => {
        setLoading(true);
        try {
            const [meData, usersData] = await Promise.all([
                api.me(),
                api.listUsers(),
            ]);
            setMe(meData);
            setUsers(usersData);
        } catch (e: any) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const isAdmin = me && ['admin', 'super_admin'].includes(me.role);

    const handleInvite = async (e: React.FormEvent) => {
        e.preventDefault();
        setInviting(true);
        setInviteError('');
        try {
            await api.inviteUser(inviteForm);
            setShowInvite(false);
            setInviteForm({ email: '', full_name: '', password: '', role: 'viewer' });
            await load();
        } catch (e: any) {
            setInviteError(e.message);
        } finally {
            setInviting(false);
        }
    };

    const withAction = (userId: string, fn: () => Promise<any>) => async () => {
        setActionLoading(prev => ({ ...prev, [userId]: true }));
        try { await fn(); await load(); }
        catch (e: any) { alert(e.message); }
        finally { setActionLoading(prev => ({ ...prev, [userId]: false })); }
    };

    const handleRoleChange = (userId: string, role: string) => {
        setRolePopover(null);
        withAction(userId, () => api.changeRole(userId, role))();
    };

    return (
        <>
            <div className="page-header">
                <div>
                    <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>Users & Roles</h1>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {users.length} member{users.length !== 1 ? 's' : ''} in your organization
                    </div>
                </div>
                {isAdmin && (
                    <button
                        id="btn-invite-user"
                        className="btn btn-primary"
                        onClick={() => setShowInvite(true)}
                    >
                        + Invite User
                    </button>
                )}
            </div>

            <div className="page-content">
                {/* Invite Modal */}
                {showInvite && (
                    <div className="modal-overlay" onClick={(e) => e.currentTarget === e.target && setShowInvite(false)}>
                        <div className="modal">
                            <div className="modal-title">Invite New User</div>
                            {inviteError && <div className="alert alert-warning">{inviteError}</div>}
                            <form onSubmit={handleInvite}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                    <div className="form-group">
                                        <label>Full Name *</label>
                                        <input
                                            id="input-invite-name"
                                            type="text"
                                            required
                                            placeholder="Jane Smith"
                                            value={inviteForm.full_name}
                                            onChange={(e) => setInviteForm({ ...inviteForm, full_name: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label>Email *</label>
                                        <input
                                            id="input-invite-email"
                                            type="email"
                                            required
                                            placeholder="jane@company.com"
                                            value={inviteForm.email}
                                            onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label>Temporary Password *</label>
                                        <input
                                            id="input-invite-password"
                                            type="password"
                                            required
                                            placeholder="Min 8 characters"
                                            value={inviteForm.password}
                                            onChange={(e) => setInviteForm({ ...inviteForm, password: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label>Role</label>
                                        <select
                                            id="input-invite-role"
                                            value={inviteForm.role}
                                            onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value })}
                                        >
                                            {ALL_ROLES.map(r => (
                                                <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <div className="modal-actions">
                                    <button type="button" className="btn btn-ghost" onClick={() => setShowInvite(false)}>Cancel</button>
                                    <button id="btn-confirm-invite" type="submit" className="btn btn-primary" disabled={inviting}>
                                        {inviting ? 'Inviting…' : 'Send Invite'}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}

                {/* Error */}
                {error && <div className="alert alert-warning">{error}</div>}

                {/* Users Table */}
                {loading ? (
                    <div className="loading-spinner" />
                ) : users.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">👥</div>
                        <h3>No users yet</h3>
                        <p style={{ marginBottom: '1.5rem' }}>Invite team members to manage devices</p>
                        {isAdmin && (
                            <button id="btn-invite-first" className="btn btn-primary" onClick={() => setShowInvite(true)}>
                                Invite First User
                            </button>
                        )}
                    </div>
                ) : (
                    <div className="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>User</th>
                                    <th>Role</th>
                                    <th>Status</th>
                                    <th>Last Login</th>
                                    <th>Joined</th>
                                    {isAdmin && <th>Actions</th>}
                                </tr>
                            </thead>
                            <tbody>
                                {users.map((user) => {
                                    const isMe = me && user.id === me.id;
                                    const isLoading = actionLoading[user.id];
                                    return (
                                        <tr key={user.id}>
                                            <td className="primary">
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                                    <div style={{
                                                        width: 36,
                                                        height: 36,
                                                        borderRadius: '50%',
                                                        background: 'var(--primary)',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        fontSize: '0.875rem',
                                                        fontWeight: 700,
                                                        color: '#fff',
                                                        flexShrink: 0,
                                                    }}>
                                                        {(user.full_name || user.email).charAt(0).toUpperCase()}
                                                    </div>
                                                    <div>
                                                        <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                                                            {user.full_name || '—'}
                                                            {isMe && (
                                                                <span style={{ marginLeft: '0.4rem', fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                                                                    (you)
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{user.email}</div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td>
                                                {isAdmin && !isMe ? (
                                                    <div style={{ position: 'relative', display: 'inline-block' }}>
                                                        <button
                                                            id={`btn-role-${user.id}`}
                                                            className={`badge ${ROLE_COLORS[user.role] || ''}`}
                                                            style={{
                                                                cursor: 'pointer',
                                                                background: 'none',
                                                                border: '1px solid var(--border)',
                                                                borderRadius: 4,
                                                                padding: '3px 8px',
                                                                fontSize: '0.75rem',
                                                                fontWeight: 600,
                                                                color: 'var(--text)',
                                                            }}
                                                            onClick={() => setRolePopover(rolePopover === user.id ? null : user.id)}
                                                        >
                                                            {ROLE_LABELS[user.role] || user.role} ▾
                                                        </button>
                                                        {rolePopover === user.id && (
                                                            <div style={{
                                                                position: 'absolute',
                                                                top: '110%',
                                                                left: 0,
                                                                background: 'var(--surface-elevated)',
                                                                border: '1px solid var(--border)',
                                                                borderRadius: 8,
                                                                boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
                                                                zIndex: 100,
                                                                minWidth: 140,
                                                                overflow: 'hidden',
                                                            }}>
                                                                {ALL_ROLES.map(r => (
                                                                    <button
                                                                        key={r}
                                                                        id={`btn-setrole-${r}-${user.id}`}
                                                                        onClick={() => handleRoleChange(user.id, r)}
                                                                        style={{
                                                                            display: 'block',
                                                                            width: '100%',
                                                                            textAlign: 'left',
                                                                            padding: '0.5rem 0.75rem',
                                                                            fontSize: '0.8rem',
                                                                            fontWeight: r === user.role ? 700 : 400,
                                                                            background: r === user.role ? 'var(--primary-subtle)' : 'transparent',
                                                                            color: 'var(--text)',
                                                                            border: 'none',
                                                                            cursor: 'pointer',
                                                                        }}
                                                                    >
                                                                        {ROLE_LABELS[r]}
                                                                    </button>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                ) : (
                                                    <span className={`badge ${ROLE_COLORS[user.role] || ''}`} style={{ fontSize: '0.75rem' }}>
                                                        {ROLE_LABELS[user.role] || user.role}
                                                    </span>
                                                )}
                                            </td>
                                            <td>
                                                {user.is_active
                                                    ? <span className="badge enrolled" style={{ fontSize: '0.75rem' }}>Active</span>
                                                    : <span className="badge wiped" style={{ fontSize: '0.75rem' }}>Inactive</span>}
                                            </td>
                                            <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                                {timeSince(user.last_login)}
                                            </td>
                                            <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                                {user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
                                            </td>
                                            {isAdmin && (
                                                <td>
                                                    {!isMe && (
                                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                            {user.is_active ? (
                                                                <button
                                                                    id={`btn-deactivate-${user.id}`}
                                                                    className="btn btn-ghost btn-sm"
                                                                    disabled={isLoading}
                                                                    onClick={withAction(user.id, () => api.deactivateUser(user.id))}
                                                                >
                                                                    Deactivate
                                                                </button>
                                                            ) : (
                                                                <button
                                                                    id={`btn-activate-${user.id}`}
                                                                    className="btn btn-ghost btn-sm"
                                                                    disabled={isLoading}
                                                                    onClick={withAction(user.id, () => api.activateUser(user.id))}
                                                                >
                                                                    Activate
                                                                </button>
                                                            )}
                                                            <button
                                                                id={`btn-delete-user-${user.id}`}
                                                                className="btn btn-danger btn-sm"
                                                                disabled={isLoading}
                                                                onClick={() => {
                                                                    if (confirm(`Delete ${user.email}? This cannot be undone.`)) {
                                                                        withAction(user.id, () => api.deleteUser(user.id))();
                                                                    }
                                                                }}
                                                            >
                                                                Delete
                                                            </button>
                                                        </div>
                                                    )}
                                                </td>
                                            )}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}

                {/* Role definitions card */}
                <div className="card" style={{ marginTop: '2rem' }}>
                    <div className="card-title">Role Permissions</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                        {[
                            {
                                role: 'super_admin',
                                label: 'Super Admin',
                                desc: 'Full platform access including multi-org management',
                                perms: ['All admin permissions', 'Manage multiple organizations', 'System-level configuration'],
                            },
                            {
                                role: 'admin',
                                label: 'Admin',
                                desc: 'Full access within the organization',
                                perms: ['Manage devices & users', 'Push apps', 'Generate tokens', 'Invite & remove users'],
                            },
                            {
                                role: 'it_manager',
                                label: 'IT Manager',
                                desc: 'Operational device management',
                                perms: ['Manage devices', 'Send MDM commands', 'Push apps', 'Generate enrollment tokens'],
                            },
                            {
                                role: 'viewer',
                                label: 'Viewer',
                                desc: 'Read-only access',
                                perms: ['View device inventory', 'View command history', 'No write access'],
                            },
                        ].map((r) => (
                            <div key={r.role} style={{
                                padding: '1rem',
                                background: 'var(--surface)',
                                borderRadius: 8,
                                border: '1px solid var(--border)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                    <span className={`badge ${ROLE_COLORS[r.role] || ''}`} style={{ fontSize: '0.7rem' }}>
                                        {r.label}
                                    </span>
                                </div>
                                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>{r.desc}</div>
                                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                                    {r.perms.map(p => (
                                        <li key={p} style={{ fontSize: '0.75rem', color: 'var(--text)', padding: '0.15rem 0', display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                            <span style={{ color: 'var(--success)' }}>✓</span> {p}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </>
    );
}
