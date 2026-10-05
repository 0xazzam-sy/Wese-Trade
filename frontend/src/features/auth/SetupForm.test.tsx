import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/http';
import { LoginPage } from '@/pages/LoginPage';
import { authApi } from '@/services/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { renderApp } from '@/test/render';

afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ status: 'unknown', user: null });
});

const USER = {
  id: 1,
  username: 'owner',
  role: 'admin' as const,
  is_active: true,
  created_at: '',
  last_login_at: null,
};

describe('first-run setup', () => {
  it('shows the setup form when no account exists and creates the first admin', async () => {
    useAuthStore.setState({ status: 'anonymous', user: null });
    vi.spyOn(authApi, 'setupStatus').mockResolvedValue({ needs_setup: true });
    const setup = vi.spyOn(authApi, 'setup').mockResolvedValue({ user: USER, expires_at: '' });
    renderApp(<LoginPage />, '/login');
    expect(await screen.findByText('الإعداد الأول')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('اسم المستخدم'), 'owner');
    await user.type(screen.getByLabelText('كلمة المرور'), 'Owner-Strong-Pass-1');
    await user.type(screen.getByLabelText('تأكيد كلمة المرور'), 'Owner-Strong-Pass-1');
    await user.click(screen.getByRole('button', { name: 'إنشاء حساب المدير' }));
    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated');
    });
    expect(setup).toHaveBeenCalledWith({ username: 'owner', password: 'Owner-Strong-Pass-1' });
  });

  it('rejects mismatched passwords and explains weak ones in Arabic', async () => {
    useAuthStore.setState({ status: 'anonymous', user: null });
    vi.spyOn(authApi, 'setupStatus').mockResolvedValue({ needs_setup: true });
    vi.spyOn(authApi, 'setup').mockRejectedValue(new ApiError(422, 'weak_password'));
    renderApp(<LoginPage />, '/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('اسم المستخدم'), 'owner');
    await user.type(screen.getByLabelText('كلمة المرور'), 'short');
    await user.type(screen.getByLabelText('تأكيد كلمة المرور'), 'other');
    await user.click(screen.getByRole('button', { name: 'إنشاء حساب المدير' }));
    expect(screen.getByRole('alert')).toHaveTextContent('كلمتا المرور غير متطابقتين');
    await user.clear(screen.getByLabelText('تأكيد كلمة المرور'));
    await user.type(screen.getByLabelText('تأكيد كلمة المرور'), 'short');
    await user.click(screen.getByRole('button', { name: 'إنشاء حساب المدير' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('كلمة المرور ضعيفة');
  });

  it('shows the normal login once an account exists, and a backend-down notice', async () => {
    useAuthStore.setState({ status: 'anonymous', user: null });
    vi.spyOn(authApi, 'setupStatus').mockResolvedValue({ needs_setup: false });
    const { unmount } = renderApp(<LoginPage />, '/login');
    expect(await screen.findByRole('heading', { name: 'تسجيل الدخول' })).toBeInTheDocument();
    expect(screen.queryByTestId('setup-form')).toBeNull();
    unmount();
    vi.spyOn(authApi, 'setupStatus').mockRejectedValue(new ApiError(0, 'network_error'));
    renderApp(<LoginPage />, '/login');
    expect(await screen.findByRole('alert')).toHaveTextContent('الخادم المحلي غير متاح');
  });
});
