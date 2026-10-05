import { create } from 'zustand';

import { ApiError } from '@/lib/http';
import { authApi } from '@/services/api/auth';
import type { LoginCredentials, User } from '@/types/auth';

export type AuthStatus = 'unknown' | 'checking' | 'authenticated' | 'anonymous';

export type LoginErrorCode = 'invalid_credentials' | 'too_many_attempts' | 'network' | 'unknown';

export interface LoginError {
  code: LoginErrorCode;
  retryAfterSeconds?: number;
}

interface AuthState {
  status: AuthStatus;
  user: User | null;
  /** Restore the session from the httpOnly cookie (called once at startup). */
  initialize: () => Promise<void>;
  login: (credentials: LoginCredentials) => Promise<LoginError | null>;
  /** First run: create the first administrator and sign in (returns the error, if any). */
  setup: (credentials: LoginCredentials) => Promise<unknown>;
  logout: () => Promise<void>;
  /** Server reported the session is no longer valid. */
  sessionExpired: () => void;
}

function toLoginError(error: unknown): LoginError {
  if (!(error instanceof ApiError)) return { code: 'unknown' };
  if (error.isNetworkError) return { code: 'network' };
  if (error.status === 401) return { code: 'invalid_credentials' };
  if (error.status === 429) {
    return error.retryAfterSeconds
      ? { code: 'too_many_attempts', retryAfterSeconds: error.retryAfterSeconds }
      : { code: 'too_many_attempts' };
  }
  if (error.status === 422) return { code: 'invalid_credentials' };
  return { code: 'unknown' };
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  status: 'unknown',
  user: null,

  async initialize() {
    if (get().status === 'checking') return;
    set({ status: 'checking' });
    try {
      const { user } = await authApi.session();
      set(user ? { status: 'authenticated', user } : { status: 'anonymous', user: null });
    } catch {
      set({ status: 'anonymous', user: null });
    }
  },

  async login(credentials) {
    try {
      const { user } = await authApi.login(credentials);
      set({ status: 'authenticated', user });
      return null;
    } catch (error) {
      return toLoginError(error);
    }
  },

  async setup(credentials) {
    try {
      const { user } = await authApi.setup(credentials);
      set({ status: 'authenticated', user });
      return null;
    } catch (error) {
      return error;
    }
  },

  async logout() {
    try {
      await authApi.logout();
    } catch {
      // The cookie may already be gone; local state is cleared regardless.
    }
    set({ status: 'anonymous', user: null });
  },

  sessionExpired() {
    if (get().status === 'authenticated') set({ status: 'anonymous', user: null });
  },
}));
