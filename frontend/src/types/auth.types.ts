export interface UserResponse {
  id: string;
  username: string;
  email?: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UserSignupRequest {
  username: string;
  email: string;
  password: string;
}

export interface UserLoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user?: UserResponse | null;
}

export interface WebSocketTicketResponse {
  ticket: string;
  expires_in: number;
}
