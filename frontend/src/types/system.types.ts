export interface HealthCheckResponse {
  status: string;
  app: string;
}

export interface ReadinessResponse {
  status: 'ready' | 'degraded' | string;
  overall: 'ok' | 'degraded' | string;
  database: string;
  storage: string;
  checks?: {
    database: string;
    storage: string;
  };
  app: string;
  error?: string;
}
