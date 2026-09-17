import React from 'react';
import styles from './TaskPage.module.css';
import { Button } from '@/components/common/Button/Button';
import { Card } from '@/components/common/Card/Card';
import {
  useTasksQuery,
  useToggleTaskMutation,
  useDeleteTaskMutation,
} from '@/queries/useTaskQuery';
import { useFilterStore, type TaskFilterType } from '@/stores/useFilterStore';
import { useUIStore } from '@/stores/useUIStore';

export const TaskPage: React.FC = () => {
  // 1. TanStack Query 서버 상태
  const { data: tasks = [], isLoading, isError, error } = useTasksQuery();
  const toggleMutation = useToggleTaskMutation();
  const deleteMutation = useDeleteTaskMutation();

  // 2. Zustand 클라이언트 상태
  const filter = useFilterStore((s) => s.filter);
  const setFilter = useFilterStore((s) => s.setFilter);
  const openCreateModal = useUIStore((s) => s.openCreateModal);

  // 필터링 적용
  const filteredTasks = tasks.filter((task) => {
    if (filter === 'active') return !task.isCompleted;
    if (filter === 'completed') return task.isCompleted;
    return true;
  });

  return (
    <div className={styles.pageContainer}>
      {/* 아키텍처 계층 안내 배너 */}
      <section className={styles.introSection}>
        <h1 className={styles.introTitle}>프론트엔드 계층 분리 아키텍처</h1>
        <p className={styles.introDesc}>
          각 계층이 단 하나의 책임(SRP)만을 수행하여 사람이 봐도 직관적이고 확장하기 쉬운 구조입니다.
        </p>

        <div className={styles.architectureDiagram}>
          <div className={styles.archCard}>
            <div className={styles.archLayer}>Layer 1 : API</div>
            <div className={styles.archRole}>Axios Client</div>
            <div className={styles.archDetail}>순수 HTTP 통신, baseURL, 인터셉터</div>
          </div>
          <div className={styles.archCard}>
            <div className={styles.archLayer}>Layer 2 : Server State</div>
            <div className={styles.archRole}>TanStack Query</div>
            <div className={styles.archDetail}>캐싱, 리페칭, 로딩/에러 상태 관리</div>
          </div>
          <div className={styles.archCard}>
            <div className={styles.archLayer}>Layer 3 : Client State</div>
            <div className={styles.archRole}>Zustand</div>
            <div className={styles.archDetail}>모달, 사이드바, 필터 등 순수 UI 전역 상태</div>
          </div>
          <div className={styles.archCard}>
            <div className={styles.archLayer}>Layer 4 : UI Component</div>
            <div className={styles.archRole}>CSS Modules</div>
            <div className={styles.archDetail}>바닐라 CSS 기반 클래스 스코핑 격리</div>
          </div>
        </div>
      </section>

      {/* 컨트롤 영역 (필터 탭 및 생성 버튼) */}
      <div className={styles.controls}>
        <div className={styles.filterTabs}>
          {(['all', 'active', 'completed'] as TaskFilterType[]).map((type) => (
            <button
              key={type}
              className={`${styles.filterTab} ${filter === type ? styles.filterTabActive : ''}`}
              onClick={() => setFilter(type)}
            >
              {type === 'all' && '전체'}
              {type === 'active' && '진행 중'}
              {type === 'completed' && '완료됨'}
            </button>
          ))}
        </div>

        <Button variant="primary" onClick={openCreateModal}>
          + 할 일 등록
        </Button>
      </div>

      {/* 태스크 목록 영역 */}
      {isLoading ? (
        <Card>
          <p style={{ textAlign: 'center', padding: '2rem' }}>데이터를 불러오는 중입니다...</p>
        </Card>
      ) : isError ? (
        <Card>
          <p style={{ color: 'var(--color-danger)', textAlign: 'center' }}>
            데이터를 불러오는 데 실패했습니다: {(error as Error).message}
          </p>
        </Card>
      ) : filteredTasks.length === 0 ? (
        <div className={styles.emptyState}>
          <p>등록된 태스크가 없습니다.</p>
        </div>
      ) : (
        <div className={styles.taskList}>
          {filteredTasks.map((task) => (
            <div
              key={task.id}
              className={`${styles.taskItem} ${task.isCompleted ? styles.taskCompleted : ''}`}
            >
              <div className={styles.taskLeft}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={task.isCompleted}
                  onChange={() => toggleMutation.mutate(task.id)}
                />
                <div className={styles.taskContent}>
                  <span
                    className={`${styles.taskTitle} ${
                      task.isCompleted ? styles.taskTitleCompleted : ''
                    }`}
                  >
                    {task.title}
                  </span>
                  {task.description && (
                    <span className={styles.taskDescription}>{task.description}</span>
                  )}
                </div>
              </div>

              <div className={styles.taskRight}>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => deleteMutation.mutate(task.id)}
                  isLoading={deleteMutation.isPending}
                >
                  삭제
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
