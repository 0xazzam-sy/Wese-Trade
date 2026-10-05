import { useQuery } from '@tanstack/react-query';
import { Navigate, useLocation, useNavigate } from 'react-router';

import { FullScreenLoader } from '@/components/ui/FullScreenLoader';
import { LogoMark, Wordmark } from '@/components/ui/Logo';
import { NeuralBackdrop } from '@/components/ui/NeuralBackdrop';
import { LoginForm } from '@/features/auth/LoginForm';
import { SetupForm } from '@/features/auth/SetupForm';
import { ThemeToggle } from '@/features/header/ThemeToggle';
import { authApi } from '@/services/api/auth';
import { useAuthStore } from '@/stores/authStore';

function redirectTarget(state: unknown): string {
  if (state && typeof state === 'object' && 'from' in state && typeof state.from === 'string') {
    return state.from.startsWith('/') && !state.from.startsWith('//') ? state.from : '/';
  }
  return '/';
}

export function LoginPage() {
  const status = useAuthStore((s) => s.status);
  const location = useLocation();
  const navigate = useNavigate();
  const target = redirectTarget(location.state);
  const setup = useQuery({
    queryKey: ['auth', 'setup'],
    queryFn: ({ signal }) => authApi.setupStatus(signal),
    enabled: status === 'anonymous',
    retry: false,
  });

  if (status === 'unknown' || status === 'checking') {
    return <FullScreenLoader label="جاري التحقق من الجلسة" />;
  }
  if (status === 'authenticated') return <Navigate to={target} replace />;

  return (
    <div className="relative flex h-full items-center justify-center overflow-hidden p-6">
      <NeuralBackdrop className="opacity-60" />
      <div className="absolute end-5 top-5">
        <ThemeToggle />
      </div>

      <main className="ns-panel relative w-full max-w-sm p-8">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <LogoMark className="size-14" />
          <Wordmark className="text-2xl" />
          <p className="text-fg-muted text-sm">منصة تحليل أسواق الكريبتو</p>
        </div>
        {setup.data?.needs_setup ? (
          <>
            <h1 className="mb-5 text-lg font-semibold">الإعداد الأول</h1>
            <SetupForm
              onDone={() => {
                void navigate('/', { replace: true });
              }}
            />
          </>
        ) : (
          <>
            <h1 className="mb-5 text-lg font-semibold">تسجيل الدخول</h1>
            {setup.isError && (
              <p role="alert" className="bg-bear-soft text-bear mb-4 rounded-lg px-3 py-2 text-xs">
                الخادم المحلي غير متاح. تأكد من تشغيل Wese Trade ثم أعد المحاولة.
              </p>
            )}
            <LoginForm
              onSuccess={() => {
                void navigate(target, { replace: true });
              }}
            />
          </>
        )}
        <p className="text-fg-subtle text-2xs mt-6 text-center leading-5">
          منصة للتحليل فقط — لا تنفّذ أي عمليات تداول.
        </p>
      </main>
    </div>
  );
}
