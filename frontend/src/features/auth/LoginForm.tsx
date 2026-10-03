import { AlertCircle, Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react';
import { type SubmitEvent, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useAuthStore } from '@/stores/authStore';

import { loginErrorMessage } from './loginMessages';

const inputClass =
  'text-fg placeholder:text-fg-subtle h-11 w-full bg-transparent text-sm outline-none';
const fieldClass =
  'bg-sunken border-line focus-within:border-accent focus-within:shadow-glow flex items-center gap-2.5 rounded-lg border px-3 transition-shadow';

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError('يرجى إدخال اسم المستخدم وكلمة المرور.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await login({ username: username.trim(), password });
    setSubmitting(false);
    if (result) {
      setError(loginErrorMessage(result));
      setPassword('');
      return;
    }
    onSuccess();
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <label htmlFor="username" className="text-fg-muted text-xs font-medium">
          اسم المستخدم
        </label>
        <div className={fieldClass}>
          <UserRound className="text-fg-subtle size-4 shrink-0" />
          <input
            id="username"
            name="username"
            dir="ltr"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
            }}
            className={inputClass}
            disabled={submitting}
            maxLength={64}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="password" className="text-fg-muted text-xs font-medium">
          كلمة المرور
        </label>
        <div className={fieldClass}>
          <LockKeyhole className="text-fg-subtle size-4 shrink-0" />
          <input
            id="password"
            name="password"
            dir="ltr"
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
            className={inputClass}
            disabled={submitting}
            maxLength={256}
          />
          <button
            type="button"
            onClick={() => {
              setShowPassword((v) => !v);
            }}
            aria-label={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
            className="text-fg-subtle hover:text-fg shrink-0"
          >
            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="bg-bear-soft text-bear flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Button type="submit" variant="primary" className="h-11 w-full" disabled={submitting}>
        {submitting ? (
          <>
            <Spinner className="border-accent-fg/30 border-t-accent-fg" label="جاري تسجيل الدخول" />
            جاري تسجيل الدخول…
          </>
        ) : (
          'تسجيل الدخول'
        )}
      </Button>
    </form>
  );
}
