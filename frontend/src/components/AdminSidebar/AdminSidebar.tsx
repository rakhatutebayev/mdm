'use client';
import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import styles from './AdminSidebar.module.css';

type SideItem = { label: string; href: string };
type SideSection = { group: string; items: SideItem[] };

const SECTIONS: SideSection[] = [
  {
    group: 'Customers',
    items: [
      { label: 'Customers', href: '/admin/customers' },
    ],
  },
  {
    group: 'Administration',
    items: [
      { label: 'Users', href: '/admin/users' },
      { label: 'Roles', href: '/admin/roles' },
      { label: 'Settings', href: '/admin/settings' },
      { label: 'Licenses', href: '/admin/licenses' },
    ],
  },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggleGroup = (group: string) =>
    setCollapsed((prev) => ({ ...prev, [group]: !prev[group] }));

  return (
    <aside className={styles.sidebar}>
      {SECTIONS.map((section) => {
        const isCollapsed = collapsed[section.group];
        return (
          <div key={section.group} className={styles.section}>
            <button
              className={styles.groupBtn}
              onClick={() => toggleGroup(section.group)}
            >
              <svg
                className={`${styles.chevron} ${isCollapsed ? styles.chevronCollapsed : ''}`}
                viewBox="0 0 10 6" width="10" height="6"
                fill="none" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round"
              >
                <polyline points="1,1 5,5 9,1" />
              </svg>
              {section.group}
            </button>

            {!isCollapsed && (
              <div className={styles.items}>
                {section.items.map((item) => {
                  const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`${styles.item} ${isActive ? styles.itemActive : ''}`}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </aside>
  );
}
