import { CircleHelp, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { CHART_SIGNAL_AR, LEGEND_TERMS } from './copy';

/** «شرح الشارت»: explains the chart annotations in Arabic (RTL dialog). Display only. */
export function ChartLegend() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-label={CHART_SIGNAL_AR.legendButton}
        title={CHART_SIGNAL_AR.legendButton}
        aria-expanded={open}
        onClick={() => {
          setOpen(true);
        }}
        className="border-line text-fg-muted hover:text-fg hover:bg-surface-hover text-2xs flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 whitespace-nowrap"
      >
        <CircleHelp className="size-3.5" />
        <span className="hidden @2xl:inline">{CHART_SIGNAL_AR.legendButton}</span>
      </button>
      {open &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setOpen(false);
            }}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label={CHART_SIGNAL_AR.legendButton}
              dir="rtl"
              className="bg-surface-strong border-line shadow-pop flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border"
            >
              <header className="border-line flex items-center gap-2 border-b px-4 py-2.5">
                <CircleHelp className="text-accent size-4" />
                <h2 className="text-sm font-semibold">{CHART_SIGNAL_AR.legendButton}</h2>
                <button
                  type="button"
                  aria-label="إغلاق"
                  onClick={() => {
                    setOpen(false);
                  }}
                  className="text-fg-muted hover:text-fg ms-auto rounded-md p-1"
                >
                  <X className="size-4" />
                </button>
              </header>
              <div className="space-y-4 overflow-y-auto px-4 py-3 text-xs">
                <p
                  data-testid="legend-authority"
                  className="border-accent/40 bg-accent/10 text-fg rounded-lg border px-3 py-2 font-medium leading-relaxed"
                >
                  {CHART_SIGNAL_AR.legendAuthority}
                </p>

                <section className="space-y-1.5">
                  <h3 className="text-fg-muted text-2xs font-semibold">
                    علامات الإشارة على الشارت
                  </h3>
                  <ul className="space-y-1.5 leading-relaxed">
                    <li className="flex items-start gap-2">
                      <span className="text-bull ns-ltr shrink-0 font-semibold">▲ BUY</span>
                      <span>
                        شراء: إشارة مؤكدة من محرك Wese Trade، تحت شمعة التأكيد. تظهر على فريمات 15m
                        و 30m و 1h فقط.
                      </span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-bear ns-ltr shrink-0 font-semibold">▼ SELL</span>
                      <span>بيع: إشارة مؤكدة من محرك Wese Trade، فوق شمعة التأكيد.</span>
                    </li>
                    <li>
                      العلامة الباهتة = إشارة سابقة مغلقة. مرّر المؤشر فوق العلامة أو انقر عليها
                      لعرض تفاصيلها.
                    </li>
                    <li>
                      خطوط الخطة (الدخول، وقف الخسارة، الهدف 1/2/3) تظهر للإشارة المفتوحة فقط.
                    </li>
                    <li>لا توجد علامة للحالة المحايدة: الشارت يظهر بشكل عادي.</li>
                  </ul>
                </section>

                <section className="space-y-1.5">
                  <h3 className="text-fg-muted text-2xs font-semibold">مصطلحات التحليل</h3>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
                    {LEGEND_TERMS.map(({ term, ar }) => (
                      <div key={term} className="contents">
                        <dt className="ns-ltr text-fg font-semibold">{term}</dt>
                        <dd className="text-fg-muted">{ar}</dd>
                      </div>
                    ))}
                  </dl>
                </section>

                <p className="text-fg-subtle text-2xs">
                  {CHART_SIGNAL_AR.forward} · {CHART_SIGNAL_AR.unproven} —{' '}
                  {CHART_SIGNAL_AR.disclaimer}
                </p>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
