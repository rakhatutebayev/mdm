'use client';
export const dynamic = 'force-dynamic';
import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { getCustomers } from '@/lib/api';
import styles from '../../windows/page.module.css';

export default function LinuxEnrollPage() {
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
          router.replace(`/enrollment/linux?customer=${nextCustomerId}`);
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
          <h1 className={styles.title}>Enroll Linux Device</h1>
          <p className={styles.subtitle}>
            Choose an enrollment method for <strong>{customerName}</strong>.
          </p>
        </div>
      </div>

      <div className={styles.methodGrid}>
        <Link
          href={`/enrollment/linux/package?customer=${customerId}`}
          className={styles.methodCard}
        >
          <div className={styles.methodIcon}>📦</div>
          <div className={styles.methodTitle}>Deployment Package</div>
          <div className={styles.methodDesc}>
            One-line bash installer with the enrollment token pre-configured for {customerName}.
            Supports Ubuntu, Debian, CentOS, RHEL, and compatible distros.
          </div>
          <div className={styles.methodBadge}>Recommended</div>
        </Link>
      </div>

      <div className={styles.steps}>
        <div className={styles.step}>
          <div className={styles.stepNum}>1</div>
          <div>
            <div className={styles.stepTitle}>Copy the install command</div>
            <div className={styles.stepDesc}>
              Go to <strong>Linux → Deployment Package</strong> and copy the one-line curl command pre-configured for <strong>{customerName}</strong>.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>2</div>
          <div>
            <div className={styles.stepTitle}>Run on the target machine</div>
            <div className={styles.stepDesc}>
              Paste and run the command in a terminal with <code>sudo</code> privileges on the Linux device.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>3</div>
          <div>
            <div className={styles.stepTitle}>Agent installs automatically</div>
            <div className={styles.stepDesc}>
              The script downloads the agent binary, writes the embedded config, and registers it as a systemd service.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>4</div>
          <div>
            <div className={styles.stepTitle}>Device appears in Enrollment</div>
            <div className={styles.stepDesc}>
              After enrollment, the device will appear under <strong>Enrollment → Devices</strong> for <strong>{customerName}</strong>.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
