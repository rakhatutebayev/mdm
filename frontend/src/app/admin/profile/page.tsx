'use client';

import Link from 'next/link';
import type { CSSProperties } from 'react';

const cardStyle: CSSProperties = {
  maxWidth: 720,
  margin: '48px auto',
  padding: 24,
  borderRadius: 16,
  background: '#1f2230',
  border: '1px solid rgba(255,255,255,0.08)',
  color: '#f3f4f6',
  boxShadow: '0 20px 40px rgba(0,0,0,0.25)',
};

const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '160px 1fr',
  gap: 12,
  marginTop: 20,
};

const labelStyle: CSSProperties = {
  color: '#9ca3af',
  fontWeight: 600,
};

const valueStyle: CSSProperties = {
  color: '#f3f4f6',
};

const linkStyle: CSSProperties = {
  display: 'inline-flex',
  marginTop: 20,
  color: '#8fb4ff',
  textDecoration: 'none',
  fontWeight: 600,
};

export default function AdminProfilePage() {
  return (
    <section style={{ padding: '0 20px 40px' }}>
      <div style={cardStyle}>
        <h1 style={{ margin: 0, fontSize: 28 }}>Admin Profile</h1>
        <p style={{ marginTop: 12, color: '#b6bcc8', lineHeight: 1.6 }}>
          This account overview page is available so the top-right profile link no
          longer points to a missing route.
        </p>

        <div style={gridStyle}>
          <div style={labelStyle}>User</div>
          <div style={valueStyle}>RK</div>
          <div style={labelStyle}>Role</div>
          <div style={valueStyle}>Administrator</div>
          <div style={labelStyle}>Portal</div>
          <div style={valueStyle}>NOCKO MDM</div>
        </div>

        <Link href="/admin/settings" style={linkStyle}>
          Manage Settings
        </Link>
      </div>
    </section>
  );
}
