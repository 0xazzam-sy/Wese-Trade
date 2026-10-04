import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { cn } from '@/lib/cn';
import { backtestsApi } from '@/services/api/backtests';
import type { BacktestSplit, BacktestStats } from '@/types/backtest';

import { FAMILY_AR, RISK_NOTE } from '../signals/lib/labels';

type SplitKey = 'holdout' | 'dev' | 'all';

const SPLITS = [
  { value: 'holdout', label: 'الاختبار المحجوز' },
  { value: 'dev', label: 'التطوير' },
  { value: 'all', label: 'الكل' },
] as const satisfies readonly { value: SplitKey; label: string }[];

function r(value: number | null | undefined, digits = 3): string {
  if (value == null) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}R`;
}

function pct(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(1)}%`;
}

function num(value: number | null | undefined, digits = 2): string {
  return value == null ? '--' : value.toFixed(digits);
}

function tone(value: number | null | undefined): string {
  if (value == null) return 'text-fg-muted';
  return value > 0 ? 'text-bull' : value < 0 ? 'text-bear' : 'text-fg';
}

function StatsTable({
  title,
  rows,
  labels,
}: {
  title: string;
  rows: Record<string, BacktestStats>;
  labels?: Record<string, string>;
}) {
  return (
    <section className="ns-panel p-3">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <table className="w-full text-xs">
        <thead className="text-fg-subtle">
          <tr>
            <th className="text-start font-medium">المجموعة</th>
            <th className="font-medium">الصفقات</th>
            <th className="font-medium">نسبة الربح</th>
            <th className="font-medium">التوقع الصافي</th>
            <th className="font-medium">التوقع الإجمالي</th>
            <th className="font-medium">PF</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([key, s]) => (
            <tr key={key} className="border-line border-t">
              <td className="py-1 text-start">{labels?.[key] ?? key}</td>
              <td className="ns-num text-center">{s.entered}</td>
              <td className="ns-num text-center">{pct(s.win_rate)}</td>
              <td className={cn('ns-num text-center', tone(s.expectancy))}>{r(s.expectancy)}</td>
              <td className={cn('ns-num text-center', tone(s.gross_expectancy))}>
                {r(s.gross_expectancy)}
              </td>
              <td className="ns-num text-center">{num(s.profit_factor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Overview({ split }: { split: BacktestSplit }) {
  const o = split.overall;
  const items: [string, string, string?][] = [
    ['الصفقات المنفذة', String(o.entered)],
    ['نسبة الربح', pct(o.win_rate)],
    ['التوقع الصافي', r(o.expectancy), tone(o.expectancy)],
    ['التوقع قبل التكاليف', r(o.gross_expectancy), tone(o.gross_expectancy)],
    ['معامل الربح', num(o.profit_factor)],
    ['أقصى تراجع', r(-o.max_drawdown_r, 1), 'text-bear'],
    ['الوسيط', r(o.median_r)],
    ['TP1 / TP2 / TP3', `${pct(o.tp1_rate)} / ${pct(o.tp2_rate)} / ${pct(o.tp3_rate)}`],
    ['أطول سلسلة خسائر', String(o.max_consecutive_losses)],
    ['حالات غامضة', String(o.ambiguous)],
  ];
  return (
    <dl className="grid grid-cols-5 gap-2" aria-label="ملخص الاختبار">
      {items.map(([label, value, cls]) => (
        <div key={label} className="bg-sunken border-line rounded-lg border px-2.5 py-1.5">
          <dt className="text-fg-subtle text-2xs">{label}</dt>
          <dd className={cn('ns-num text-sm font-semibold', cls)}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Calibration({ split }: { split: BacktestSplit }) {
  return (
    <section className="ns-panel p-3">
      <h3 className="mb-1 text-sm font-semibold">معايرة قوة الإشارة</h3>
      <p className="text-fg-subtle text-2xs mb-2">
        {split.score_monotonic
          ? 'النتائج تتحسن مع ارتفاع قوة الإشارة.'
          : 'النتائج لا تتحسن بشكل مطّرد مع ارتفاع قوة الإشارة — الدرجة ليست احتمالية.'}
      </p>
      <table className="w-full text-xs">
        <thead className="text-fg-subtle">
          <tr>
            <th className="text-start font-medium">النطاق</th>
            <th className="font-medium">الصفقات</th>
            <th className="font-medium">نسبة الربح</th>
            <th className="font-medium">التوقع الصافي</th>
          </tr>
        </thead>
        <tbody>
          {split.calibration
            .filter((c) => c.signals > 0)
            .map((c) => (
              <tr key={c.bucket} className="border-line border-t">
                <td className="ns-num py-1 text-start">{c.bucket}</td>
                <td className="ns-num text-center">{c.entered}</td>
                <td className="ns-num text-center">{pct(c.win_rate)}</td>
                <td className={cn('ns-num text-center', tone(c.expectancy))}>{r(c.expectancy)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </section>
  );
}

/** Developer/admin view of stored backtest runs. Read-only; results are historical, in R. */
export function BacktestView() {
  const [selected, setSelected] = useState<number | null>(null);
  const [split, setSplit] = useState<SplitKey>('holdout');
  const list = useQuery({
    queryKey: ['backtests'],
    queryFn: ({ signal }) => backtestsApi.list(signal),
  });
  const runId = selected ?? list.data?.items[0]?.id ?? null;
  const run = useQuery({
    queryKey: ['backtests', runId],
    queryFn: ({ signal }) => backtestsApi.get(runId ?? 0, signal),
    enabled: runId !== null,
  });

  if (list.isError) return <p className="text-bear p-4 text-sm">تعذر تحميل نتائج الاختبار.</p>;
  if (list.data?.items.length === 0) {
    return <p className="text-fg-muted p-4 text-sm">لا توجد اختبارات محفوظة بعد.</p>;
  }
  const data = run.data?.summary[split];
  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-4">
      <header className="flex items-center gap-3">
        <h2 className="text-base font-semibold">الاختبار التاريخي</h2>
        <select
          aria-label="الاختبار"
          className="bg-sunken border-line rounded-md border px-2 py-1 text-sm"
          value={runId ?? ''}
          onChange={(e) => {
            setSelected(Number(e.target.value));
          }}
        >
          {list.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {new Date(item.created_at).toLocaleDateString()}
            </option>
          ))}
        </select>
        {run.data && (
          <span className="ns-ltr text-fg-subtle text-2xs">{run.data.strategy_version}</span>
        )}
        <div className="ms-auto">
          <SegmentedControl
            size="sm"
            ariaLabel="جزء البيانات"
            value={split}
            options={SPLITS}
            onChange={setSplit}
          />
        </div>
      </header>
      <p className="text-fg-subtle text-2xs">
        النتائج بوحدات المخاطرة (R) بعد الرسوم والانزلاق. الأداء التاريخي لا يضمن النتائج
        المستقبلية. {RISK_NOTE}
      </p>
      {data ? (
        <>
          <Overview split={data} />
          <div className="grid grid-cols-2 gap-3">
            <StatsTable title="حسب الرمز" rows={data.by_symbol} />
            <StatsTable title="حسب الإطار الزمني" rows={data.by_timeframe} />
            <StatsTable title="حسب نوع الإعداد" rows={data.by_setup} labels={FAMILY_AR} />
            <StatsTable title="حسب حالة السوق" rows={data.by_regime} />
            <Calibration split={data} />
          </div>
        </>
      ) : (
        <p className="text-fg-muted text-sm">جاري التحميل…</p>
      )}
    </div>
  );
}
