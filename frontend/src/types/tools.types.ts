export interface ToolItem {
  name: string;
  description: string;
  active: boolean;
  enabled: boolean;
  parameters?: Record<string, unknown>;
}

export interface ServerInfo {
  id: string;
  name: string;
  type: 'builtin' | 'mcp';
  status: 'connected' | 'offline';
  transport?: string | null;
  url?: string | null;
  description: string;
  total_tools: number;
  total_tools_count?: number;
  active_tools: number;
  active_tools_count?: number;
  auth_required: boolean;
  is_linked: boolean;
  account_email?: string | null;
  tools: ToolItem[];
}

export interface ToolsServersResponse {
  servers: ServerInfo[];
}

export interface ToolToggleRequest {
  active?: boolean;
  enabled?: boolean;
}

export interface ToolToggleResponse {
  tool_name: string;
  active: boolean;
  enabled: boolean;
  disabled_tools: string[];
  user_id: string;
  message: string;
}

export interface GoogleAuthUrlResponse {
  url: string;
  state: string;
  scopes: string[];
}

export interface GoogleAuthCallbackResponse {
  status: string;
  provider: string;
  linked: boolean;
  account_email?: string | null;
  message: string;
}

export interface GoogleCredentialsRequest {
  client_id?: string | null;
  client_secret?: string | null;
}

export interface GoogleCredentialsResponse {
  client_id: string;
  has_client_secret: boolean;
  is_configured: boolean;
  is_linked: boolean;
  account_email?: string | null;
}

export interface ServerTestResponse {
  server_id: string;
  status: 'connected' | 'offline';
  latency_ms: number;
  message: string;
}
