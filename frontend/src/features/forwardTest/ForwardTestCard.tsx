import { useQuery } from '@tanstack/react-query';
import { FlaskConical } from 'lucide-react';

import { cn } from '@/lib/cn';
import { forwardTestApi } from '@/services/api/forwardTest';

import { FORWARD_DISCLAIMER, fmtR, statusTone } from './labels';

/** Compact dashboard card: which strategy is being forward-tested and how it is doing. */
export function ForwardTestCard() {
  const { data, isError } = useQuery({
    queryKey: ['forward-test', 'status'],
    queryFn: ({ signal }) => forwardTestApi.status(signal),
    refetchInterval: 60_000,
    retry: false,
  });
  return (
    <section aria-label="استراتيجية الإشارات" className="ns-panel shrink-0 p-3">
      <header className="mb-2 flex items-center gap-2">
        <FlaskConical className="text-accent size-4" />
        <h2 className="text-sm font-semibold">استراتيجية الإشارات</h2>
        {data?.run && (
          <span
            data-testid="forward-status"
            className={cn(
              'text-2xs ms-auto rounded-md border px-1.5 py-0.5',
              statusTone(data.run.status),
            )}
          >
            {data.run.status_ar}
          </span>
        )}
      </header>
      {isError || !data ? (
        <p className="text-fg-subtle text-2xs">حالة الاختبار المباشر غير متاحة.</p>
      ) : !data.run ? (
        <p className="text-fg-subtle text-2xs">لا يوجد اختبار مباشر نشط.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <dt className="text-fg-subtle">الإصدار</dt>
          <dd className="ns-ltr ns-num" data-testid="forward-fingerprint">
            {data.run.fingerprint}
          </dd>
          <dt className="text-fg-subtle">صفقات مغلقة</dt>
          <dd className="ns-num">
            {data.closed_trades ?? 0} / {data.minimum_required_trades ?? 150}
          </dd>
          <dt className="text-fg-subtle">التوقع الصافي</dt>
          <dd className="ns-num">{fmtR(data.net_expectancy_r)}</dd>
        </dl>
      )}
      <p className="text-fg-subtle text-2xs mt-2">{FORWARD_DISCLAIMER}</p>
    </section>
  );
}
