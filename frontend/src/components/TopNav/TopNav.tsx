'use client';
import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';

import { usePathname, useSearchParams } from 'next/navigation';
import styles from './TopNav.module.css';

type NavChild = { label: string; href: string; icon: React.ReactNode };
type NavItem = { label: string; href?: string; children?: NavChild[] };

const NAV_ITEMS: NavItem[] = [
  { label: 'Home', href: '/' },
  {
    label: 'Device Mgmt',
    children: [
      { label: 'Mobile Devices', href: '/devices?type=mobile', icon: '📱' },
      { label: 'Computers', href: '/devices?type=computer', icon: '💻' },
      { label: 'Tablets', href: '/devices?type=tablet', icon: '📟' },
      { label: 'Device Groups', href: '/devices/groups', icon: '🗂️' },
    ],
  },
  {
    label: 'Inventory',
    children: [
      { label: 'Hardware', href: '/inventory/hardware', icon: '🔧' },
      { label: 'Software', href: '/inventory/software', icon: '📦' },
    ],
  },
  { label: 'Enrollment', href: '/enrollment' },
  { label: 'Discovery', href: '/discovery' },
  {
    label: 'Reports',
    children: [
      { label: 'Device Status', href: '/reports/status', icon: '📊' },
      { label: 'Compliance', href: '/reports/compliance', icon: '✅' },
      { label: 'Security Audit', href: '/reports/security', icon: '🛡️' },
    ],
  },
  { label: 'Admin', href: '/admin' },
  { label: 'Support', href: '/support' },
];

export default function TopNav() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Full current URL path+query for exact child matching
  const currentHref = searchParams.toString() ? `${pathname}?${searchParams.toString()}` : pathname;
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const navRef = useRef<HTMLElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const isActive = (item: NavItem) => {
    if (item.href) return pathname === item.href;
    if (item.children) return item.children.some((c: NavChild) => pathname.startsWith(c.href.split('?')[0]));
    return false;
  };

  return (
    <nav className={styles.nav} ref={navRef}>
      {/* Logo */}
      <Link href="/" className={styles.logo}>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26, borderRadius: '50%', background: '#fff', flexShrink: 0 }}>
          <img src="/icon.svg" alt="NOCKO" width={18} height={18} style={{ display: 'block' }} />
        </span>
        <span className={styles.logoText}>NOCKO MDM</span>
        <span className={styles.logoBadge}>MSP</span>
      </Link>

      {/* Menu */}
      <ul className={styles.menu}>
        {NAV_ITEMS.map((item) => {
          const active = isActive(item);
          const isOpen = openMenu === item.label;

          return (
            <li key={item.label} className={styles.menuItem}>
              {item.children ? (
                <>
                  <button
                    className={`${styles.menuLink} ${active ? styles.active : ''}`}
                    onClick={() => setOpenMenu(isOpen ? null : item.label)}
                    onMouseEnter={() => setOpenMenu(item.label)}
                  >
                    {item.label}
                    <svg className={`${styles.arrow} ${isOpen ? styles.arrowOpen : ''}`} viewBox="0 0 10 6">
                      <path d="M0 0l5 6 5-6z"/>
                    </svg>
                  </button>
                  {isOpen && (
                    <div className={styles.dropdown} onMouseLeave={() => setOpenMenu(null)}>
                      {item.children.map((child) => {
                        // Exact match: compare full href (path + query) for items with query params,
                        // otherwise use startsWith for pure-path children
                        const hasQuery = child.href.includes('?');
                        const isChildActive = hasQuery
                          ? currentHref === child.href
                          : pathname.startsWith(child.href);
                        return (
                          <Link
                            key={child.href}
                            href={child.href}
                            className={`${styles.dropdownItem} ${isChildActive ? styles.dropdownActive : ''}`}
                            onClick={() => setOpenMenu(null)}
                          >
                            <span className={styles.dropdownIcon} style={{ display:'flex', alignItems:'center' }}>{child.icon}</span>
                            {child.label}
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </>
              ) : (
                <Link
                  href={item.href!}
                  className={`${styles.menuLink} ${active ? styles.active : ''}`}
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ul>

      {/* Right */}
      <div className={styles.right}>
        <div className={styles.searchBox}>
          <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
          <input
            type="text"
            placeholder="Search devices, users…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <button className={styles.iconBtn} title="Remote Control">
          <svg viewBox="0 0 24 24"><path d="M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z"/></svg>
        </button>

        <button className={styles.iconBtn} title="Notifications">
          <svg viewBox="0 0 24 24"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
          <span className={styles.badge}></span>
        </button>

        <button className={styles.iconBtn} title="Quick Actions">
          <svg viewBox="0 0 24 24"><path d="M7 2v11h3v9l7-12h-4l4-8z"/></svg>
        </button>

        <Link href="/admin/profile" className={styles.avatar} title="Profile">
          RK
        </Link>
      </div>
    </nav>
  );
}
