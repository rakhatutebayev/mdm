'use client';
import { useState, useEffect, useCallback } from 'react';
import { getCustomers, createCustomer, deleteCustomer, type Customer } from '@/lib/api';
import styles from './page.module.css';

type ModalMode = 'add' | 'edit' | null;

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState<Set<string>>(new Set());
  const [search, setSearch]       = useState('');
  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [form, setForm]           = useState({ name: '', slug: '' });
  const [editId, setEditId]       = useState<string | null>(null);
  const [saving, setSaving]       = useState(false);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  // ── Load from API ──────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCustomers(await getCustomers());
    } catch { /* backend unavailable */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Derived ────────────────────────────────────────────────────────────────
  const filtered = customers.filter((c) =>
    !search || c.name.toLowerCase().includes(search.toLowerCase())
  );

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((c) => c.id)));
  };

  const toggleRow = (id: string) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const selectedCount    = selected.size;
  const singleSelected   = selectedCount === 1;

  // ── Actions ────────────────────────────────────────────────────────────────
  const openAdd = () => {
    setForm({ name: '', slug: '' });
    setEditId(null);
    setModalMode('add');
  };

  const openEdit = () => {
    const id = [...selected][0];
    const c  = customers.find((x) => x.id === id);
    if (!c) return;
    setForm({ name: c.name, slug: c.slug });
    setEditId(id);
    setModalMode('edit');
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.slug.trim()) return;
    setSaving(true);
    try {
      if (modalMode === 'add') {
        const newC = await createCustomer(form.name.trim(), form.slug.trim().toLowerCase().replace(/\s+/g, '-'));
        setCustomers((prev) => [...prev, newC]);
      }
      // edit: API endpoint not wired yet — optimistic local update
      else if (modalMode === 'edit' && editId) {
        setCustomers((prev) => prev.map((c) => c.id === editId ? { ...c, name: form.name.trim() } : c));
      }
      setModalMode(null);
      setSelected(new Set());
    } catch (e) {
      console.error('Save failed', e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const ids = [...selected];
    try {
      await Promise.all(ids.map((id) => deleteCustomer(id)));
      setCustomers((prev) => prev.filter((c) => !ids.includes(c.id)));
      setSelected(new Set());
    } catch (e) {
      console.error('Delete failed', e);
    }
  };

  const handleRowDelete = async (id: string) => {
    try {
      await deleteCustomer(id);
      setCustomers((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      console.error('Delete failed', e);
    }
  };

  return (
    <div className={styles.page}>
      {/* ── Toolbar ── */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <button className={styles.addBtn} onClick={openAdd}>
            <span className={styles.plus}>+</span>
            Add Customer
          </button>

          <button
            className={styles.actionBtn}
            disabled={!singleSelected}
            onClick={openEdit}
            title="Edit customer"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
              <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm2.92 1.42H5v-.71l9.06-9.06.71.71-9.06 9.06zM20.71 5.63l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83a1 1 0 000-1.41z"/>
            </svg>
            Edit
          </button>

          <button
            className={`${styles.actionBtn} ${styles.deleteBtn}`}
            disabled={selectedCount === 0}
            onClick={handleDelete}
            title="Delete selected"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
              <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zm2.46-7.12l1.41-1.41L12 12.59l2.12-2.12 1.41 1.41L13.41 14l2.12 2.12-1.41 1.41L12 15.41l-2.12 2.12-1.41-1.41L10.59 14l-2.13-2.12zM15.5 4l-1-1h-5l-1 1H5v2h14V4h-3.5z"/>
            </svg>
            Delete
          </button>
        </div>

        <div className={styles.toolbarRight}>
          <span className={styles.totalLabel}>Total: {filtered.length}</span>
          <div className={styles.searchBox}>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
              <path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
            </svg>
            <input
              type="text"
              placeholder="Search customers..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={styles.searchInput}
            />
          </div>
        </div>
      </div>

      {/* ── Table ── */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thCheck}>
                <input type="checkbox" checked={selected.size === filtered.length && filtered.length > 0} onChange={toggleAll} />
              </th>
              <th className={styles.th}>Customer Name</th>
              <th className={styles.th}>Slug</th>
              <th className={styles.th}>Created</th>
              <th className={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className={styles.empty}>Loading…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} className={styles.empty}>No customers found</td></tr>
            ) : (
              filtered.map((c) => (
                <tr
                  key={c.id}
                  className={`${styles.tr} ${selected.has(c.id) ? styles.trSelected : ''}`}
                  onClick={() => toggleRow(c.id)}
                >
                  <td className={styles.tdCheck} onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleRow(c.id)} />
                  </td>
                  <td className={styles.td}>
                    <div className={styles.customerNameCell}>
                      <div className={styles.customerAvatar}>{c.name[0]}</div>
                      <span>{c.name}</span>
                    </div>
                  </td>
                  <td className={styles.td}><code>{c.slug}</code></td>
                  <td className={styles.td}>{new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</td>
                  <td className={styles.td} onClick={(e) => e.stopPropagation()}>
                    <div className={styles.rowActions}>
                      <button
                        className={styles.rowBtn}
                        title="Edit"
                        onClick={() => { setSelected(new Set([c.id])); setTimeout(() => { setForm({ name: c.name, slug: c.slug }); setEditId(c.id); setModalMode('edit'); }, 0); }}
                      >
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                          <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 5.63l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83a1 1 0 000-1.41z"/>
                        </svg>
                      </button>
                      <button
                        className={`${styles.rowBtn} ${styles.rowBtnDanger}`}
                        title="Delete"
                        onClick={() => handleRowDelete(c.id)}
                      >
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                          <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
                        </svg>
                      </button>
                    </div>
                  </td>
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
          <select className={styles.paginationSelect} value={rowsPerPage} onChange={(e) => setRowsPerPage(Number(e.target.value))}>
            {[10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div className={styles.paginationRight}>
          <span className={styles.paginationInfo}>1 – {Math.min(rowsPerPage, filtered.length)} of {filtered.length}</span>
          <button className={styles.pageBtn} disabled>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M15.41 16.59L10.83 12l4.58-4.59L14 6l-6 6 6 6z"/></svg>
          </button>
          <button className={styles.pageBtn} disabled={filtered.length <= rowsPerPage}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>
          </button>
        </div>
      </div>

      {/* ── Add / Edit Modal ── */}
      {modalMode && (
        <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && setModalMode(null)}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>{modalMode === 'add' ? 'Add Customer' : 'Edit Customer'}</h2>
              <button className={styles.modalClose} onClick={() => setModalMode(null)}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.formRow}>
                <label className={styles.formLabel}>Customer Name <span className={styles.required}>*</span></label>
                <input
                  type="text"
                  className={styles.formInput}
                  placeholder="e.g. NOCKO IT"
                  value={form.name}
                  onChange={(e) => {
                    const name = e.target.value;
                    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
                    setForm((f) => ({ ...f, name, slug }));
                  }}
                  autoFocus
                />
              </div>
              <div className={styles.formRow}>
                <label className={styles.formLabel}>Slug <span className={styles.required}>*</span></label>
                <input
                  type="text"
                  className={styles.formInput}
                  placeholder="e.g. nocko-it"
                  value={form.slug}
                  onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))}
                />
              </div>
            </div>
            <div className={styles.modalFooter}>
              <button className={styles.saveBtn} onClick={handleSave} disabled={!form.name.trim() || !form.slug.trim() || saving}>
                {saving ? 'Saving…' : modalMode === 'add' ? 'Add Customer' : 'Save Changes'}
              </button>
              <button className={styles.cancelBtn} onClick={() => setModalMode(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
