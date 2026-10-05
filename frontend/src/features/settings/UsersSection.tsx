import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { UserPlus } from 'lucide-react';
import { type SubmitEvent, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { PASSWORD_HINT, userErrorMessage } from '@/features/auth/userMessages';
import { usersApi } from '@/services/api/users';
import { useAuthStore } from '@/stores/authStore';
import type { User, UserRole } from '@/types/auth';

import { ROLE_AR } from './roles';
import { Section } from './Section';

const input = 'border-line bg-sunken h-9 rounded-md border px-2 text-sm';

function UserRow({ user, me }: { user: User; me: boolean }) {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const update = useMutation({
    mutationFn: (body: { role?: UserRole; is_active?: boolean }) => usersApi.update(user.id, body),
    onSuccess: () => {
      setError(null);
      void client.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => {
      setError(userErrorMessage(e));
    },
  });
  const reset = useMutation({
    mutationFn: () => usersApi.resetPassword(user.id, password),
    onSuccess: () => {
      setPassword('');
      setError('تم تغيير كلمة المرور.');
    },
    onError: (e) => {
      setError(userErrorMessage(e));
    },
  });
  return (
    <li className="border-line/60 border-t py-2" data-testid={`user-${user.username}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="ns-ltr font-medium">{user.username}</span>
        {me && <span className="text-fg-subtle text-2xs">(أنت)</span>}
        {!user.is_active && <span className="text-bear text-2xs">معطّل</span>}
        <select
          aria-label={`دور ${user.username}`}
          className={`${input} ms-auto`}
          value={user.role}
          disabled={update.isPending}
          onChange={(e) => {
            update.mutate({ role: e.target.value as UserRole });
          }}
        >
          {(Object.keys(ROLE_AR) as UserRole[]).map((r) => (
            <option key={r} value={r}>
              {ROLE_AR[r]}
            </option>
          ))}
        </select>
        <Button
          variant="ghost"
          disabled={update.isPending}
          onClick={() => {
            update.mutate({ is_active: !user.is_active });
          }}
        >
          {user.is_active ? 'تعطيل' : 'تفعيل'}
        </Button>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <input
          dir="ltr"
          type="password"
          aria-label={`كلمة مرور جديدة لـ ${user.username}`}
          placeholder="كلمة مرور جديدة"
          autoComplete="new-password"
          className={`${input} min-w-48 flex-1`}
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
        />
        <Button
          variant="ghost"
          disabled={!password || reset.isPending}
          onClick={() => {
            reset.mutate();
          }}
        >
          تعيين كلمة المرور
        </Button>
      </div>
      {error && <p className="text-fg-muted text-2xs mt-1">{error}</p>}
    </li>
  );
}

/** Administrators manage accounts here: no terminal needed. */
export function UsersSection() {
  const me = useAuthStore((s) => s.user);
  const client = useQueryClient();
  const { data, isError } = useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) => usersApi.list(signal),
  });
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('viewer');
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => usersApi.create({ username: username.trim(), password, role }),
    onSuccess: () => {
      setUsername('');
      setPassword('');
      setError(null);
      void client.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => {
      setError(userErrorMessage(e));
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <Section id="users" title="المستخدمون">
      {isError ? (
        <p className="text-bear text-xs">تعذر تحميل المستخدمين.</p>
      ) : (
        <ul data-testid="users-list">
          {(data?.items ?? []).map((u) => (
            <UserRow key={u.id} user={u} me={u.id === me?.id} />
          ))}
        </ul>
      )}
      <form
        onSubmit={submit}
        className="border-line mt-3 flex flex-wrap items-end gap-2 border-t pt-3"
      >
        <input
          dir="ltr"
          aria-label="اسم المستخدم الجديد"
          placeholder="اسم المستخدم"
          className={input}
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
          }}
        />
        <input
          dir="ltr"
          type="password"
          aria-label="كلمة مرور المستخدم الجديد"
          placeholder="كلمة المرور"
          autoComplete="new-password"
          className={input}
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
        />
        <select
          aria-label="دور المستخدم الجديد"
          className={input}
          value={role}
          onChange={(e) => {
            setRole(e.target.value as UserRole);
          }}
        >
          {(Object.keys(ROLE_AR) as UserRole[]).map((r) => (
            <option key={r} value={r}>
              {ROLE_AR[r]}
            </option>
          ))}
        </select>
        <Button
          type="submit"
          variant="primary"
          disabled={!username || !password || create.isPending}
        >
          <UserPlus className="size-4" />
          إضافة مستخدم
        </Button>
      </form>
      <p className="text-fg-subtle text-2xs mt-1">{PASSWORD_HINT}</p>
      {error && (
        <p role="alert" className="text-bear mt-1 text-xs">
          {error}
        </p>
      )}
    </Section>
  );
}
