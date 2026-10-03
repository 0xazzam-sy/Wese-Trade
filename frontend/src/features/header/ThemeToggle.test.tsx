import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { THEME_STORAGE_KEY, useThemeStore } from '@/stores/themeStore';

import { ThemeToggle } from './ThemeToggle';

describe('ThemeToggle', () => {
  beforeEach(() => {
    useThemeStore.getState().setTheme('dark');
  });

  it('switches between dark and light, updating <html data-theme> and persisting', async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe('dark');

    await user.click(screen.getByRole('button', { name: 'التبديل إلى الوضع الفاتح' }));
    expect(useThemeStore.getState().theme).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toContain('"theme":"light"');

    await user.click(screen.getByRole('button', { name: 'التبديل إلى الوضع الداكن' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
