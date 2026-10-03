import { apiRequest } from '@/lib/http';
import type { LoginCredentials, LoginResponse, SessionResponse, User } from '@/types/auth';

export const authApi = {
  login(credentials: LoginCredentials): Promise<LoginResponse> {
    return apiRequest<LoginResponse>('/auth/login', {
      method: 'POST',
      body: credentials,
      notifyUnauthorized: false,
    });
  },

  logout(): Promise<void> {
    return apiRequest<undefined>('/auth/logout', { method: 'POST', notifyUnauthorized: false });
  },

  /** Session bootstrap: always 200 (no console error for anonymous visitors). */
  session(signal?: AbortSignal): Promise<SessionResponse> {
    return apiRequest<SessionResponse>('/auth/session', {
      notifyUnauthorized: false,
      ...(signal ? { signal } : {}),
    });
  },

  me(signal?: AbortSignal): Promise<User> {
    return apiRequest<User>('/auth/me', {
      notifyUnauthorized: false,
      ...(signal ? { signal } : {}),
    });
  },
};
