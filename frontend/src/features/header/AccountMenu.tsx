import {
  ChartNoAxesColumn,
  ChevronDown,
  FlaskConical,
  LogOut,
  Settings,
  UserRound,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import { useAuthStore } from '@/stores/authStore';
import type { UserRole } from '@/types/auth';

const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'مدير النظام',
  analyst: 'محلل',
  viewer: 'مشاهد',
};

export function AccountMenu() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!user) return null;

  const handleLogout = async () => {
    setOpen(false);
    await logout();
    await navigate('/login', { replace: true });
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
        }}
        className="hover:bg-surface-hover flex h-9 items-center gap-2 rounded-lg ps-1 pe-2 transition-colors"
      >
        <span className="bg-accent-soft text-accent flex size-7 items-center justify-center rounded-full">
          <UserRound className="size-4" />
        </span>
        <span className="flex flex-col items-start leading-tight">
          <span className="ns-ltr text-fg text-sm font-medium">{user.username}</span>
          <span className="text-fg-subtle text-2xs">{ROLE_LABELS[user.role]}</span>
        </span>
        <ChevronDown className="text-fg-subtle size-3.5" />
      </button>

      {open && (
        <div
          role="menu"
          className="bg-surface-strong shadow-pop border-line absolute end-0 top-11 z-40 w-48 rounded-lg border p-1"
        >
          {(user.role === 'admin' || user.role === 'analyst') && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void navigate('/backtests');
              }}
              className="hover:bg-sunken flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm"
            >
              <ChartNoAxesColumn className="size-4" />
              الاختبار التاريخي
            </button>
          )}
          {(user.role === 'admin' || user.role === 'analyst') && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void navigate('/forward-test');
              }}
              className="hover:bg-sunken flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm"
            >
              <FlaskConical className="size-4" />
              الاختبار المباشر
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              void navigate('/settings');
            }}
            className="hover:bg-sunken flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm"
          >
            <Settings className="size-4" />
            الإعدادات
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => void handleLogout()}
            className="text-bear hover:bg-bear-soft flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm"
          >
            <LogOut className="size-4" />
            تسجيل الخروج
          </button>
        </div>
      )}
    </div>
  );
}
