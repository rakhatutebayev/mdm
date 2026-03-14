'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { api } from '@/lib/api';

const NAV = [
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
            { href: '/dashboard/organizations', label: 'Organizations', icon: '🏢' },
            { href: '/dashboard/users', label: 'Users & Roles', icon: '👥' },
        ],
    },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="sidebar">
            <div className="sidebar-logo">
                <div className="logo-icon">N</div>
                <div>
                    <div className="logo-text">NOCKO MDM</div>
                    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '-2px' }}>Device Management</div>
                </div>
            </div>

            <nav className="sidebar-nav">
                {NAV.map((group) => (
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
