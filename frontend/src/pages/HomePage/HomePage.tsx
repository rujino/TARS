import React from 'react';
import { Link } from '@tanstack/react-router';
import styles from './HomePage.module.css';
import { Button } from '@/components/common/Button/Button';
import { Card } from '@/components/common/Card/Card';
import { ROUTES } from '@/routes/paths';

export const HomePage: React.FC = () => {
  return (
    <div className={styles.container}>
      {/* 히어로 배너 */}
      <section className={styles.hero}>
        <h1 className={styles.heroTitle}>TARS Intelligent Platform</h1>
        <p className={styles.heroSubtitle}>
          TanStack Router + TanStack Query + Zustand + CSS Modules 기반의 
          타입 안전하고 명확한 7대 계층 아키텍처 프론트엔드입니다.
        </p>
        <div className={styles.heroActions}>
          <Link to={ROUTES.TASKS}>
            <Button variant="primary" size="lg">
              태스크 관리 시작하기 →
            </Button>
          </Link>
        </div>
      </section>

      {/* 기술 특장점 그리드 */}
      <section className={styles.featuresGrid}>
        <Card>
          <span className={styles.techTag}>Routing</span>
          <h3 className={styles.featureTitle}>TanStack Router</h3>
          <p className={styles.featureDesc}>
            100% Type-safe 라우팅을 제공하며, 컴파일 타임에 모든 경로 오타를 감지하고 
            라우트 프리로딩(Preloading)을 지원합니다.
          </p>
        </Card>

        <Card>
          <span className={styles.techTag}>Server State</span>
          <h3 className={styles.featureTitle}>TanStack Query</h3>
          <p className={styles.featureDesc}>
            서버 비동기 데이터의 자동 캐싱, 백그라운드 리페칭, 로딩/에러 상태를 중앙 관리하여 
            데이터 일관성을 보장합니다.
          </p>
        </Card>

        <Card>
          <span className={styles.techTag}>Client State</span>
          <h3 className={styles.featureTitle}>Zustand</h3>
          <p className={styles.featureDesc}>
            불필요한 보일러플레이트 없이 모달, 사이드바 토글, 클라이언트 필터 상태를 
            초경량(~1KB) 훅으로 격리 관리합니다.
          </p>
        </Card>

        <Card>
          <span className={styles.techTag}>Styling</span>
          <h3 className={styles.featureTitle}>CSS Modules</h3>
          <p className={styles.featureDesc}>
            바닐라 CSS 표준을 유지하면서 컴포넌트 단위 고유 해시 클래스를 생성하여 
            스타일 충돌(오염)을 원천 차단합니다.
          </p>
        </Card>
      </section>
    </div>
  );
};
