import React from 'react';
import { Link } from '@tanstack/react-router';
import styles from './Header.module.css';
import { Button } from '@/components/common/Button/Button';
import { useUIStore } from '@/stores/useUIStore';
import { ROUTES } from '@/routes/paths';

export const Header: React.FC = () => {
  const openCreateModal = useUIStore((state) => state.openCreateModal);

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <Link to={ROUTES.HOME} className={styles.logo}>
          TARS
        </Link>
        <span className={styles.badge}>Clean Architecture</span>

        <nav className={styles.nav}>
          <Link
            to={ROUTES.HOME}
            className={styles.navLink}
            activeProps={{ className: styles.navLinkActive }}
          >
            홈
          </Link>
          <Link
            to={ROUTES.TASKS}
            className={styles.navLink}
            activeProps={{ className: styles.navLinkActive }}
          >
            태스크 관리
          </Link>
        </nav>
      </div>

      <div className={styles.actions}>
        <Button variant="primary" size="sm" onClick={openCreateModal}>
          + 새 태스크
        </Button>
      </div>
    </header>
  );
};
