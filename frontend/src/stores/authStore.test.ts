import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/http';
import { authApi } from '@/services/api/auth';
import type { User } from '@/types/auth';

import { useAuthStore } from './authStore';

const user: User = {
  id: 1,
  username: 'admin',
  role: 'admin',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
};

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'unknown', user: null });
  });

  it('restores an existing session on initialize', async () => {
    vi.spyOn(authApi, 'session').mockResolvedValue({ authenticated: true, user });
    await useAuthStore.getState().initialize();
    expect(useAuthStore.getState()).toMatchObject({ status: 'authenticated', user });
  });

  it('becomes anonymous when there is no session', async () => {
    vi.spyOn(authApi, 'session').mockResolvedValue({ authenticated: false, user: null });
    await useAuthStore.getState().initialize();
    expect(useAuthStore.getState()).toMatchObject({ status: 'anonymous', user: null });
  });

  it('becomes anonymous when the backend is unreachable', async () => {
    vi.spyOn(authApi, 'session').mockRejectedValue(new ApiError(0, 'network_error'));
    await useAuthStore.getState().initialize();
    expect(useAuthStore.getState().status).toBe('anonymous');
  });

  it('logs in successfully', async () => {
    vi.spyOn(authApi, 'login').mockResolvedValue({ user, expires_at: '2026-01-02T00:00:00Z' });
    const error = await useAuthStore.getState().login({ username: 'admin', password: 'x' });
    expect(error).toBeNull();
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it.each([
    [new ApiError(401, 'invalid_credentials'), { code: 'invalid_credentials' }],
    [
      new ApiError(429, 'too_many_attempts', 120),
      { code: 'too_many_attempts', retryAfterSeconds: 120 },
    ],
    [new ApiError(0, 'network_error'), { code: 'network' }],
    [new ApiError(500, 'request_failed'), { code: 'unknown' }],
  ])('maps login failure %#', async (apiError, expected) => {
    useAuthStore.setState({ status: 'anonymous' });
    vi.spyOn(authApi, 'login').mockRejectedValue(apiError);
    const error = await useAuthStore.getState().login({ username: 'admin', password: 'bad' });
    expect(error).toEqual(expected);
    expect(useAuthStore.getState().status).toBe('anonymous');
  });

  it('clears the session on logout even if the request fails', async () => {
    useAuthStore.setState({ status: 'authenticated', user });
    vi.spyOn(authApi, 'logout').mockRejectedValue(new ApiError(0, 'network_error'));
    await useAuthStore.getState().logout();
    expect(useAuthStore.getState()).toMatchObject({ status: 'anonymous', user: null });
  });

  it('drops the session when the server reports it expired', () => {
    useAuthStore.setState({ status: 'authenticated', user });
    useAuthStore.getState().sessionExpired();
    expect(useAuthStore.getState().status).toBe('anonymous');
  });
});
