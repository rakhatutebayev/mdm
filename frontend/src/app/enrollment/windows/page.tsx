'use client';
import { useSearchParams } from 'next/navigation';
import styles from './page.module.css';

const CUSTOMERS: Record<string, string> = {
  default: 'DEFAULT_CUSTOMER',
  nocko: 'NOCKO IT',
  strattech: 'Strategic Technology Solutions',
  almatygroup: 'Almaty Group',
  delta: 'Delta Corp',
};

export default function WindowsEnrollPage() {
  const searchParams = useSearchParams();
  const customerId = searchParams.get('customer') || 'default';
  const customerName = CUSTOMERS[customerId] || customerId;

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
          <p className={styles.subtitle}>Enroll Windows devices for <strong>{customerName}</strong> using the NOCKO MDM Agent.</p>
        </div>
      </div>

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
