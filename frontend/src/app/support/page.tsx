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

const mutedStyle: CSSProperties = {
  color: '#b6bcc8',
  lineHeight: 1.6,
};

const linkStyle: CSSProperties = {
  display: 'inline-flex',
  marginTop: 16,
  color: '#8fb4ff',
  textDecoration: 'none',
  fontWeight: 600,
};

export default function SupportPage() {
  return (
    <section style={{ padding: '0 20px 40px' }}>
      <div style={cardStyle}>
        <h1 style={{ margin: '0 0 12px', fontSize: 28 }}>Support</h1>
        <p style={mutedStyle}>
          Support tools are being organized into the admin area. For now, use the
          settings page to review deployment and agent configuration, or return to
          the dashboard.
        </p>
        <Link href="/admin/settings" style={linkStyle}>
          Open Admin Settings
        </Link>
      </div>
    </section>
  );
}
