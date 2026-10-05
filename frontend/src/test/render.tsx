import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';

import { useAuthStore } from '@/stores/authStore';
import type { UserRole } from '@/types/auth';

/** Render with a fresh query client (no retries) and a router. */
export function renderApp(ui: ReactElement, path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function loginAs(role: UserRole, id = 1) {
  useAuthStore.setState({
    status: 'authenticated',
    user: {
      id,
      username: `${role}-user`,
      role,
      is_active: true,
      created_at: '',
      last_login_at: null,
    },
  });
}
