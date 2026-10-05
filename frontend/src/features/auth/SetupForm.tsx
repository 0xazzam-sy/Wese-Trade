import { AlertCircle, ShieldCheck } from 'lucide-react';
import { type SubmitEvent, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useAuthStore } from '@/stores/authStore';

import { PASSWORD_HINT, userErrorMessage } from './userMessages';

const fieldClass =
  'bg-sunken border-line focus-within:border-accent text-fg h-11 w-full rounded-lg border px-3 text-sm outline-none';

/** First run only: create the first administrator from the UI (no terminal needed). */
export function SetupForm({ onDone }: { onDone: () => void }) {
  const setup = useAuthStore((s) => s.setup);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirm) {
      setError('كلمتا المرور غير متطابقتين.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const failure = await setup({ username: username.trim(), password });
    setSubmitting(false);
    if (failure) {
      setError(userErrorMessage(failure));
      return;
    }
    onDone();
  };

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-4"
      noValidate
      data-testid="setup-form"
    >
      <p className="text-fg-muted flex items-start gap-2 text-xs leading-5">
        <ShieldCheck className="text-accent mt-0.5 size-4 shrink-0" />
        لا يوجد أي حساب بعد. أنشئ حساب مدير النظام الأول لهذا الجهاز.
      </p>
      <label className="block space-y-1.5">
        <span className="text-fg-muted text-xs font-medium">اسم المستخدم</span>
        <input
          dir="ltr"
          autoComplete="username"
          autoFocus
          value={username}
          maxLength={64}
          onChange={(e) => {
            setUsername(e.target.value);
          }}
          className={fieldClass}
          disabled={submitting}
        />
      </label>
      <label className="block space-y-1.5">
        <span className="text-fg-muted text-xs font-medium">كلمة المرور</span>
        <input
          dir="ltr"
          type="password"
          autoComplete="new-password"
          value={password}
          maxLength={256}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
          className={fieldClass}
          disabled={submitting}
        />
      </label>
      <p className="text-fg-subtle text-2xs -mt-2">{PASSWORD_HINT}</p>
      <label className="block space-y-1.5">
        <span className="text-fg-muted text-xs font-medium">تأكيد كلمة المرور</span>
        <input
          dir="ltr"
          type="password"
          autoComplete="new-password"
          value={confirm}
          maxLength={256}
          onChange={(e) => {
            setConfirm(e.target.value);
          }}
          className={fieldClass}
          disabled={submitting}
        />
      </label>
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
          <Spinner className="border-accent-fg/30 border-t-accent-fg" />
        ) : (
          'إنشاء حساب المدير'
        )}
      </Button>
    </form>
  );
}
