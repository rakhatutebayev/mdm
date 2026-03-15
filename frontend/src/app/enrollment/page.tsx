'use client';
export const dynamic = 'force-dynamic';
import { useState, useRef, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { WindowsIcon } from '@/components/icons/PlatformIcons';
import EnrollWindowsModal from '@/components/EnrollWindowsModal/EnrollWindowsModal';
import { getDevices, updateDeviceStatus, deleteDevice, type DeviceListItem } from '@/lib/api';
import styles from './page.module.css';

const CUSTOMERS: Record<string, string> = {
  default: 'DEFAULT_CUSTOMER',
  nocko: 'NOCKO IT',
  strattech: 'Strategic Technology Solutions',
  almatygroup: 'Almaty Group',
  delta: 'Delta Corp',
};


const COLUMNS = [
  { key: 'deviceName', label: 'Device Name', visible: true },
  { key: 'platform', label: 'Platform', visible: true },
  { key: 'owner', label: 'Owner', visible: true },
  { key: 'enrollmentMethod', label: 'Enrollment Method', visible: true },
  { key: 'enrolledTime', label: 'Enrolled Time', visible: true },
  { key: 'status', label: 'Status', visible: true },
  { key: 'actions', label: 'Actions', visible: true },
];


export default function EnrollmentDevicesPage() {
  const searchParams = useSearchParams();
  const customerId = searchParams.get('customer') || 'default';

  // ── API state ──────────────────────────────────────────────────────────────
  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);

  const fetchDevices = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const data = await getDevices(customerId);
      setDevices(data);
    } catch (e) {
      setApiError('Could not load devices — is the backend running?');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { fetchDevices(); }, [fetchDevices]);

  // ── UI state ───────────────────────────────────────────────────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [colsOpen, setColsOpen] = useState(false);
  const [columns, setColumns] = useState(COLUMNS);
  const [search, setSearch] = useState('');
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [showEnrollModal, setShowEnrollModal] = useState(false);
  const [openActionMenu, setOpenActionMenu] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 });

  // Approve Enrollment — calls API then updates local state
  const approveEnrollment = async (deviceId: string) => {
    setOpenActionMenu(null);
    try {
      const updated = await updateDeviceStatus(deviceId, 'Enrolled');
      setDevices((prev) =>
        prev.map((d) => (d.id === updated.id ? { ...d, status: updated.status, enrolled_at: updated.enrolled_at } : d))
      );
    } catch (e) {
      console.error('Failed to approve enrollment', e);
    }
  };

  const handleDeprovision = async (deviceId: string, deviceName: string) => {
    setOpenActionMenu(null);
    if (!confirm(`Delete device "${deviceName}" from the system? This cannot be undone.`)) return;
    try {
      await deleteDevice(deviceId);
      setDevices((prev) => prev.filter((d) => d.id !== deviceId));
    } catch (e) {
      console.error('Failed to delete device', e);
      alert('Could not delete the device. Please try again.');
    }
  };

  const enrollRef = useRef<HTMLDivElement>(null);
  const exportRef = useRef<HTMLDivElement>(null);
  const colsRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (enrollRef.current && !enrollRef.current.contains(e.target as Node)) setEnrollOpen(false);
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false);
      if (colsRef.current && !colsRef.current.contains(e.target as Node)) setColsOpen(false);
      // Close row action menu on outside click
      const target = e.target as HTMLElement;
      if (!target.closest('[data-action-menu]')) setOpenActionMenu(null);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const toggleAll = () => {
    if (selected.size === devices.length) setSelected(new Set());
    else setSelected(new Set(devices.map((d) => d.id)));
  };

  const toggleCol = (key: string) =>
    setColumns((prev) => prev.map((c) => (c.key === key ? { ...c, visible: !c.visible } : c)));

  const visibleCols = columns.filter((c) => c.visible);
  const filtered = devices.filter(
    (d) =>
      !search ||
        d.owner.toLowerCase().includes(search.toLowerCase()) ||
        d.device_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <>
    <div className={styles.page}>
      {/* ── Toolbar ── */}
      <div className={styles.toolbar}>
        {/* Left */}
        <div className={styles.toolbarLeft}>
          {/* Customer badge */}
          <span className={styles.customerBadge}>
            <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
              <path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/>
            </svg>
            {customerId}
          </span>
          {/* Enroll Device dropdown */}
          <div className={styles.dropdownWrap} ref={enrollRef}>
            <button
              className={styles.enrollBtn}
              onClick={() => setEnrollOpen((v) => !v)}
            >
              <span className={styles.enrollPlus}>+</span>
              Enroll Device
              <svg className={styles.btnChevron} viewBox="0 0 10 6" width="10" height="6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1,1 5,5 9,1" />
              </svg>
            </button>
            {enrollOpen && (
              <div className={styles.dropdownMenu}>
                <button className={styles.dropdownItem} onClick={() => { setEnrollOpen(false); setShowEnrollModal(true); }}>
                  <span className={styles.dropdownIcon}><WindowsIcon size={14} /></span>
                  Windows
                </button>
              </div>
            )}
          </div>

          {/* Filter */}
          <button className={styles.iconBtn} title="Filter">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
              <path d="M4.25 5.61A1 1 0 015.16 4h13.68a1 1 0 01.91 1.61l-5.43 7.25V19a1 1 0 01-1.45.89l-2-.9A1 1 0 0110 18v-5.14L4.25 5.61z"/>
            </svg>
          </button>

          {/* More */}
          <button className={styles.iconBtn} title="More options">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
              <circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>
            </svg>
          </button>
        </div>

        {/* Right */}
        <div className={styles.toolbarRight}>
          <span className={styles.totalLabel}>Total Records</span>

          {/* Refresh */}
          <button className={styles.iconBtn} title="Refresh">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
              <path d="M17.65 6.35A7.96 7.96 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
            </svg>
          </button>

          {/* Search */}
          <div className={styles.searchBox}>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
              <path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
            </svg>
            <input
              type="text"
              placeholder="Search..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={styles.searchInput}
            />
          </div>

          {/* Columns */}
          <div className={styles.dropdownWrap} ref={colsRef}>
            <button className={styles.iconBtn} title="Show/hide columns" onClick={() => setColsOpen((v) => !v)}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                <path d="M3 5h18v2H3zm0 4h18v2H3zm0 4h18v2H3zm0 4h18v2H3z"/>
              </svg>
            </button>
            {colsOpen && (
              <div className={`${styles.dropdownMenu} ${styles.dropdownRight}`}>
                <div className={styles.dropdownHeader}>Columns</div>
                {columns.map((col) => (
                  <label key={col.key} className={styles.colToggle}>
                    <input type="checkbox" checked={col.visible} onChange={() => toggleCol(col.key)} />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Export */}
          <div className={styles.dropdownWrap} ref={exportRef}>
            <button className={styles.iconBtn} title="Export" onClick={() => setExportOpen((v) => !v)}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                <path d="M19 9h-4V3H9v6H5l7 7 7-7zm-8 2V5h2v6h1.17L12 13.17 9.83 11H11zm-6 7h14v2H5z"/>
              </svg>
            </button>
            {exportOpen && (
              <div className={`${styles.dropdownMenu} ${styles.dropdownRight}`}>
                <button className={styles.dropdownItem}>
                  <span className={styles.excelIcon}>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="#1d6f42"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 7V3.5L18.5 9H13zM8.5 18l-2-3 2-3h1.5l-2 3 2 3H8.5zm5 0h-1.5l-2-3 2-3H13l-2 3 2 3z"/></svg>
                  </span>
                  Excel
                </button>
                <button className={styles.dropdownItem}>
                  <span className={styles.pdfIcon}>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="#e53935"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 7V3.5L18.5 9H13zM7.5 18h-.8v-5h2.3c.9 0 1.5.6 1.5 1.5s-.6 1.5-1.5 1.5H7.5v2zm0-2.7h1.5c.4 0 .7-.2.7-.8s-.3-.8-.7-.8H7.5v1.6zm5.2 2.7h-1.5v-5h1.5c1.5 0 2.5.9 2.5 2.5s-1 2.5-2.5 2.5zm0-4.2h-.8v3.5h.8c.9 0 1.7-.6 1.7-1.8s-.8-1.7-1.7-1.7zm4.3 0h-1.6V16h1.5v.8h-1.5v1.2H17V18h-2.8v-5H17v.8z"/></svg>
                  </span>
                  PDF
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Table ── */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thCheck}>
                <input
                  type="checkbox"
                  checked={selected.size === devices.length && devices.length > 0}
                  onChange={toggleAll}
                />
              </th>
              <th className={styles.thIcon}></th>
              {visibleCols.map((col) => (
                <th key={col.key} className={styles.th}>{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={visibleCols.length + 2} className={styles.empty}>Loading devices…</td></tr>
            ) : apiError ? (
              <tr><td colSpan={visibleCols.length + 2} className={styles.empty}>{apiError}</td></tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={visibleCols.length + 2} className={styles.empty}>
                  No devices found
                </td>
              </tr>
            ) : (
              filtered.map((d) => (
                <tr key={d.id} className={`${styles.tr} ${selected.has(d.id) ? styles.trSelected : ''}`}>
                  <td className={styles.tdCheck}>
                    <input
                      type="checkbox"
                      checked={selected.has(d.id)}
                      onChange={() => {
                        const next = new Set(selected);
                        next.has(d.id) ? next.delete(d.id) : next.add(d.id);
                        setSelected(next);
                      }}
                    />
                  </td>
                  <td className={styles.tdIcon}>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="#8b90a4">
                      <path d="M20 3H4v10c0 2.21 1.79 4 4 4h6c2.21 0 4-1.79 4-4v-3h2c1.11 0 2-.89 2-2V5c0-1.11-.89-2-2-2zm0 5h-2V5h2v3z"/>
                    </svg>
                  </td>
                  {visibleCols.map((col) => (
                    <td key={col.key} className={styles.td}>
                      {col.key === 'deviceName' ? (
                        <Link href={`/devices/${d.id}?customer=${customerId}`} className={styles.deviceLink}>
                          {d.device_name}
                        </Link>
                      ) : col.key === 'status' ? (
                        <span className={`${styles.badge} ${
                          d.status === 'Enrolled' ? styles.badgeGreen :
                          d.status === 'Pending'  ? styles.badgeOrange :
                          d.status === 'Failed'   ? styles.badgeRed : ''
                        }`}>{d.status}</span>
                      ) : col.key === 'platform' ? (
                        <span className={styles.platformCell}>
                          {d.platform === 'Windows' && (
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="#0078d4"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/></svg>
                          )}
                          {d.platform === 'macOS' && (
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="#555"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>
                          )}
                          {d.platform === 'iOS' && (
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="#555"><path d="M17 1H7C5.9 1 5 1.9 5 3v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-2-2-2zm-5 21c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm5-3H7V4h10v15z"/></svg>
                          )}
                          {d.platform === 'Android' && (
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="#3ddc84"><path d="M6 18c0 .55.45 1 1 1h1v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h2v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h1c.55 0 1-.45 1-1V8H6v10zM3.5 8C2.67 8 2 8.67 2 9.5v7c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-7C5 8.67 4.33 8 3.5 8zm17 0c-.83 0-1.5.67-1.5 1.5v7c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-7c0-.83-.67-1.5-1.5-1.5zm-4.97-5.84l1.3-1.3c.2-.2.2-.51 0-.71-.2-.2-.51-.2-.71 0l-1.48 1.48C13.85 1.23 12.95 1 12 1c-.96 0-1.86.23-2.66.63L7.85.15c-.2-.2-.51-.2-.71 0-.2.2-.2.51 0 .71l1.31 1.31C7.08 3.04 6 4.6 6 6.5v.5h12v-.5c0-1.9-1.08-3.46-2.47-4.34zM10 5H9V4h1v1zm5 0h-1V4h1v1z"/></svg>
                          )}
                          <span style={{marginLeft: 5}}>{d.platform}</span>
                        </span>
                      ) : col.key === 'actions' ? (
                        <div className={styles.actionMenuWrap} data-action-menu>
                          <button
                            className={styles.dotsBtn}
                            title="Actions"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (openActionMenu === d.id) {
                                setOpenActionMenu(null);
                              } else {
                                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
                                setOpenActionMenu(d.id);
                              }
                            }}
                          >
                            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                              <circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>
                            </svg>
                          </button>
                        </div>
                      ) : col.key === 'owner' ? d.owner
                      : col.key === 'enrollmentMethod' ? d.enrollment_method
                      : col.key === 'enrolledTime' ? (d.enrolled_at ? new Date(d.enrolled_at).toLocaleString() : '—')
                      : null}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ── */}
      <div className={styles.pagination}>
        <div className={styles.paginationLeft}>
          <span className={styles.paginationLabel}>Rows per page:</span>
          <select
            className={styles.paginationSelect}
            value={rowsPerPage}
            onChange={(e) => setRowsPerPage(Number(e.target.value))}
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div className={styles.paginationRight}>
          <span className={styles.paginationInfo}>
            1 – {Math.min(rowsPerPage, filtered.length)} of{' '}
            <span className={styles.paginationTotal}>Total Records</span>
          </span>
          <button className={styles.pageBtn} disabled>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M15.41 16.59L10.83 12l4.58-4.59L14 6l-6 6 6 6z"/></svg>
          </button>
          <button className={styles.pageBtn} disabled={filtered.length <= rowsPerPage}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>
          </button>
        </div>
      </div>
    </div>

    {/* Windows Enrollment Modal */}
    {showEnrollModal && (
      <EnrollWindowsModal onClose={() => setShowEnrollModal(false)} />
    )}

    {/* Fixed action dropdown — outside overflow:auto to not get clipped */}
    {openActionMenu && (() => {
      const activeDevice = filtered.find((d) => d.id === openActionMenu);
      const effectiveStatus = activeDevice ? activeDevice.status : '';
      return (
        <div
          data-action-menu
          className={styles.actionDropdown}
          style={{ position: 'fixed', top: menuPos.top, right: menuPos.right }}
        >
          {/* Approve Enrollment — only for Pending devices */}
          {effectiveStatus === 'Pending' && (
            <button
              className={styles.actionItem}
              onClick={() => approveEnrollment(openActionMenu)}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" style={{color:'#16a34a'}}>
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
              </svg>
              Approve Enrollment
            </button>
          )}
          <button
              className={styles.actionItem}
              onClick={() => {
                const dev = filtered.find((d) => d.id === openActionMenu);
                handleDeprovision(openActionMenu, dev?.device_name || openActionMenu);
              }}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" style={{color:'#ef4444'}}>
                <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
              </svg>
              Deprovision (Delete)
            </button>
          <button className={styles.actionItem} onClick={() => setOpenActionMenu(null)}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" style={{color:'#4a7cff'}}>
              <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
            </svg>
            Re-Assign User
          </button>
        </div>
      );
    })()}
    </>
  );
}
