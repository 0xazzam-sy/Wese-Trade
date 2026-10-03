import { Navigate, Outlet, useLocation } from 'react-router';

import { FullScreenLoader } from '@/components/ui/FullScreenLoader';
import { useAuthStore } from '@/stores/authStore';
import type { UserRole } from '@/types/auth';

interface ProtectedRouteProps {
  /** Restrict to specific roles (all authenticated users when omitted). */
  roles?: readonly UserRole[];
}

export function ProtectedRoute({ roles }: ProtectedRouteProps) {
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const location = useLocation();

  if (status === 'unknown' || status === 'checking') {
    return <FullScreenLoader label="جاري التحقق من الجلسة" />;
  }
  if (status === 'anonymous' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
