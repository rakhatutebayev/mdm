import AdminSidebar from '@/components/AdminSidebar/AdminSidebar';
import styles from './layout.module.css';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.container}>
      <AdminSidebar />
      <main className={styles.content}>{children}</main>
    </div>
  );
}
