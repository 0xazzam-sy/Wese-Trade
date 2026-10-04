import { Check, Layers } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { OVERLAY_LABELS, useOverlayStore } from '@/stores/overlayStore';

/** Chart overlay toggles (persisted locally). Purely visual: analysis is always computed. */
export function OverlayMenu() {
  const [open, setOpen] = useState(false);
  const toggles = useOverlayStore((s) => s.toggles);
  const toggle = useOverlayStore((s) => s.toggle);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <IconButton
        size="sm"
        label="طبقات التحليل"
        active={open}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => {
          setOpen((v) => !v);
        }}
        icon={<Layers className="size-3.5" />}
      />
      {open && (
        <div
          role="group"
          aria-label="طبقات التحليل على الرسم"
          className="bg-surface-strong border-line shadow-pop absolute end-0 top-8 z-30 w-48 rounded-lg border p-1"
        >
          {OVERLAY_LABELS.map(({ key, label }) => {
            const on = toggles[key];
            return (
              <button
                key={key}
                type="button"
                role="menuitemcheckbox"
                aria-checked={on}
                onClick={() => {
                  toggle(key);
                }}
                className="hover:bg-surface-hover flex w-full items-center justify-between rounded-md px-2 py-1.5 text-xs"
              >
                <span className={cn(on ? 'text-fg' : 'text-fg-muted')}>{label}</span>
                <span
                  className={cn(
                    'border-line flex size-4 items-center justify-center rounded border',
                    on && 'bg-accent-soft border-accent text-accent',
                  )}
                >
                  {on && <Check className="size-3" />}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
