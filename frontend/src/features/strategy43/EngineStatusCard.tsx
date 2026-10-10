import { useQuery } from '@tanstack/react-query';
import { Activity } from 'lucide-react';

import { cn } from '@/lib/cn';
import { strategy43Api } from '@/services/api/strategy43';

import { ago, ENGINE_TONE, S43_AR, TELEGRAM_STATE_AR } from './labels';

/**
 * «محرك الإشارات»: is the live engine running, and if not, the real technical problem
 * reported by the backend (never a generic "inactive" message).
 */
export function EngineStatusCard({ detailed = false }: { detailed?: boolean }) {
  const { data, isError } = useQuery({
    queryKey: ['strategy43', 'health'],
    queryFn: ({ signal }) => strategy43Api.health(signal),
    refetchInterval: 15_000,
    retry: false,
  });
  const rows: [string, string][] = data
    ? [
        [S43_AR.lastMarket, ago(data.last_market_update)],
        [S43_AR.lastCandle, ago(data.last_candle_close)],
        [S43_AR.lastScan, ago(data.last_scan_at)],
        [S43_AR.lastSignal, ago(data.last_signal_at)],
        [S43_AR.openCount, String(data.open_opportunities)],
        [
          'A+ / A / B / C',
          `${String(data.open_by_tier['A+'])} / ${String(data.open_by_tier.A)} / ${String(
            data.open_by_tier.B,
          )} / ${String(data.open_by_tier.C)}`,
        ],
        ['الأسواق المفحوصة', `${String(data.markets_scanned)} / ${String(data.universe_size)}`],
        [S43_AR.todayCount, String(data.signals?.today?.total ?? 0)],
        ['محرك توقيت الدخول', data.execution ? 'نشط' : '--'],
        [
          S43_AR.telegram,
          data.telegram ? (TELEGRAM_STATE_AR[data.telegram.state] ?? data.telegram.state) : '--',
        ],
        [
          'آخر إرسال Telegram',
          data.telegram?.last_sent_at ? ago(Date.parse(data.telegram.last_sent_at) / 1000) : '--',
        ],
      ]
    : [];
  return (
    <section
      aria-label={S43_AR.engine}
      data-testid="engine-status"
      data-state={data?.state ?? (isError ? 'error' : 'loading')}
      className="ns-panel shrink-0 p-3"
    >
      <header className="mb-1.5 flex items-center gap-2">
        <Activity className="text-accent size-4" />
        <h2 className="text-sm font-semibold">{S43_AR.engine}</h2>
        {data && (
          <span
            data-testid="engine-state"
            className={cn('text-2xs rounded-md border px-1.5 py-0.5', ENGINE_TONE[data.state])}
          >
            {data.state_ar}
          </span>
        )}
        {data && (
          <span className="ns-ltr text-fg-subtle text-2xs ms-auto" title={data.version}>
            Strategy {data.fingerprint}
          </span>
        )}
      </header>
      {isError ? (
        <p className="text-bear text-2xs" role="alert">
          تعذر الاتصال بمحرك الإشارات (الخادم المحلي لا يستجيب).
        </p>
      ) : !data ? (
        <p className="text-fg-subtle text-2xs">جارٍ التحميل…</p>
      ) : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {rows.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-fg-subtle">{k}</dt>
                <dd className="ns-num text-end">{v}</dd>
              </div>
            ))}
          </dl>
          {data.open_opportunities === 0 && (data.why_none?.length ?? 0) > 0 && (
            <div className="text-fg-subtle text-2xs mt-1.5" data-testid="engine-why-none">
              <p>لماذا لا توجد فرص الآن:</p>
              <ul>
                {data.why_none?.slice(0, 3).map((w) => (
                  <li key={w.reason}>
                    • {w.reason} ({w.streams})
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(data.warm?.pending ?? 0) > 0 && (
            <p className="text-fg-subtle text-2xs mt-1" data-testid="engine-warming">
              جارٍ تحليل الشموع الأخيرة لاستعادة الفرص الحالية… ({data.warm?.pending})
            </p>
          )}
          {data.problems.length > 0 && (
            <ul className="text-warning text-2xs mt-1.5 flex flex-col gap-0.5" role="alert">
              {data.problems.map((p) => (
                <li key={p}>• {p}</li>
              ))}
            </ul>
          )}
          {detailed && (
            <dl className="border-line text-2xs mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t pt-1.5">
              <dt className="text-fg-subtle">الأسواق المفحوصة</dt>
              <dd className="ns-num text-end">
                {data.markets_scanned} / {data.universe_size}
              </dd>
              <dt className="text-fg-subtle">A+ / A / B / C المفتوحة</dt>
              <dd className="ns-num text-end">
                {data.open_by_tier['A+']} / {data.open_by_tier.A} / {data.open_by_tier.B} /{' '}
                {data.open_by_tier.C}
              </dd>
              <dt className="text-fg-subtle">إشارات 7 أيام / 30 يوماً</dt>
              <dd className="ns-num text-end">
                {data.signals?.['7d']?.total ?? 0} / {data.signals?.['30d']?.total ?? 0}
              </dd>
              <dt className="text-fg-subtle">طبقة توقيت الدخول</dt>
              <dd className="text-end">
                {data.execution ? `${String(data.execution.confirmed)} تأكيد` : '--'}
              </dd>
              <dt className="text-fg-subtle">المرجع المجمّد</dt>
              <dd className="ns-ltr text-end">
                {data.baseline_4_2 ? `Strategy ${data.baseline_4_2.fingerprint}` : '--'}
              </dd>
              <dt className="text-fg-subtle">الإصدار</dt>
              <dd className="ns-ltr truncate text-end">{data.version}</dd>
            </dl>
          )}
        </>
      )}
    </section>
  );
}
