import axios from 'axios';

/**
 * 전역 Axios 인스턴스
 * - baseURL: 상대 경로 ('')를 기본으로 사용하여 k8s Ingress, Vite proxy, 프로덕션 환경에 투명하게 대응
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 요청 인터셉터: 로컬 스토리지의 tars_token을 Bearer 인증 헤더로 주입
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('tars_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 응답 인터셉터: 공통 에러 핸들링
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 인증 만료 시 저장된 토큰 정리 (화면단에서 상태 반영)
      const hadToken = !!localStorage.getItem('tars_token');
      if (hadToken) {
        localStorage.removeItem('tars_token');
        window.dispatchEvent(new CustomEvent('tars_auth_expired'));
      }
    }
    return Promise.reject(error);
  }
);
