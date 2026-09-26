import React from 'react';
import { Outlet } from '@tanstack/react-router';
import styles from './Layout.module.css';
import { Header } from './Header/Header';
import { Sidebar } from './Sidebar/Sidebar';

interface LayoutProps {
  children?: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className={styles.layoutWrapper}>
      <div className={styles.layout}>
        <Header />
        <div className={styles.bodyContainer}>
          <Sidebar />
          <main className={styles.main}>{children ?? <Outlet />}</main>
        </div>
      </div>
    </div>
  );
};
