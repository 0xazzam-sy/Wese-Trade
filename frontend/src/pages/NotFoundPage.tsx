import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <p className="ns-num text-fg-subtle text-5xl font-semibold">404</p>
      <p className="text-fg-muted">الصفحة غير موجودة</p>
      <Link to="/" className="text-accent text-sm hover:underline">
        العودة إلى لوحة التحليل
      </Link>
    </div>
  );
}
