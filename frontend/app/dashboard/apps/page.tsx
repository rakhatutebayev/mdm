'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export default function AppsPage() {
    const [apps, setApps] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({
        name: '', bundle_id: '', app_store_id: '', play_store_url: '',
        icon_url: '', version: '', description: '', is_managed: true, is_byod_allowed: false,
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');

    const load = async () => {
        setLoading(true);
        try { setApps(await api.listApps()); }
        finally { setLoading(false); }
    };

    useEffect(() => { load(); }, []);

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        setSubmitting(true);
        setError('');
        try {
            await api.createApp(form);
            setShowForm(false);
            setForm({ name: '', bundle_id: '', app_store_id: '', play_store_url: '', icon_url: '', version: '', description: '', is_managed: true, is_byod_allowed: false });
            await load();
        } catch (e: any) {
            setError(e.message);
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Remove this app from the catalog?')) return;
        await api.deleteApp(id);
        await load();
    };

    return (
        <>
            <div className="page-header">
                <div>
                    <h1 style={{ fontSize: '1.2rem', fontWeight: 700 }}>App Catalog</h1>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{apps.length} apps in catalog</div>
                </div>
                <button
                    id="btn-add-app"
                    className="btn btn-primary"
                    onClick={() => setShowForm(true)}
                >
                    + Add App
                </button>
            </div>

            <div className="page-content">
                {/* Add App Modal */}
                {showForm && (
                    <div className="modal-overlay" onClick={(e) => e.currentTarget === e.target && setShowForm(false)}>
                        <div className="modal">
                            <div className="modal-title">Add App to Catalog</div>
                            {error && <div className="alert alert-warning">{error}</div>}
                            <form onSubmit={handleCreate}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                    <div className="form-group">
                                        <label>App Name *</label>
                                        <input id="input-app-name" type="text" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Slack" />
                                    </div>
                                    <div className="form-group">
                                        <label>Bundle / Package ID *</label>
                                        <input id="input-bundle-id" type="text" required value={form.bundle_id} onChange={(e) => setForm({ ...form, bundle_id: e.target.value })} placeholder="com.tinyspeck.chatlyio" />
                                    </div>
                                    <div className="form-group">
                                        <label>App Store ID (iOS)</label>
                                        <input id="input-appstore-id" type="text" value={form.app_store_id} onChange={(e) => setForm({ ...form, app_store_id: e.target.value })} placeholder="618783545" />
                                    </div>
                                    <div className="form-group">
                                        <label>Version</label>
                                        <input id="input-version" type="text" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} placeholder="6.0.0" />
                                    </div>
                                    <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                        <label>Play Store URL (Android)</label>
                                        <input id="input-playstore" type="text" value={form.play_store_url} onChange={(e) => setForm({ ...form, play_store_url: e.target.value })} placeholder="https://play.google.com/store/apps/details?id=..." />
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem' }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textTransform: 'none', fontSize: '0.875rem', fontWeight: 500 }}>
                                        <input type="checkbox" checked={form.is_byod_allowed} onChange={(e) => setForm({ ...form, is_byod_allowed: e.target.checked })} />
                                        Allow on BYOD devices
                                    </label>
                                </div>

                                <div className="modal-actions">
                                    <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
                                    <button id="btn-save-app" type="submit" className="btn btn-primary" disabled={submitting}>
                                        {submitting ? 'Adding…' : 'Add to Catalog'}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}

                {loading ? (
                    <div className="loading-spinner" />
                ) : apps.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">🗂️</div>
                        <h3>No apps in catalog</h3>
                        <p style={{ marginBottom: '1.5rem' }}>Add apps to push them to managed devices</p>
                        <button id="btn-add-first-app" className="btn btn-primary" onClick={() => setShowForm(true)}>Add First App</button>
                    </div>
                ) : (
                    <div className="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>App Name</th>
                                    <th>Bundle ID</th>
                                    <th>Version</th>
                                    <th>Platforms</th>
                                    <th>BYOD</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {apps.map((app) => (
                                    <tr key={app.id} onClick={(e) => e.stopPropagation()}>
                                        <td className="primary">
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                {app.icon_url ? (
                                                    <img src={app.icon_url} alt="" style={{ width: 28, height: 28, borderRadius: 6 }} />
                                                ) : (
                                                    <div style={{ width: 28, height: 28, background: 'var(--border)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9rem' }}>📦</div>
                                                )}
                                                {app.name}
                                            </div>
                                        </td>
                                        <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{app.bundle_id}</td>
                                        <td>{app.version || '—'}</td>
                                        <td>
                                            <div style={{ display: 'flex', gap: '0.25rem' }}>
                                                {app.app_store_id && <span style={{ fontSize: '1rem' }} title="iOS">🍎</span>}
                                                {app.play_store_url && <span style={{ fontSize: '1rem' }} title="Android">🤖</span>}
                                            </div>
                                        </td>
                                        <td>
                                            {app.is_byod_allowed
                                                ? <span className="badge pending">BYOD</span>
                                                : <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No</span>}
                                        </td>
                                        <td>
                                            <button
                                                id={`btn-delete-app-${app.id}`}
                                                className="btn btn-danger btn-sm"
                                                onClick={() => handleDelete(app.id)}
                                            >
                                                Remove
                                            </button>
                                        </td>
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
