import { Maximize2, Minimize2, RefreshCw } from 'lucide-react';

import { IconButton } from '@/components/ui/IconButton';
import { StatusDot, type StatusTone } from '@/components/ui/StatusDot';
import type { FeedStatus } from '@/features/charts/hooks/useChartData';
import type { SymbolCode, Timeframe } from '@/types/market';
import type { ConnectionState } from '@/types/realtime';

import { SymbolSelector } from './SymbolSelector';
import { TimeframeSelector } from './TimeframeSelector';

interface ChartHeaderProps {
  title: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  feed: FeedStatus;
  connection: ConnectionState;
  maximized: boolean;
  onSymbolChange: (symbol: SymbolCode) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  onReconnect: (() => void) | null;
  onToggleMaximize: () => void;
}

const FEED_LABEL: Record<FeedStatus, { tone: StatusTone; text: string }> = {
  unavailable: { tone: 'idle', text: 'لا توجد تغذية بيانات' },
  loading: { tone: 'pending', text: 'جاري التحميل' },
  live: { tone: 'ok', text: 'مباشر' },
  error: { tone: 'error', text: 'خطأ في البيانات' },
};

export function ChartHeader(props: ChartHeaderProps) {
  const feed = FEED_LABEL[props.feed];
  const reconnecting = props.connection === 'connecting';

  return (
    <header className="border-line flex h-11 shrink-0 items-center gap-2 border-b px-2.5">
      <span className="text-fg-subtle text-2xs hidden font-medium whitespace-nowrap @3xl:inline">
        {props.title}
      </span>
      <SymbolSelector value={props.symbol} onChange={props.onSymbolChange} />
      <TimeframeSelector value={props.timeframe} onChange={props.onTimeframeChange} />

      <div className="ms-auto flex items-center gap-1">
        <span
          className="text-fg-subtle text-2xs flex items-center gap-1.5 px-1.5"
          title={feed.text}
        >
          <StatusDot tone={feed.tone} />
          <span className="hidden whitespace-nowrap @2xl:inline">{feed.text}</span>
        </span>
        <IconButton
          size="sm"
          label="إعادة الاتصال"
          disabled={!props.onReconnect || reconnecting}
          onClick={() => props.onReconnect?.()}
          icon={<RefreshCw className={reconnecting ? 'size-3.5 animate-spin' : 'size-3.5'} />}
        />
        <IconButton
          size="sm"
          label={props.maximized ? 'استعادة الحجم' : 'تكبير الرسم البياني'}
          active={props.maximized}
          onClick={props.onToggleMaximize}
          icon={
            props.maximized ? (
              <Minimize2 className="size-3.5" />
            ) : (
              <Maximize2 className="size-3.5" />
            )
          }
        />
      </div>
    </header>
  );
}
