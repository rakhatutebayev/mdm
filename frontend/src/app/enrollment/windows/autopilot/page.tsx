'use client';
export const dynamic = 'force-dynamic';
import { useSearchParams } from 'next/navigation';
import styles from '../page.module.css';

const CUSTOMERS: Record<string, string> = {
  default: 'DEFAULT_CUSTOMER',
  nocko: 'NOCKO IT',
  strattech: 'Strategic Technology Solutions',
  almatygroup: 'Almaty Group',
  delta: 'Delta Corp',
};

export default function AutoPilotPage() {
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
          <h1 className={styles.title}>Azure Enrollment (AutoPilot)</h1>
          <p className={styles.subtitle}>
            Enroll Windows devices for <strong>{customerName}</strong> via Microsoft Entra ID (Azure AD) and Windows Autopilot.
          </p>
        </div>
      </div>

      <div className={styles.steps}>
        <div className={styles.step}>
          <div className={styles.stepNum}>1</div>
          <div>
            <div className={styles.stepTitle}>Connect Azure Tenant</div>
            <div className={styles.stepDesc}>
              Link the Azure AD tenant for <strong>{customerName}</strong> in <em>Admin → Settings → Azure Integration</em>.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>2</div>
          <div>
            <div className={styles.stepTitle}>Upload Autopilot Hardware Hash</div>
            <div className={styles.stepDesc}>
              Export the hardware hash from the device using PowerShell and upload it to the Microsoft Intune / NOCKO MDM portal for <strong>{customerName}</strong>.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>3</div>
          <div>
            <div className={styles.stepTitle}>Assign Autopilot Profile</div>
            <div className={styles.stepDesc}>
              Assign an Autopilot deployment profile to the device group in your Azure portal. Set the OOBE experience and skip screens as needed.
            </div>
          </div>
        </div>
        <div className={styles.step}>
          <div className={styles.stepNum}>4</div>
          <div>
            <div className={styles.stepTitle}>Device boots and auto-enrolls</div>
            <div className={styles.stepDesc}>
              The device connects to the internet during OOBE, authenticates against Azure AD, and automatically enrolls into NOCKO MDM under <strong>{customerName}</strong>.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
