import React from 'react';
import { Link } from '@tanstack/react-router';
import styles from './NotFoundPage.module.css';
import { Button } from '@/components/common/Button/Button';
import { ROUTES } from '@/routes/paths';

export const NotFoundPage: React.FC = () => {
  return (
    <div className={styles.container}>
      <span className={styles.code}>404</span>
      <h2 className={styles.title}>페이지를 찾을 수 없습니다</h2>
      <p className={styles.desc}>
        요청하신 페이지가 존재하지 않거나 이동되었습니다. 올바른 경로인지 확인해 주세요.
      </p>
      <Link to={ROUTES.HOME}>
        <Button variant="primary">홈으로 돌아가기</Button>
      </Link>
    </div>
  );
};
