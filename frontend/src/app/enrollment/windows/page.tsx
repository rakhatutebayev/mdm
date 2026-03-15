'use client';
export const dynamic = 'force-dynamic';
import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { getCustomers } from '@/lib/api';
import styles from './page.module.css';

export default function WindowsEnrollPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const customerParam = searchParams.get('customer');
  const isPlaceholderCustomer = !customerParam || customerParam === 'default';
  const [customerId, setCustomerId] = useState(isPlaceholderCustomer ? '' : customerParam);
  const [customerName, setCustomerName] = useState(isPlaceholderCustomer ? 'Select customer' : customerParam);

  useEffect(() => {
    getCustomers()
      .then((list) => {
        if (isPlaceholderCustomer && list.length > 0) {
          const fallback = list[0];
          const nextCustomerId = fallback.slug || fallback.id;
          setCustomerId(nextCustomerId);
          setCustomerName(fallback.name);
          router.replace(`/enrollment/windows?customer=${nextCustomerId}`);
          return;
        }
        const activeCustomerId = isPlaceholderCustomer ? customerId : (customerParam || customerId);
        const match = list.find((c) => c.slug === activeCustomerId || c.id === activeCustomerId);
        if (match) {
          setCustomerId(match.slug || match.id);
          setCustomerName(match.name);
        }
      })
      .catch(() => {});
  }, [customerId, customerParam, isPlaceholderCustomer, router]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.customerPill}>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
              <path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/>
            </svg>
            {customerName}
          </div>
          <h1 className={styles.title}>Enroll Windows Device</h1>
          <p className={styles.subtitle}>
            Choose an enrollment method for <strong>{customerName}</strong>.
          </p>
        </div>
      </div>

      {/* Method cards */}
      <div className={styles.methodGrid}>
        <Link
          href={`/enrollment/windows/package?customer=${customerId}`}
          className={styles.methodCard}
        >
          <div className={styles.methodIcon}>📦</div>
          <div className={styles.methodTitle}>Deployment Package</div>
          <div className={styles.methodDesc}>
            Generate a self-contained ZIP or EXE installer with the enrollment token
            pre-configured for {customerName}. No Azure required.
          </div>
          <div className={styles.methodBadge}>Recommended for MSPs</div>
        </Link>

        <Link
          href={`/enrollment/windows/autopilot?customer=${customerId}`}
          className={styles.methodCard}
        >
          <div className={styles.methodIcon}>🏢</div>
          <div className={styles.methodTitle}>Windows Autopilot</div>
          <div className={styles.methodDesc}>
            Enroll via native Windows MDM (OMA-DM) using Azure Entra ID. Zero-touch
            for domain-joined devices in corporate environments.
          </div>
          <div className={styles.methodBadge}>Requires Azure AD</div>
        </Link>
      </div>

      {/* Quick steps */}
      <div className={styles.steps}>
        <div className={styles.step}>
          <div className={styles.stepNum}>1</div>
          <div>
            <div className={styles.stepTitle}>Download the Deployment Package</div>
            <div className={styles.stepDesc}>
              Go to <strong>Windows → Deployment Package</strong> and generate a package pre-configured for <strong>{customerName}</strong>.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>2</div>
          <div>
            <div className={styles.stepTitle}>Copy to target machine</div>
            <div className={styles.stepDesc}>Transfer the package to the Windows device via USB, network share, or GPO software deployment.</div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>3</div>
          <div>
            <div className={styles.stepTitle}>Run as Administrator</div>
            <div className={styles.stepDesc}>Right-click <code>setup.bat</code> → <em>Run as Administrator</em>. The agent installs silently and enrolls automatically.</div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>4</div>
          <div>
            <div className={styles.stepTitle}>Device appears in Enrollment</div>
            <div className={styles.stepDesc}>After enrollment, the device will appear under <strong>Enrollment → Devices</strong> for <strong>{customerName}</strong>.</div>
          </div>
        </div>
      </div>
    </div>
  );
}
