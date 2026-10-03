export type UserRole = 'admin' | 'analyst' | 'viewer';

export interface User {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  user: User;
  expires_at: string;
}

export interface SessionResponse {
  authenticated: boolean;
  user: User | null;
}
