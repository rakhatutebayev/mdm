import { Suspense } from 'react';
import EnrollSidebar from '@/components/EnrollSidebar/EnrollSidebar';
import styles from './layout.module.css';

export default function EnrollmentLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.layout}>
      <Suspense fallback={<div className={styles.sidebarSkeleton} />}>
        <EnrollSidebar />
      </Suspense>
      <div className={styles.content}>
        {children}
      </div>
    </div>
  );
}
