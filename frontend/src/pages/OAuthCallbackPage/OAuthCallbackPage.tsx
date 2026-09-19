import React, { useEffect, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { toolsApi } from '@/api/endpoints/tools.api';

export const OAuthCallbackPage: React.FC = () => {
  const navigate = useNavigate();

  const searchParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
  const initialError = searchParams?.get('error');
  const code = searchParams?.get('code');
  const state = searchParams?.get('state') || undefined;

  const [statusText, setStatusText] = useState(
    initialError
      ? `Google 인증 실패: ${initialError}`
      : !code
      ? '유효한 인증 코드(code)가 전달되지 않았습니다.'
      : 'Google 연동 인증을 처리하는 중입니다...'
  );
  const [isSuccess, setIsSuccess] = useState<boolean | null>(
    initialError || !code ? false : null
  );

  useEffect(() => {
    if (initialError || !code) return;

    toolsApi
      .handleGoogleCallback({ code, state })
      .then((res) => {
        setIsSuccess(true);
        setStatusText(
          res.linked
            ? `Google Workspace 연동 완료 (${res.account_email || '계정 연결됨'})`
            : res.message || '인증 처리가 완료되었습니다.'
        );
        setTimeout(() => {
          navigate({ to: '/' });
        }, 2000);
      })
      .catch((err) => {
        setIsSuccess(false);
        const detail = err.response?.data?.detail || err.message;
        setStatusText(`연동 처리 실패: ${detail}`);
      });
  }, [code, state, initialError, navigate]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '2rem',
        textAlign: 'center',
        color: 'var(--color-text-main)',
      }}
    >
      <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>
        {isSuccess === true ? '✅' : isSuccess === false ? '❌' : '🔄'}
      </div>
      <h2 style={{ marginBottom: '0.5rem' }}>Google 계정 연동</h2>
      <p style={{ color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>{statusText}</p>
      <button
        style={{
          padding: '8px 16px',
          borderRadius: 'var(--radius-md)',
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-main)',
          cursor: 'pointer',
        }}
        onClick={() => navigate({ to: '/' })}
      >
        메인 대화 화면으로 이동
      </button>
    </div>
  );
};
