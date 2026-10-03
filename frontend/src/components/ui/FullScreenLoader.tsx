import { LogoMark } from './Logo';
import { Spinner } from './Spinner';

export function FullScreenLoader({ label }: { label: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <LogoMark className="size-12" />
      <div className="text-fg-muted flex items-center gap-2 text-sm">
        <Spinner label={label} />
        {label}
      </div>
    </div>
  );
}
