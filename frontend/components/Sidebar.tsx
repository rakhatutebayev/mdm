'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';

// Nav shown when INSIDE an org context
const ORG_NAV = [
    {
        section: 'Management',
        items: [
            { href: '/dashboard', label: 'Overview', icon: '⊞' },
            { href: '/dashboard/devices', label: 'Devices', icon: '📱' },
            { href: '/dashboard/apps', label: 'App Catalog', icon: '🗂️' },
            { href: '/dashboard/enrollment', label: 'Enrollment', icon: '🔗' },
        ],
    },
    {
        section: 'Administration',
        items: [
            { href: '/dashboard/users', label: 'Users & Roles', icon: '👥' },
        ],
    },
];

// Nav shown in GLOBAL view (no org selected)
const GLOBAL_NAV = [
    {
        section: 'Global',
        items: [
            { href: '/dashboard/organizations', label: 'Organizations', icon: '🏢' },
        ],
    },
];

interface OrgOption { id: string; name: string; }

export default function Sidebar() {
    const pathname = usePathname();

    const [orgs, setOrgs] = useState<OrgOption[]>([]);
    const [activeOrg, setActiveOrgState] = useState<OrgOption | null>(null);
    const [isSuperAdmin, setIsSuperAdmin] = useState(false);
    const [open, setOpen] = useState(false);
    const dropRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const token = localStorage.getItem('access_token');
        if (!token) return;

        fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } })
            .then(r => r.json())
            .then(me => {
                const isSuper = me.role === 'super_admin';
                setIsSuperAdmin(isSuper);

                if (isSuper) {
                    fetch('/api/v1/organizations', { headers: { Authorization: `Bearer ${token}` } })
                        .then(r => r.json())
                        .then((list: OrgOption[]) => {
                            setOrgs(list);
                            const saved = localStorage.getItem('active_org_id');
                            const found = saved ? list.find(o => o.id === saved) : null;
                            const active = found || list[0] || null;
                            setActiveOrgState(active);
                            if (active) {
                                localStorage.setItem('active_org_id', active.id);
                                localStorage.setItem('active_org_header', active.id);
                            }
                        })
                        .catch(() => {});
                } else {
                    const myOrg: OrgOption = { id: me.org_id || '', name: me.org_name || 'My Organization' };
                    setOrgs([myOrg]);
                    setActiveOrgState(myOrg);
                }
            })
            .catch(() => {});

        // Close dropdown on outside click
        const handleClick = (e: MouseEvent) => {
            if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        return () => document.removeEventListener('mousedown', handleClick);
    }, []);

    const switchOrg = (org: OrgOption) => {
        localStorage.setItem('active_org_id', org.id);
        localStorage.setItem('active_org_header', org.id);
        setActiveOrgState(org);
        setOpen(false);
        window.location.href = '/dashboard';
    };

    const exitToGlobal = () => {
        localStorage.removeItem('active_org_id');
        localStorage.removeItem('active_org_header');
        setActiveOrgState(null);
        setOpen(false);
        window.location.href = '/dashboard/organizations';
    };

    // Determine if in global mode (super admin with no org selected)
    const isGlobalMode = isSuperAdmin && !activeOrg;
    const nav = isGlobalMode ? GLOBAL_NAV : ORG_NAV;

    return (
        <aside className="sidebar">
            <div className="sidebar-logo">
                <div className="logo-icon">N</div>
                <div>
                    <div className="logo-text">NOCKO MDM</div>
                    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '-2px' }}>Device Management</div>
                </div>
            </div>

            {/* Org Switcher */}
            {(activeOrg || isSuperAdmin) && (
                <div ref={dropRef} style={{ padding: '0 12px 8px', position: 'relative' }}>
                    <button
                        id="btn-org-switcher"
                        onClick={() => isSuperAdmin && setOpen(o => !o)}
                        style={{
                            width: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '8px 10px',
                            background: 'var(--bg-hover)',
                            border: '1px solid var(--border)',
                            borderRadius: '8px',
                            cursor: isSuperAdmin ? 'pointer' : 'default',
                            textAlign: 'left',
                            color: 'var(--text)',
                        }}
                    >
                        {/* Avatar */}
                        <div style={{
                            width: 28, height: 28, borderRadius: 6,
                            background: isGlobalMode ? 'var(--text-muted)' : 'var(--accent)',
                            color: '#fff',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontWeight: 700, fontSize: '0.8rem', flexShrink: 0,
                        }}>
                            {isGlobalMode ? '🌐' : activeOrg!.name.charAt(0).toUpperCase()}
                        </div>
                        <div style={{ flex: 1, overflow: 'hidden' }}>
                            <div style={{ fontSize: '0.8rem', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {isGlobalMode ? 'Global View' : activeOrg!.name}
                            </div>
                            {isSuperAdmin && (
                                <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                                    {isGlobalMode ? 'Select an organization' : 'Click to switch'}
                                </div>
                            )}
                        </div>
                        {isSuperAdmin && (
                            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>▼</span>
                        )}
                    </button>

                    {/* Dropdown */}
                    {open && (
                        <div style={{
                            position: 'absolute',
                            top: 'calc(100% + 4px)',
                            left: 12, right: 12,
                            background: 'var(--bg-card)',
                            border: '1px solid var(--border)',
                            borderRadius: '10px',
                            boxShadow: 'var(--shadow-md)',
                            zIndex: 200,
                            overflow: 'hidden',
                        }}>
                            {/* Global View option */}
                            <button
                                id="btn-global-view"
                                onClick={exitToGlobal}
                                style={{
                                    width: '100%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    padding: '8px 10px',
                                    background: isGlobalMode ? 'var(--bg-hover)' : 'transparent',
                                    border: 'none',
                                    borderBottom: '1px solid var(--border)',
                                    cursor: 'pointer',
                                    textAlign: 'left',
                                    color: 'var(--text)',
                                    fontSize: '0.82rem',
                                }}
                                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
                                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = isGlobalMode ? 'var(--bg-hover)' : 'transparent'; }}
                            >
                                <div style={{ width: 24, height: 24, borderRadius: 5, background: 'var(--bg)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem' }}>🌐</div>
                                <span style={{ flex: 1 }}>Global View</span>
                                {isGlobalMode && <span style={{ color: 'var(--accent)', fontSize: '0.75rem' }}>✓</span>}
                            </button>

                            {/* Orgs list */}
                            <div style={{ padding: '4px 10px', fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Organizations</div>
                            {orgs.map(org => (
                                <button
                                    key={org.id}
                                    id={`org-switch-${org.id}`}
                                    onClick={() => switchOrg(org)}
                                    style={{
                                        width: '100%',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '8px',
                                        padding: '8px 10px',
                                        background: (!isGlobalMode && activeOrg?.id === org.id) ? 'var(--bg-hover)' : 'transparent',
                                        border: 'none',
                                        cursor: 'pointer',
                                        textAlign: 'left',
                                        color: 'var(--text)',
                                        fontSize: '0.82rem',
                                    }}
                                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
                                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = (!isGlobalMode && activeOrg?.id === org.id) ? 'var(--bg-hover)' : 'transparent'; }}
                                >
                                    <div style={{
                                        width: 24, height: 24, borderRadius: 5,
                                        background: (!isGlobalMode && activeOrg?.id === org.id) ? 'var(--accent)' : 'var(--border)',
                                        color: (!isGlobalMode && activeOrg?.id === org.id) ? '#fff' : 'var(--text-muted)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontWeight: 700, fontSize: '0.7rem', flexShrink: 0,
                                    }}>
                                        {org.name.charAt(0).toUpperCase()}
                                    </div>
                                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{org.name}</span>
                                    {(!isGlobalMode && activeOrg?.id === org.id) && (
                                        <span style={{ color: 'var(--accent)', fontSize: '0.75rem' }}>✓</span>
                                    )}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}

            <nav className="sidebar-nav">
                {nav.map((group) => (
                    <div key={group.section}>
                        <div className="nav-section-title">{group.section}</div>
                        {group.items.map((item) => {
                            const exact = item.href === '/dashboard';
                            const active = exact ? pathname === item.href : pathname.startsWith(item.href);
                            return (
                                <Link key={item.href} href={item.href} className={`nav-item ${active ? 'active' : ''}`}>
                                    <span style={{ fontSize: '1rem' }}>{item.icon}</span>
                                    {item.label}
                                </Link>
                            );
                        })}
                    </div>
                ))}
            </nav>

            <div className="sidebar-footer">
                <button
                    className="btn btn-ghost"
                    style={{ width: '100%', justifyContent: 'center', fontSize: '0.8rem' }}
                    onClick={() => api.logout()}
                    id="btn-logout"
                >
                    Sign out
                </button>
            </div>
        </aside>
    );
}
