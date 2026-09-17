/**
 * API 공통 응답 및 에러 규격 타입
 */
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

export interface ApiError {
  statusCode: number;
  message: string;
  detail?: unknown;
}
