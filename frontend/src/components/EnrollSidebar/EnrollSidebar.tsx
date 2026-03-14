'use client';
import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams, useRouter } from 'next/navigation';
import { getCustomers, type Customer } from '@/lib/api';
import styles from './EnrollSidebar.module.css';


type SideItem = { label: string; href: string };
type SideSection = { group: string; items: SideItem[] };

const SECTIONS: SideSection[] = [
  {
    group: 'Enroll',
    items: [
      { label: 'Devices', href: '/enrollment' },
      { label: 'Users', href: '/enrollment/users' },
      { label: 'Directory Services', href: '/enrollment/directory' },
    ],
  },
  {
    group: 'Windows',
    items: [
      { label: 'Enroll', href: '/enrollment/windows' },
      { label: 'Azure Enrollment (AutoPilot)', href: '/enrollment/windows/autopilot' },
      { label: 'Deployment Package', href: '/enrollment/windows/package' },
    ],
  },
];

export default function EnrollSidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();

  const currentHref = searchParams.toString() ? `${pathname}?${searchParams.toString()}` : pathname;

  // Customer list from API
  const [customers, setCustomers] = useState<Customer[]>([]);
  useEffect(() => {
    getCustomers()
      .then(setCustomers)
      .catch(() => {/* backend not available */});
  }, []);

  const selectedCustomerId = searchParams.get('customer') || '';
  const selectedCustomer = customers.find((c) => c.id === selectedCustomerId || c.slug === selectedCustomerId);
  const [custOpen, setCustOpen] = useState(false);
  const [custSearch, setCustSearch] = useState('');
  const custRef = useRef<HTMLDivElement>(null);

  const filteredCustomers = customers.filter((c) =>
    c.name.toLowerCase().includes(custSearch.toLowerCase())
  );

  const selectCustomer = (id: string) => {
    setCustOpen(false);
    setCustSearch('');
    const params = new URLSearchParams(searchParams.toString());
    params.set('customer', id);
    router.push(`${pathname}?${params.toString()}`);
  };

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (custRef.current && !custRef.current.contains(e.target as Node)) {
        setCustOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Nav section collapse state
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggleGroup = (group: string) =>
    setCollapsed((prev) => ({ ...prev, [group]: !prev[group] }));

  return (
    <aside className={styles.sidebar}>
      {/* ── Customer Selector ── */}
      <div className={styles.customerWrap} ref={custRef}>
        <div className={styles.customerLabel}>Customers :</div>
        <button
          className={styles.customerBtn}
          onClick={() => setCustOpen((v) => !v)}
        >
          <span className={styles.customerName}>{selectedCustomer?.name ?? 'Select customer…'}</span>
          <svg
            className={`${styles.custChevron} ${custOpen ? styles.custChevronOpen : ''}`}
            viewBox="0 0 10 6" width="10" height="6"
            fill="none" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round"
          >
            <polyline points="1,1 5,5 9,1" />
          </svg>
        </button>

        {custOpen && (
          <div className={styles.custDropdown}>
            {/* Search */}
            <div className={styles.custSearchWrap}>
              <input
                type="text"
                className={styles.custSearch}
                placeholder="Search"
                value={custSearch}
                onChange={(e) => setCustSearch(e.target.value)}
                autoFocus
              />
              <svg viewBox="0 0 24 24" width="13" height="13" fill="#8b90a4" className={styles.custSearchIcon}>
                <path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
              </svg>
            </div>
            {/* Options */}
            <div className={styles.custOptions}>
              {filteredCustomers.map((c) => (
                <button
                  key={c.id}
                  className={`${styles.custOption} ${c.id === selectedCustomer?.id ? styles.custOptionActive : ''}`}
                  onClick={() => selectCustomer(c.slug)}
                >
                  {c.name}
                  {c.id === selectedCustomer?.id && (
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="#4a7cff">
                      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
                    </svg>
                  )}
                </button>
              ))}
              {filteredCustomers.length === 0 && (
                <div className={styles.custNoResults}>No customers found</div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className={styles.divider} />

      {/* ── Nav Sections ── */}
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
                  const isActive = pathname === item.href;
                  return (
                    <Link
                      key={item.href}
                      href={`${item.href}?customer=${selectedCustomer?.slug ?? ''}`}
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
