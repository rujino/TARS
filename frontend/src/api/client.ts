import axios from 'axios';

/**
 * 전역 Axios 인스턴스
 * - baseURL, 헤더, 인터셉터(토큰 주입, 공통 에러 핸들링 등)를 여기서 관리합니다.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 요청 인터셉터 예시 (인증 토큰 등)
apiClient.interceptors.request.use(
  (config) => {
    // const token = localStorage.getItem('access_token');
    // if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  },
  (error) => Promise.reject(error)
);

// 응답 인터셉터 예시 (공통 에러 로깅, 토큰 만료 처리)
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('[API Error]:', error.response?.data || error.message);
    return Promise.reject(error);
  }
);
