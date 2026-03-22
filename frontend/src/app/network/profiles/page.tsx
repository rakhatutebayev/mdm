'use client';

import { useState, useEffect, useCallback } from 'react';
import styles from './profiles.module.css';

interface Profile { id: number; name: string; vendor: string; version: string; description: string; }
interface Template { id: number; name: string; description: string; items: Item[]; }
interface Item {
  id: number; key: string; name: string;
  value_type: string; poll_class: string; interval_sec: number;
}

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [showNewTemplate, setShowNewTemplate] = useState(false);
  const [newItemFor, setNewItemFor] = useState<number | null>(null); // template_id

  // Zabbix import
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    ok: boolean; profile_name: string; templates_created: number;
    items_created: number; items_skipped: number; warnings: string[];
  } | null>(null);

  // New profile form
  const [npName, setNpName] = useState('');
  const [npVendor, setNpVendor] = useState('');
  const [npVersion, setNpVersion] = useState('1.0.0');
  const [npDesc, setNpDesc] = useState('');

  // New template form
  const [ntName, setNtName] = useState('');

  // New item form
  const [niKey, setNiKey] = useState('');
  const [niName, setNiName] = useState('');
  const [niType, setNiType] = useState('uint');
  const [niClass, setNiClass] = useState('fast');
  const [niInterval, setNiInterval] = useState(60);

  const fetchProfiles = useCallback(async () => {
    const r = await fetch('/api/agent/profiles');
    if (r.ok) setProfiles(await r.json());
    setLoading(false);
  }, []);

  const fetchTemplates = useCallback(async (profileId: number) => {
    const r = await fetch(`/api/agent/profiles/${profileId}/templates`);
    if (r.ok) setTemplates(await r.json());
  }, []);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);
  useEffect(() => { if (selected) fetchTemplates(selected.id); }, [selected, fetchTemplates]);

  async function createProfile(e: React.FormEvent) {
    e.preventDefault();
    const r = await fetch('/api/agent/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: npName, vendor: npVendor, version: npVersion, description: npDesc }),
    });
    if (r.ok) {
      await fetchProfiles();
      setShowNewProfile(false);
      setNpName(''); setNpVendor(''); setNpVersion('1.0.0'); setNpDesc('');
    }
  }

  async function createTemplate(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    const r = await fetch(`/api/agent/profiles/${selected.id}/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: ntName }),
    });
    if (r.ok) {
      await fetchTemplates(selected.id);
      setShowNewTemplate(false);
      setNtName('');
    }
  }

  async function createItem(e: React.FormEvent) {
    e.preventDefault();
    if (!newItemFor) return;
    const r = await fetch(`/api/agent/templates/${newItemFor}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key: niKey, name: niName, value_type: niType,
        poll_class: niClass, interval_sec: niInterval,
      }),
    });
    if (r.ok) {
      if (selected) await fetchTemplates(selected.id);
      setNewItemFor(null);
      setNiKey(''); setNiName(''); setNiType('uint'); setNiClass('fast'); setNiInterval(60);
    } else {
      const err = await r.json();
      alert(err.detail || 'Failed to create item');
    }
  }

  async function importZabbix(e: React.FormEvent) {
    e.preventDefault();
    if (!importFile) return;
    setImporting(true);
    setImportResult(null);
    const fd = new FormData();
    fd.append('file', importFile);
    try {
      const r = await fetch('/api/agent/profiles/import/zabbix', {
        method: 'POST',
        body: fd,
      });
      const data = await r.json();
      if (r.ok) {
        setImportResult(data);
        await fetchProfiles();
      } else {
        setImportResult({ ok: false, profile_name: '', templates_created: 0,
          items_created: 0, items_skipped: 0, warnings: [data.detail || 'Import failed'] });
      }
    } catch (err) {
      setImportResult({ ok: false, profile_name: '', templates_created: 0,
        items_created: 0, items_skipped: 0, warnings: [String(err)] });
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className={styles.page}>
      {/* Zabbix Import Modal */}
      {showImport && (
        <div className={styles.modalOverlay} onClick={() => { setShowImport(false); setImportResult(null); setImportFile(null); }}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>📥 Import Zabbix Template</span>
              <button className={styles.ghostBtn} onClick={() => { setShowImport(false); setImportResult(null); setImportFile(null); }}>✕</button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.muted} style={{ marginBottom: 12, fontSize: 13 }}>
                Supports <strong>.xml</strong> (Zabbix 1–6), <strong>.json</strong> (Zabbix 4+), <strong>.yaml / .yml</strong> (Zabbix 6+)
              </p>
              {!importResult ? (
                <form onSubmit={importZabbix}>
                  <div className={styles.dropZone}>
                    <input
                      id="zbx-file-input"
                      type="file"
                      accept=".xml,.json,.yaml,.yml"
                      style={{ display: 'none' }}
                      onChange={e => setImportFile(e.target.files?.[0] || null)}
                    />
                    <label htmlFor="zbx-file-input" className={styles.dropLabel}>
                      {importFile ? (
                        <span>📄 <strong>{importFile.name}</strong> ({(importFile.size / 1024).toFixed(1)} KB)</span>
                      ) : (
                        <span>Click to select a Zabbix template file<br /><span className={styles.muted}>.xml · .json · .yaml · .yml</span></span>
                      )}
                    </label>
                  </div>
                  <div className={styles.formActions} style={{ marginTop: 12 }}>
                    <button type="submit" className={styles.primaryBtn} disabled={!importFile || importing}>
                      {importing ? 'Importing…' : 'Import'}
                    </button>
                    <button type="button" className={styles.ghostBtn} onClick={() => { setShowImport(false); setImportFile(null); }}>Cancel</button>
                  </div>
                </form>
              ) : (
                <div>
                  {importResult.ok ? (
                    <div className={styles.importSuccess}>
                      <div className={styles.importSuccessTitle}>✅ Import successful</div>
                      <div><strong>{importResult.profile_name}</strong></div>
                      <div className={styles.importStats}>
                        <span>{importResult.templates_created} templates</span>
                        <span>{importResult.items_created} items</span>
                        {importResult.items_skipped > 0 && <span className={styles.muted}>{importResult.items_skipped} skipped</span>}
                      </div>
                    </div>
                  ) : (
                    <div className={styles.importError}>❌ Import failed</div>
                  )}
                  {importResult.warnings.length > 0 && (
                    <details style={{ marginTop: 12 }}>
                      <summary className={styles.muted} style={{ cursor: 'pointer', fontSize: 12 }}>
                        {importResult.warnings.length} warning{importResult.warnings.length > 1 ? 's' : ''}
                      </summary>
                      <ul className={styles.warnList}>
                        {importResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                      </ul>
                    </details>
                  )}
                  <div className={styles.formActions} style={{ marginTop: 16 }}>
                    <button className={styles.primaryBtn} onClick={() => { setShowImport(false); setImportResult(null); setImportFile(null); }}>Done</button>
                    <button className={styles.ghostBtn} onClick={() => { setImportResult(null); setImportFile(null); }}>Import another</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>SNMP Profiles</h1>
          <p className={styles.subtitle}>Manage device profiles, templates, and metric keys</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={styles.ghostBtn} onClick={() => { setShowImport(true); setImportResult(null); }}
            title="Import Zabbix template (.xml, .json, .yaml)">
            📥 Import Zabbix
          </button>
          <button className={styles.primaryBtn} onClick={() => setShowNewProfile(true)}>
            + New Profile
          </button>
        </div>
      </div>

      <div className={styles.layout}>
        {/* Profile list */}
        <div className={styles.sidebar}>
          <div className={styles.sideHeader}>Profiles</div>
          {loading ? (
            <div className={styles.muted}>Loading…</div>
          ) : profiles.length === 0 ? (
            <div className={styles.empty}>No profiles yet.</div>
          ) : profiles.map(p => (
            <button
              key={p.id}
              className={`${styles.profileItem} ${selected?.id === p.id ? styles.profileItemActive : ''}`}
              onClick={() => { setSelected(p); setTemplates([]); }}
            >
              <div className={styles.profileName}>{p.name}</div>
              <div className={styles.profileMeta}>{p.vendor} · v{p.version}</div>
            </button>
          ))}

          {/* New profile form */}
          {showNewProfile && (
            <form className={styles.inlineForm} onSubmit={createProfile}>
              <div className={styles.formTitle}>New Profile</div>
              <input className={styles.input} placeholder="Name *" value={npName} onChange={e => setNpName(e.target.value)} required />
              <input className={styles.input} placeholder="Vendor" value={npVendor} onChange={e => setNpVendor(e.target.value)} />
              <input className={styles.input} placeholder="Version" value={npVersion} onChange={e => setNpVersion(e.target.value)} />
              <textarea className={styles.textarea} placeholder="Description" value={npDesc} onChange={e => setNpDesc(e.target.value)} rows={2} />
              <div className={styles.formActions}>
                <button type="submit" className={styles.primaryBtn}>Create</button>
                <button type="button" className={styles.ghostBtn} onClick={() => setShowNewProfile(false)}>Cancel</button>
              </div>
            </form>
          )}
        </div>

        {/* Templates + Items panel */}
        <div className={styles.main}>
          {!selected ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>🗂️</div>
              <p>Select a profile to view its templates and items.</p>
            </div>
          ) : (
            <>
              <div className={styles.profileHeader}>
                <div>
                  <h2 className={styles.profileTitle}>{selected.name}</h2>
                  <div className={styles.profileDesc}>{selected.description}</div>
                </div>
                <button className={styles.primaryBtn} onClick={() => setShowNewTemplate(true)}>
                  + New Template
                </button>
              </div>

              {showNewTemplate && (
                <form className={styles.newTemplateForm} onSubmit={createTemplate}>
                  <input className={styles.input} placeholder="Template name *" value={ntName} onChange={e => setNtName(e.target.value)} required />
                  <button type="submit" className={styles.primaryBtn}>Create</button>
                  <button type="button" className={styles.ghostBtn} onClick={() => setShowNewTemplate(false)}>Cancel</button>
                </form>
              )}

              {templates.length === 0 ? (
                <div className={styles.emptyState}>
                  <p>No templates yet. Create one to start defining metric keys.</p>
                </div>
              ) : templates.map(tmpl => (
                <div key={tmpl.id} className={styles.templateCard}>
                  <div className={styles.templateHeader}>
                    <div>
                      <span className={styles.templateName}>{tmpl.name}</span>
                      <span className={styles.templateMeta}> · {tmpl.items.length} item{tmpl.items.length !== 1 ? 's' : ''}</span>
                    </div>
                    <button className={styles.addItemBtn} onClick={() => setNewItemFor(tmpl.id)}>
                      + Item
                    </button>
                  </div>

                  {/* Item list */}
                  {tmpl.items.length > 0 && (
                    <table className={styles.itemTable}>
                      <thead>
                        <tr>
                          <th>Key</th>
                          <th>Name</th>
                          <th>Type</th>
                          <th>Class</th>
                          <th>Interval</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tmpl.items.map(item => (
                          <tr key={item.id}>
                            <td className={styles.mono}>{item.key}</td>
                            <td>{item.name}</td>
                            <td><span className={styles.typePill}>{item.value_type}</span></td>
                            <td><span className={`${styles.classPill} ${styles[`class_${item.poll_class}`]}`}>{item.poll_class}</span></td>
                            <td className={styles.muted}>{item.interval_sec}s</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}

                  {/* Inline new item form */}
                  {newItemFor === tmpl.id && (
                    <form className={styles.newItemForm} onSubmit={createItem}>
                      <div className={styles.formTitle}>New Item</div>
                      <div className={styles.itemFormGrid}>
                        <input className={styles.input} placeholder="Key *" value={niKey} onChange={e => setNiKey(e.target.value)} required />
                        <input className={styles.input} placeholder="Display name" value={niName} onChange={e => setNiName(e.target.value)} />
                        <select className={styles.select} value={niType} onChange={e => setNiType(e.target.value)}>
                          <option value="uint">uint</option>
                          <option value="float">float</option>
                          <option value="string">string</option>
                          <option value="text">text</option>
                          <option value="log">log</option>
                        </select>
                        <select className={styles.select} value={niClass} onChange={e => setNiClass(e.target.value)}>
                          <option value="fast">fast</option>
                          <option value="slow">slow</option>
                          <option value="inventory">inventory</option>
                          <option value="lld">lld</option>
                        </select>
                        <input className={styles.input} type="number" placeholder="Interval (sec)" value={niInterval}
                          onChange={e => setNiInterval(Number(e.target.value))} min={5} />
                      </div>
                      <div className={styles.formActions}>
                        <button type="submit" className={styles.primaryBtn}>Add Item</button>
                        <button type="button" className={styles.ghostBtn} onClick={() => setNewItemFor(null)}>Cancel</button>
                      </div>
                    </form>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
