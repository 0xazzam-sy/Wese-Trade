import { Moon, Sun } from 'lucide-react';

import { IconButton } from '@/components/ui/IconButton';
import { useThemeStore } from '@/stores/themeStore';

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggleTheme);
  const label = theme === 'dark' ? 'التبديل إلى الوضع الفاتح' : 'التبديل إلى الوضع الداكن';

  return (
    <IconButton
      label={label}
      onClick={toggle}
      icon={theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
    />
  );
}
