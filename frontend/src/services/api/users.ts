import { apiRequest } from '@/lib/http';
import type { User, UserRole } from '@/types/auth';

/** Administrator-only user management. */
export const usersApi = {
  list(signal?: AbortSignal): Promise<{ items: User[] }> {
    return apiRequest('/users', signal ? { signal } : {});
  },

  create(body: { username: string; password: string; role: UserRole }): Promise<User> {
    return apiRequest<User>('/users', { method: 'POST', body });
  },

  update(id: number, body: { role?: UserRole; is_active?: boolean }): Promise<User> {
    return apiRequest<User>(`/users/${String(id)}`, { method: 'PATCH', body });
  },

  resetPassword(id: number, password: string): Promise<void> {
    return apiRequest<undefined>(`/users/${String(id)}/password`, {
      method: 'POST',
      body: { password },
    });
  },
};
