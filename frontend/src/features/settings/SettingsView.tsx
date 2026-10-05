import { useQuery } from '@tanstack/react-query';

import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { FORWARD_STATUS_AR } from '@/features/forwardTest/labels';
import { marketFeedLabel } from '@/features/markets/marketFeedLabel';
import { forwardTestApi } from '@/services/api/forwardTest';
import { systemApi } from '@/services/api/system';
import { useAuthStore } from '@/stores/authStore';
import { useConnectionStore } from '@/stores/connectionStore';
import { useMarketStore } from '@/stores/marketStore';
import { type Theme, useThemeStore } from '@/stores/themeStore';

import { DesktopSection } from './DesktopSection';
import { Row, Section } from './Section';
import { ROLE_AR } from './roles';
import { UsersSection } from './UsersSection';
import { WeatherSection } from './WeatherSection';

const THEMES = [
  { value: 'dark', label: 'داكن' },
  { value: 'light', label: 'فاتح' },
] as const satisfies readonly { value: Theme; label: string }[];

export function SettingsView() {
  const user = useAuthStore((s) => s.user);
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const feed = marketFeedLabel(
    useConnectionStore((s) => s.state),
    useMarketStore((s) => s.feed),
  );
  const runtime = useQuery({
    queryKey: ['system', 'runtime'],
    queryFn: ({ signal }) => systemApi.runtime(signal),
  });
  const forward = useQuery({
    queryKey: ['forward-test', 'status'],
    queryFn: ({ signal }) => forwardTestApi.status(signal),
    retry: false,
  });
  const run = forward.data?.run;
  return (
    <div
      className="mx-auto grid w-full max-w-5xl gap-3 p-3 lg:grid-cols-2"
      data-testid="settings-view"
    >
      <div className="flex flex-col gap-3">
        <Section id="account" title="الحساب">
          <Row label="اسم المستخدم">
            <span className="ns-ltr">{user?.username}</span>
          </Row>
          <Row label="الدور">{user ? ROLE_AR[user.role] : '--'}</Row>
        </Section>
        <Section id="appearance" title="المظهر">
          <SegmentedControl
            ariaLabel="السمة"
            value={theme}
            options={THEMES}
            onChange={(t) => {
              setTheme(t);
            }}
          />
        </Section>
        <Section id="strategy" title="استراتيجية الإشارات">
          <Row label="الاسم">{runtime.data?.strategy.name ?? '--'}</Row>
          <Row label="البصمة">
            <span className="ns-ltr" data-testid="settings-fingerprint">
              {runtime.data?.strategy.fingerprint ?? '--'}
            </span>
          </Row>
          <Row label="الإصدار">
            <span className="ns-ltr text-2xs">{runtime.data?.strategy.version ?? '--'}</span>
          </Row>
          <Row label="الاختبار المباشر">
            {run ? FORWARD_STATUS_AR[run.status] : 'غير مُثبت — لا يوجد تشغيل'}
          </Row>
          <p className="text-fg-subtle text-2xs mt-1">
            الإشارات قيد الاختبار وليست توصيات مضمونة. الإعدادات مجمّدة ولا تُعدّل من الواجهة.
          </p>
        </Section>
        <Section id="market" title="مزود بيانات السوق">
          <Row label="المزود">
            {runtime.data?.market_provider ?? 'OKX'} (بيانات عامة فقط، بدون مفاتيح)
          </Row>
          <Row label="الحالة">{feed.text}</Row>
        </Section>
      </div>
      <div className="flex flex-col gap-3">
        <DesktopSection runtime={runtime.data} />
        <WeatherSection enabled={runtime.data?.weather_enabled ?? true} />
        {user?.role === 'admin' && <UsersSection />}
      </div>
    </div>
  );
}
