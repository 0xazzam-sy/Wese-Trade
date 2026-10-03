import { ChartWorkspace } from '@/features/charts/components/ChartWorkspace';
import { NewsPanel } from '@/features/news/NewsPanel';
import { ScannerSidebar } from '@/features/scanner/ScannerSidebar';
import { SignalPanel } from '@/features/signals/SignalPanel';
import { SystemIdentity } from '@/features/system/SystemIdentity';

/**
 * Workstation layout (RTL): the first grid column renders on the RIGHT.
 * The spec's "left sidebar" (scanner) is therefore the last column, and the
 * "right sidebar" (identity + news) is the first.
 */
export function DashboardPage() {
  return (
    <div className="grid h-full grid-cols-[272px_minmax(0,1fr)_264px] gap-3 p-3 2xl:grid-cols-[340px_minmax(0,1fr)_320px]">
      <div className="flex min-h-0 flex-col gap-3">
        <SystemIdentity />
        <NewsPanel />
      </div>

      <div className="flex min-h-0 min-w-0 flex-col gap-3">
        <ChartWorkspace />
        <SignalPanel />
      </div>

      <ScannerSidebar />
    </div>
  );
}
