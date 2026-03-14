'use client';
import { useState } from 'react';
import styles from './EnrollWindowsModal.module.css';

const ENROLL_URL = 'https://mdm.it-uae.com/enroll/windows/win';

interface Props {
  onClose: () => void;
}

export default function EnrollWindowsModal({ onClose }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(ENROLL_URL).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    // Trigger package download - in real impl this would call API to generate package
    const link = document.createElement('a');
    link.href = '/api/enrollment/windows/package';
    link.download = 'nocko-mdm-enrollment.zip';
    link.click();
  };

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        {/* Header */}
        <div className={styles.step2Header}>
          <div className={styles.step2Title}>
            <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" style={{ color: '#555' }}>
              <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/>
            </svg>
            Enroll Windows Device
          </div>
          <div className={styles.step2Links}>
            <button className={styles.closeBtn} onClick={onClose} title="Close">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className={styles.step2Body}>
          <div className={styles.step2Left}>
            <h3 className={styles.stepsTitle}>Enrollment Steps:</h3>

            {/* Step 1 — Enrollment Link */}
            <div className={styles.enrollStep}>
              <div className={styles.enrollStepIcon} style={{ color: '#4a7cff' }}>
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                  <path d="M20 3H4v10c0 2.21 1.79 4 4 4h6c2.21 0 4-1.79 4-4v-3h2c1.11 0 2-.89 2-2V5c0-1.11-.89-2-2-2zm0 5h-2V5h2v3z"/>
                </svg>
              </div>
              <div style={{ flex: 1 }}>
                <p className={styles.enrollStepText}>
                  1. Paste the <strong>Enrollment Link</strong> in IE/Edge browser on the device to be enrolled.
                </p>
                <div className={styles.urlBox}>
                  <a href={ENROLL_URL} className={styles.urlText} target="_blank" rel="noreferrer">
                    {ENROLL_URL}
                  </a>
                  <button className={styles.copyBtn} onClick={handleCopy} title={copied ? 'Copied!' : 'Copy'}>
                    {copied ? (
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="#16a34a">
                        <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                        <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                      </svg>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Step 2 — Auth */}
            <div className={styles.enrollStep}>
              <div className={styles.enrollStepIcon} style={{ color: '#6b7080' }}>
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                  <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>
                </svg>
              </div>
              <p className={styles.enrollStepText}>
                2. Complete the authentication, if required to complete the enrollment.
              </p>
            </div>

            {/* Step 3 — Download Package */}
            <div className={styles.enrollStep}>
              <div className={styles.enrollStepIcon} style={{ color: '#6b7080' }}>
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                  <path d="M19 9h-4V3H9v6H5l7 7 7-7zm-8 2V5h2v6h1.17L12 13.17 9.83 11H11zm-6 7h14v2H5z"/>
                </svg>
              </div>
              <div>
                <p className={styles.enrollStepText}>
                  3. Or download and run the enrollment package directly on the device.
                </p>
                <button className={styles.downloadBtn} onClick={handleDownload}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                    <path d="M19 9h-4V3H9v6H5l7 7 7-7zm-8 2V5h2v6h1.17L12 13.17 9.83 11H11zm-6 7h14v2H5z"/>
                  </svg>
                  Download Enrollment Package (.zip)
                </button>
              </div>
            </div>

            <button className={styles.finishBtn} onClick={onClose}>Finish</button>
          </div>
        </div>
      </div>
    </div>
  );
}
