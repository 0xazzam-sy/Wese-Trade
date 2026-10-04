import { Maximize2, Minimize2, RefreshCw } from 'lucide-react';

import { IconButton } from '@/components/ui/IconButton';
import { OverlayMenu } from '@/features/analysis/components/OverlayMenu';
import type { MarketSymbol, SymbolCode, Timeframe } from '@/types/market';

import { ContractInfo } from './ContractInfo';
import { LiveQuote } from './LiveQuote';
import type { FeedIndicator } from '../lib/feedIndicator';
import { StreamBadge } from './StreamBadge';
import { SymbolSelector } from './SymbolSelector';
import { TimeframeSelector } from './TimeframeSelector';

interface ChartHeaderProps {
  title: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  meta: MarketSymbol | undefined;
  indicator: FeedIndicator;
  reloading: boolean;
  maximized: boolean;
  onSymbolChange: (symbol: SymbolCode) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  onReload: () => void;
  onToggleMaximize: () => void;
}

export function ChartHeader(props: ChartHeaderProps) {
  return (
    <header className="border-line flex h-11 shrink-0 items-center gap-2 border-b px-2.5">
      <span className="text-fg-subtle text-2xs hidden font-medium whitespace-nowrap @5xl:inline">
        {props.title}
      </span>
      <SymbolSelector value={props.symbol} onChange={props.onSymbolChange} />
      <TimeframeSelector value={props.timeframe} onChange={props.onTimeframeChange} />
      <div className="hidden @xl:block">
        <LiveQuote symbol={props.symbol} meta={props.meta} />
      </div>

      <div className="ms-auto flex items-center gap-1">
        <StreamBadge indicator={props.indicator} />
        <OverlayMenu />
        <ContractInfo symbol={props.symbol} />
        <IconButton
          size="sm"
          label="إعادة تحميل البيانات"
          disabled={props.reloading}
          onClick={props.onReload}
          icon={<RefreshCw className={props.reloading ? 'size-3.5 animate-spin' : 'size-3.5'} />}
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
