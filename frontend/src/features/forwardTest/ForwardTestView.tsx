import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Pause, Play, Square } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/cn';
import { forwardTestApi } from '@/services/api/forwardTest';
import { useAuthStore } from '@/stores/authStore';
import type { ForwardRun, ForwardSignalFilters, ForwardStats } from '@/types/forwardTest';

import { STATE_AR } from '../signals/lib/labels';
import {
  FORWARD_DISCLAIMER,
  FORWARD_STATUS_AR,
  HEALTH_AR,
  VERDICT_AR,
  fmtNum,
  fmtPct,
  fmtR,
  statusTone,
} from './labels';

function tone(v: number | null | undefined): string {
  if (v == null) return 'text-fg-muted';
  return v > 0 ? 'text-bull' : v < 0 ? 'text-bear' : 'text-fg';
}

function fmtTime(iso: string | null | undefined): { utc: string; local: string } {
  if (!iso) return { utc: '--', local: '--' };
  const d = new Date(iso);
  return {
    utc: `${d.toISOString().replace('T', ' ').slice(0, 19)} UTC`,
    local: d.toLocaleString('ar', { hour12: false }),
  };
}

function Tile({ label, value, valueTone }: { label: string; value: string; valueTone?: string }) {
  return (
    <div className="bg-sunken rounded-lg px-3 py-2">
      <div className="text-fg-subtle text-2xs">{label}</div>
      <div className={cn('ns-num ns-ltr text-sm font-semibold', valueTone)}>{value}</div>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: Record<string, ForwardStats> }) {
  const keys = Object.keys(rows);
  return (
    <section className="ns-panel p-3">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {keys.length === 0 ? (
        <p className="text-fg-subtle text-2xs">لا توجد صفقات مغلقة بعد.</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-fg-subtle">
            <tr>
              <th className="text-start font-medium">المجموعة</th>
              <th className="font-medium">الصفقات</th>
              <th className="font-medium">التوقع الصافي</th>
              <th className="font-medium">PF</th>
              <th className="font-medium">متوسط R</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const s = rows[k];
              if (!s) return null;
              return (
                <tr key={k} className="border-line/50 border-t">
                  <td className="ns-ltr py-1 text-start">{k}</td>
                  <td className="ns-num text-center">{s.entered}</td>
                  <td className={cn('ns-num ns-ltr text-center', tone(s.expectancy))}>
                    {fmtR(s.expectancy)}
                  </td>
                  <td className="ns-num text-center">{fmtNum(s.profit_factor)}</td>
                  <td className="ns-num ns-ltr text-center">{fmtR(s.avg_r)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Controls({ run }: { run: ForwardRun }) {
  const client = useQueryClient();
  const [note, setNote] = useState('');
  const mutation = useMutation({
    mutationFn: (action: 'pause' | 'resume' | 'stop') =>
      forwardTestApi.control(run.id, action, note),
    onSuccess: () => {
      setNote('');
      void client.invalidateQueries({ queryKey: ['forward-test'] });
    },
  });
  const btn =
    'border-line hover:bg-surface-hover flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs disabled:opacity-50';
  return (
    <section aria-label="تحكم المدير" className="ns-panel p-3" data-testid="forward-controls">
      <h3 className="mb-2 text-sm font-semibold">تحكم المدير</h3>
      <p className="text-fg-subtle text-2xs mb-2">
        الإعدادات مجمّدة؛ يمكن فقط الإيقاف المؤقت أو الاستئناف أو الإنهاء.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="ملاحظة"
          value={note}
          maxLength={500}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="ملاحظة (اختياري)"
          className="border-line bg-sunken min-w-40 flex-1 rounded-md border px-2 py-1.5 text-xs"
        />
        {run.status === 'forward_testing' && (
          <button
            type="button"
            className={btn}
            disabled={mutation.isPending}
            onClick={() => {
              mutation.mutate('pause');
            }}
          >
            <Pause className="size-3.5" />
            إيقاف مؤقت
          </button>
        )}
        {run.status === 'paused' && (
          <button
            type="button"
            className={btn}
            disabled={mutation.isPending}
            onClick={() => {
              mutation.mutate('resume');
            }}
          >
            <Play className="size-3.5" />
            استئناف
          </button>
        )}
        <button
          type="button"
          className={cn(btn, 'text-bear')}
          disabled={mutation.isPending}
          onClick={() => {
            if (window.confirm('إنهاء الاختبار المباشر نهائياً؟')) mutation.mutate('stop');
          }}
        >
          <Square className="size-3.5" />
          إنهاء الاختبار
        </button>
      </div>
      {mutation.isError && <p className="text-bear text-2xs mt-2">تعذّر تنفيذ الإجراء.</p>}
    </section>
  );
}

const SIDES = [
  { value: '', label: 'الكل' },
  { value: 'long', label: 'شراء' },
  { value: 'short', label: 'بيع' },
];

function History({ run }: { run: ForwardRun }) {
  const [filters, setFilters] = useState<ForwardSignalFilters>({});
  const { data, isLoading } = useQuery({
    queryKey: ['forward-test', 'signals', run.id, filters],
    queryFn: ({ signal }) => forwardTestApi.signals(run.id, filters, signal),
    refetchInterval: 60_000,
  });
  const set = (k: keyof ForwardSignalFilters) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    setFilters((f) => ({ ...f, [k]: e.target.value || undefined }));
  };
  const select = 'border-line bg-sunken rounded-md border px-2 py-1 text-xs';
  const items = data?.items ?? [];
  return (
    <section className="ns-panel p-3" aria-label="سجل الإشارات">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="me-auto text-sm font-semibold">سجل الإشارات</h3>
        <select aria-label="الرمز" className={select} onChange={set('symbol')}>
          <option value="">كل الرموز</option>
          {run.symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select aria-label="الفريم" className={select} onChange={set('timeframe')}>
          <option value="">كل الفريمات</option>
          {run.timeframes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select aria-label="الاتجاه" className={select} onChange={set('side')}>
          {SIDES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <select aria-label="الحالة" className={select} onChange={set('state')}>
          <option value="">كل الحالات</option>
          {Object.entries(STATE_AR)
            .filter(([k]) => k !== 'developing')
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
      </header>
      {isLoading ? (
        <p className="text-fg-subtle text-2xs">جارٍ التحميل…</p>
      ) : items.length === 0 ? (
        <p className="text-fg-subtle text-2xs" data-testid="history-empty">
          لا توجد إشارات مؤكدة منذ بدء الاختبار.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] text-xs" data-testid="history-table">
            <thead className="text-fg-subtle">
              <tr>
                <th className="text-start font-medium">الوقت</th>
                <th className="font-medium">الرمز</th>
                <th className="font-medium">الفريم</th>
                <th className="font-medium">الاتجاه</th>
                <th className="font-medium">قوة الإشارة</th>
                <th className="font-medium">الدخول</th>
                <th className="font-medium">الوقف</th>
                <th className="font-medium">الأهداف</th>
                <th className="font-medium">الحالة</th>
                <th className="font-medium">النتيجة</th>
                <th className="font-medium">الإصدار</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.signal_id} className="border-line/50 border-t">
                  <td className="ns-ltr ns-num py-1 text-start">{fmtTime(s.confirmed_at).utc}</td>
                  <td className="ns-ltr text-center">{s.symbol}</td>
                  <td className="ns-ltr text-center">{s.timeframe}</td>
                  <td className={cn('text-center', s.side === 'long' ? 'text-bull' : 'text-bear')}>
                    {s.side === 'long' ? 'شراء' : 'بيع'}
                  </td>
                  <td className="ns-num text-center">{Math.round(s.score)}/100</td>
                  <td className="ns-num ns-ltr text-center">{s.entry}</td>
                  <td className="ns-num ns-ltr text-center">{s.stop}</td>
                  <td className="ns-num ns-ltr text-center">
                    {s.tp1} / {s.tp2} / {s.tp3}
                  </td>
                  <td className="text-center">
                    {(STATE_AR as Record<string, string | undefined>)[s.state] ?? s.state}
                  </td>
                  <td className={cn('ns-num ns-ltr text-center', tone(s.net_r))}>
                    {fmtR(s.net_r, 2)}
                  </td>
                  <td className="ns-ltr text-fg-subtle text-center">
                    {s.strategy_version.slice(-10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ForwardTestView() {
  const user = useAuthStore((s) => s.user);
  const status = useQuery({
    queryKey: ['forward-test', 'status'],
    queryFn: ({ signal }) => forwardTestApi.status(signal),
    refetchInterval: 60_000,
  });
  const runId = status.data?.run?.id;
  const runQuery = useQuery({
    queryKey: ['forward-test', 'run', runId],
    queryFn: ({ signal }) => forwardTestApi.run(runId ?? 0, signal),
    enabled: runId != null,
    refetchInterval: 60_000,
  });

  if (status.isLoading) return <p className="text-fg-subtle p-4 text-sm">جارٍ التحميل…</p>;
  if (status.isError || !status.data)
    return <p className="text-bear p-4 text-sm">تعذّر تحميل حالة الاختبار المباشر.</p>;
  const card = status.data;
  const run = runQuery.data;

  return (
    <div
      className="mx-auto flex w-full max-w-6xl flex-col gap-3 p-3"
      data-testid="forward-test-view"
    >
      <section className="ns-panel p-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">{card.name}</h2>
          <span className="border-accent/40 bg-accent/10 text-accent text-2xs rounded-md border px-1.5 py-0.5">
            اختبار مباشر
          </span>
          {run && (
            <span
              data-testid="run-status"
              className={cn('text-2xs rounded-md border px-1.5 py-0.5', statusTone(run.status))}
            >
              {FORWARD_STATUS_AR[run.status]}
            </span>
          )}
          <span className="ns-ltr text-fg-subtle text-2xs ms-auto" data-testid="fingerprint">
            {card.fingerprint}
          </span>
        </div>
        <p className="ns-ltr text-fg-subtle text-2xs mt-1">{card.version}</p>
        <p className="text-warning mt-2 text-xs" data-testid="forward-disclaimer">
          {FORWARD_DISCLAIMER}
        </p>
      </section>

      {!card.run ? (
        <section className="ns-panel p-3 text-sm" data-testid="no-run">
          لا يوجد اختبار مباشر نشط. يُنشأ التشغيل من سطر الأوامر ولا يُعدَّل من الواجهة.
        </section>
      ) : !run ? (
        <p className="text-fg-subtle p-2 text-sm">جارٍ تحميل التشغيل…</p>
      ) : (
        <RunBody run={run} isAdmin={user?.role === 'admin'} />
      )}
    </div>
  );
}

function RunBody({ run, isAdmin }: { run: ForwardRun; isAdmin: boolean }) {
  const m = run.metrics;
  const started = fmtTime(run.started_at);
  const c = m.counts;
  const a = m.all;
  const verdict = m.assessment.verdict;
  return (
    <>
      <section className="ns-panel grid gap-2 p-3 text-xs sm:grid-cols-2">
        <div>
          <span className="text-fg-subtle">بداية الاختبار: </span>
          <span className="ns-ltr ns-num" data-testid="started-utc">
            {started.utc}
          </span>
          <span className="text-fg-subtle"> — محلياً: </span>
          <span className="ns-num">{started.local}</span>
        </div>
        <div>
          <span className="text-fg-subtle">الأيام المنقضية: </span>
          <span className="ns-num">
            {fmtNum(m.elapsed_days, 1)} / {run.minimum_days}
          </span>
        </div>
        <div>
          <span className="text-fg-subtle">الرموز ({run.symbols.length}): </span>
          <span className="ns-ltr">{run.symbols.join(', ')}</span>
        </div>
        <div>
          <span className="text-fg-subtle">الفريمات: </span>
          <span className="ns-ltr">{run.timeframes.join(', ')}</span>
          <span className="text-fg-subtle"> — فريمات 1m/5m/10m للسياق فقط</span>
        </div>
        <div>
          <span className="text-fg-subtle">الصحة: </span>
          <span data-testid="health">
            {run.health ? (HEALTH_AR[run.health.state] ?? run.health.state) : 'غير محمّل'}
          </span>
          {run.health?.last_candle_close != null && (
            <span className="text-fg-subtle ns-ltr">
              {' '}
              — {fmtTime(new Date(run.health.last_candle_close * 1000).toISOString()).utc}
            </span>
          )}
        </div>
        <div>
          <span className="text-fg-subtle">التكاليف: </span>
          <span className="ns-ltr">
            taker {String(run.cost_model.fee_rate)} · maker {String(run.cost_model.maker_fee_rate)}{' '}
            · slippage {String(run.cost_model.slippage_rate)}
          </span>
        </div>
        {!run.config_matches_code && (
          <p className="text-bear sm:col-span-2">
            تحذير: إصدار الكود الحالي لا يطابق إعدادات هذا التشغيل.
          </p>
        )}
      </section>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6" data-testid="stats">
        <Tile label="إشارات مؤكدة" value={String(c.confirmed)} />
        <Tile label="نشطة" value={String(c.active)} />
        <Tile
          label="صفقات مغلقة"
          value={`${String(c.closed_trades)} / ${String(run.minimum_required_trades)}`}
        />
        <Tile label="رابحة" value={String(c.wins)} />
        <Tile label="خاسرة" value={String(c.losses)} />
        <Tile label="غامضة" value={String(c.ambiguous)} />
        <Tile label="انتهت دون دخول" value={String(c.expired_unfilled)} />
        <Tile label="التوقع الصافي" value={fmtR(a.expectancy)} valueTone={tone(a.expectancy)} />
        <Tile
          label="التوقع الإجمالي"
          value={fmtR(a.gross_expectancy)}
          valueTone={tone(a.gross_expectancy)}
        />
        <Tile label="عامل الربح PF" value={fmtNum(a.profit_factor)} />
        <Tile label="أقصى تراجع" value={`${fmtNum(a.max_drawdown_r)}R`} />
        <Tile label="متوسط R" value={fmtR(a.avg_r)} />
        <Tile label="وسيط R" value={fmtR(a.median_r)} />
        <Tile label="متوسط مدة الاحتفاظ" value={`${fmtNum(a.avg_hold_hours, 1)} س`} />
        <Tile label="نسبة الصفقات الرابحة (ثانوي)" value={fmtPct(a.win_rate)} />
        <Tile
          label="آخر 30 صفقة"
          value={fmtR(m.recent.expectancy)}
          valueTone={tone(m.recent.expectancy)}
        />
      </section>

      <section className="ns-panel p-3 text-xs" data-testid="assessment">
        <h3 className="mb-1 text-sm font-semibold">التقييم مقابل الشروط المسجّلة مسبقاً</h3>
        <p>{VERDICT_AR[verdict] ?? verdict}</p>
        {m.assessment.reasons.length > 0 && (
          <ul className="text-fg-subtle ns-ltr mt-1 list-disc ps-5">
            {m.assessment.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        <p className="text-fg-subtle mt-2">
          المقاييس الأساسية: التوقع الصافي وعامل الربح والتراجع ومتوسط R وحجم العينة. قوة الإشارة
          غير معايرة وليست احتمال نجاح.
        </p>
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        <Breakdown title="حسب الفريم" rows={m.by_timeframe} />
        <Breakdown title="حسب الاتجاه" rows={m.by_side} />
        <Breakdown title="حسب الرمز" rows={m.by_symbol} />
        <Breakdown title="حسب حالة السوق" rows={m.by_regime} />
        <Breakdown title="حسب قوة الإشارة" rows={m.by_score_bucket} />
      </div>

      <History run={run} />

      <section className="ns-panel flex flex-wrap items-center gap-2 p-3 text-xs">
        <span className="text-fg-subtle me-auto">تصدير (بدون أسرار)</span>
        <a
          className="flex items-center gap-1 underline"
          href={forwardTestApi.exportUrl(run.id, 'csv')}
        >
          <Download className="size-3.5" /> CSV
        </a>
        <a
          className="flex items-center gap-1 underline"
          href={forwardTestApi.exportUrl(run.id, 'json')}
        >
          <Download className="size-3.5" /> JSON
        </a>
      </section>

      {isAdmin && run.stopped_at == null && <Controls run={run} />}
    </>
  );
}
