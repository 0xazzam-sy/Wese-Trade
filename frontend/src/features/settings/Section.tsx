import type { ReactNode } from 'react';

export function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-label={title} className="ns-panel scroll-mt-4 p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
      <span className="text-fg-subtle text-xs">{label}</span>
      <span className="text-fg-muted min-w-0 text-end">{children}</span>
    </div>
  );
}
