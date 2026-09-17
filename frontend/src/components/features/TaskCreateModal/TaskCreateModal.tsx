import React, { useState } from 'react';
import styles from './TaskCreateModal.module.css';
import { Button } from '@/components/common/Button/Button';
import { useUIStore } from '@/stores/useUIStore';
import { useCreateTaskMutation } from '@/queries/useTaskQuery';

export const TaskCreateModal: React.FC = () => {
  const isOpen = useUIStore((s) => s.isCreateModalOpen);
  const closeModal = useUIStore((s) => s.closeCreateModal);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  const createTaskMutation = useCreateTaskMutation();

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

    createTaskMutation.mutate(
      { title: title.trim(), description: description.trim() },
      {
        onSuccess: () => {
          setTitle('');
          setDescription('');
          closeModal();
        },
      }
    );
  };

  return (
    <div className={styles.backdrop} onClick={closeModal}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h2 className={styles.title}>새 태스크 추가</h2>
        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label className={styles.label}>제목 *</label>
            <input
              type="text"
              className={styles.input}
              placeholder="할 일을 입력하세요..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>상세 설명</label>
            <textarea
              className={styles.textarea}
              placeholder="상세 내용을 적어주세요 (선택)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className={styles.footer}>
            <Button variant="outline" type="button" onClick={closeModal}>
              취소
            </Button>
            <Button
              variant="primary"
              type="submit"
              isLoading={createTaskMutation.isPending}
            >
              등록
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
