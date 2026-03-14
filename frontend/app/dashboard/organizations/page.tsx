'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import PackageBuilder from '@/components/PackageBuilder';

interface Organization {
  id: string;
  name: string;
  domain?: string;
  is_active: boolean;
  created_at: string;
  device_count: number;
  user_count: number;
  token_count: number;
  max_devices: number;
}

export default function OrganizationsPage() {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showPkg, setShowPkg] = useState<Organization | null>(null);
  const [newOrg, setNewOrg] = useState({ name: '', domain: '' });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  // Hide "Create org" when inside an org context (only available from Global View)
  const isGlobalView = typeof window !== 'undefined'
    ? !localStorage.getItem('active_org_header')
    : true;

  const load = async () => {
    try {
      const data = await api.get('/organizations');
      setOrgs(data);
    } catch (e: any) {
      setError(e.message || 'Failed to load organizations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!newOrg.name.trim()) return;
    setCreating(true);
    try {
      await api.post('/organizations', newOrg);
      setShowCreate(false);
      setNewOrg({ name: '', domain: '' });
      load();
    } catch (e: any) {
      setError(e.message || 'Failed to create organization');
    } finally {
      setCreating(false);
    }
  };

  const handleToggleActive = async (org: Organization) => {
    try {
      await api.patch(`/organizations/${org.id}`, { is_active: !org.is_active });
      load();
    } catch (e: any) {
      setError(e.message || 'Failed to update organization');
    }
  };

  return (
    <div style={{ padding: '2rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.6rem', fontWeight: 700, margin: 0 }}>Organizations</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: '4px 0 0' }}>
            Manage organizations and their device access
          </p>
        </div>
        <button className="btn btn-primary" id="btn-new-org"
          onClick={() => setShowCreate(true)}
          style={{ display: isGlobalView ? undefined : 'none' }}
        >
          + New Organization
        </button>
      </div>

      {error && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444', borderRadius: 8, padding: '12px 16px', marginBottom: '1rem', color: '#ef4444', fontSize: '0.875rem' }}>
          {error}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 16, padding: '2rem', width: 440, maxWidth: '90vw' }}>
            <h2 style={{ marginTop: 0, fontSize: '1.2rem', fontWeight: 700 }}>New Organization</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Organization Name *</label>
                <input
                  className="input"
                  id="input-org-name"
                  placeholder="e.g. Acme Corp"
                  value={newOrg.name}
                  onChange={e => setNewOrg(p => ({ ...p, name: e.target.value }))}
                  style={{ width: '100%' }}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Domain (optional)</label>
                <input
                  className="input"
                  id="input-org-domain"
                  placeholder="e.g. acme.com"
                  value={newOrg.domain}
                  onChange={e => setNewOrg(p => ({ ...p, domain: e.target.value }))}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: '1.5rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" id="btn-create-org" onClick={handleCreate} disabled={creating || !newOrg.name.trim()}>
                {creating ? 'Creating...' : '✓ Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Package Builder Modal */}
      {showPkg && (
        <PackageBuilder org={showPkg} onClose={() => setShowPkg(null)} />
      )}

      {/* Org grid */}
      {loading ? (
        <div style={{ color: 'var(--text-muted)', padding: '3rem', textAlign: 'center' }}>Loading organizations...</div>
      ) : orgs.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🏢</div>
          <p>No organizations yet. Create your first one.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' }}>
          {orgs.map(org => (
            <div key={org.id} className="card" style={{ padding: '1.25rem', border: '1px solid var(--border)', borderRadius: 12 }}>
              {/* Org header */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '1rem' }}>{org.name}</div>
                  {org.domain && <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{org.domain}</div>}
                </div>
                <span style={{
                  fontSize: '0.7rem', fontWeight: 600, padding: '3px 8px', borderRadius: 99,
                  background: org.is_active ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.1)',
                  color: org.is_active ? '#10b981' : '#ef4444',
                }}>
                  {org.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>

              {/* Stats row */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: '1rem' }}>
                {[
                  { label: 'Devices', value: org.device_count, icon: '📱' },
                  { label: 'Users', value: org.user_count, icon: '👤' },
                  { label: 'Tokens', value: org.token_count, icon: '🔑' },
                ].map(s => (
                  <div key={s.label} style={{ textAlign: 'center', background: 'var(--bg)', borderRadius: 8, padding: '8px 4px' }}>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>{s.value}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{s.icon} {s.label}</div>
                  </div>
                ))}
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-primary"
                  id={`btn-pkg-${org.id}`}
                  style={{ flex: 1, fontSize: '0.8rem', padding: '8px' }}
                  onClick={() => setShowPkg(org)}
                >
                  📦 Package Builder
                </button>
                <button
                  className="btn btn-ghost"
                  id={`btn-toggle-${org.id}`}
                  style={{ fontSize: '0.75rem', padding: '8px 10px' }}
                  onClick={() => handleToggleActive(org)}
                >
                  {org.is_active ? 'Disable' : 'Enable'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
