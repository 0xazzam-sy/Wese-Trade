import { Outlet } from 'react-router';

import { useRealtimeConnection } from '@/features/realtime/useRealtimeConnection';
import { StatusBanners } from '@/features/system/StatusBanners';

import { AppHeader } from './AppHeader';

/** Authenticated workstation frame: header + page content; owns the realtime connection. */
export function AppShell() {
  useRealtimeConnection();

  return (
    <div className="flex h-full min-w-[1366px] flex-col overflow-hidden">
      <AppHeader />
      <StatusBanners />
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
