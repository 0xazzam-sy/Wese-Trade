import { LogoMark, Wordmark } from '@/components/ui/Logo';
import { AccountMenu } from '@/features/header/AccountMenu';
import { ConnectionIndicator } from '@/features/header/ConnectionIndicator';
import { HeaderClock } from '@/features/header/HeaderClock';
import { MarketFeedIndicator } from '@/features/header/MarketFeedIndicator';
import { ThemeToggle } from '@/features/header/ThemeToggle';
import { WeatherWidget } from '@/features/weather/WeatherWidget';

export function AppHeader() {
  return (
    <header className="border-line bg-elevated/80 relative z-20 flex h-14 shrink-0 items-center gap-4 border-b px-4 backdrop-blur-xl">
      <div className="flex items-center gap-2.5">
        <LogoMark className="size-8" />
        <Wordmark />
      </div>
      <ConnectionIndicator />
      <MarketFeedIndicator />

      <div className="ms-auto flex items-center gap-3">
        <HeaderClock />
        <WeatherWidget />
        <span className="bg-line h-6 w-px" aria-hidden />
        <ThemeToggle />
        <AccountMenu />
      </div>
    </header>
  );
}
