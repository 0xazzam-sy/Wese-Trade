import type { UserRole } from '@/types/auth';

export const ROLE_AR: Record<UserRole, string> = {
  admin: 'مدير النظام',
  analyst: 'محلل',
  viewer: 'مشاهد',
};
