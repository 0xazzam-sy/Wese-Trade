import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '@/stores/authStore';
import type { User } from '@/types/auth';

import { ProtectedRoute } from './ProtectedRoute';

const baseUser: User = {
  id: 1,
  username: 'admin',
  role: 'admin',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
};

function renderAt(path: string, roles?: User['role'][]) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>login page</p>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<p>dashboard</p>} />
        </Route>
        <Route element={<ProtectedRoute {...(roles ? { roles } : {})} />}>
          <Route path="/admin" element={<p>admin area</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'unknown', user: null });
  });

  it('shows a loader while the session is being checked', () => {
    useAuthStore.setState({ status: 'checking' });
    renderAt('/');
    expect(screen.getAllByText('جاري التحقق من الجلسة').length).toBeGreaterThan(0);
    expect(screen.queryByText('dashboard')).not.toBeInTheDocument();
  });

  it('redirects anonymous users to the login page', () => {
    useAuthStore.setState({ status: 'anonymous' });
    renderAt('/');
    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('renders protected content for authenticated users', () => {
    useAuthStore.setState({ status: 'authenticated', user: baseUser });
    renderAt('/');
    expect(screen.getByText('dashboard')).toBeInTheDocument();
  });

  it('enforces roles when specified', () => {
    useAuthStore.setState({ status: 'authenticated', user: { ...baseUser, role: 'viewer' } });
    renderAt('/admin', ['admin']);
    expect(screen.queryByText('admin area')).not.toBeInTheDocument();
    expect(screen.getByText('dashboard')).toBeInTheDocument();
  });
});
