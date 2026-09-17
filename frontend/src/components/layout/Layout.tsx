import React from 'react';
import { Outlet } from '@tanstack/react-router';
import styles from './Layout.module.css';
import { Header } from './Header/Header';

interface LayoutProps {
  children?: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className={styles.layout}>
      <Header />
      <main className={styles.main}>{children ?? <Outlet />}</main>
    </div>
  );
};
