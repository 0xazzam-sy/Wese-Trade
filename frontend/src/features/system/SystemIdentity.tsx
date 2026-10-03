import { useQuery } from '@tanstack/react-query';

import { LogoMark, Wordmark } from '@/components/ui/Logo';
import { NeuralBackdrop } from '@/components/ui/NeuralBackdrop';
import { StatusDot, type StatusTone } from '@/components/ui/StatusDot';
import { systemApi } from '@/services/api/system';
import { useConnectionStore } from '@/stores/connectionStore';

function Row({ label, value, tone }: { label: string; value: string; tone: StatusTone }) {
  return (
    <li className="flex items-center justify-between gap-2 py-1">
      <span className="text-fg-subtle text-xs">{label}</span>
      <span className="text-fg-muted flex items-center gap-1.5 text-xs">
        <StatusDot tone={tone} />
        {value}
      </span>
    </li>
  );
}

/** Brand block + live system status (real health data from the backend). */
export function SystemIdentity() {
  const health = useQuery({
    queryKey: ['system', 'health'],
    queryFn: ({ signal }) => systemApi.health(signal),
    refetchInterval: 30_000,
  });
  const realtime = useConnectionStore((s) => s.state);

  const api: [string, StatusTone] = health.isPending
    ? ['جاري الفحص', 'pending']
    : health.data?.status === 'ok'
      ? ['يعمل', 'ok']
      : ['متعطل', 'error'];
  const db: [string, StatusTone] = health.isPending
    ? ['جاري الفحص', 'pending']
    : health.data?.database.status === 'ok'
      ? ['متصلة', 'ok']
      : ['غير متاحة', 'error'];
  const ws: [string, StatusTone] =
    realtime === 'connected'
      ? ['متصل', 'ok']
      : realtime === 'connecting'
        ? ['جاري الاتصال', 'pending']
        : ['غير متصل', 'error'];

  return (
    <section aria-label="هوية النظام" className="ns-panel relative overflow-hidden p-4">
      <NeuralBackdrop className="opacity-70" />
      <div className="relative flex items-center gap-3">
        <LogoMark className="size-10" />
        <div className="flex flex-col">
          <Wordmark className="text-lg" />
          <span className="text-fg-subtle text-xs">منصة تحليل العقود الآجلة</span>
        </div>
        {health.data && (
          <span className="ns-num text-fg-subtle text-2xs ms-auto self-start">
            v{health.data.version}
          </span>
        )}
      </div>
      <ul className="border-line relative mt-3 border-t pt-2">
        <Row label="الخادم" value={api[0]} tone={api[1]} />
        <Row label="قاعدة البيانات" value={db[0]} tone={db[1]} />
        <Row label="الاتصال اللحظي" value={ws[0]} tone={ws[1]} />
        <Row label="مزود البيانات BingX" value="غير مفعّل" tone="idle" />
      </ul>
      <p className="text-fg-subtle text-2xs relative mt-2 leading-5">
        منصة تحليل فقط — لا يتم تنفيذ أي صفقات.
      </p>
    </section>
  );
}
