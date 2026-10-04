import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { DEFAULT_OVERLAYS, useOverlayStore } from '@/stores/overlayStore';

import { OverlayMenu } from './OverlayMenu';

afterEach(() => {
  useOverlayStore.getState().reset();
  localStorage.clear();
});

describe('OverlayMenu', () => {
  it('toggles overlays and persists the preference locally', () => {
    render(<OverlayMenu />);
    fireEvent.click(screen.getByRole('button', { name: 'طبقات التحليل' }));
    const ote = screen.getByRole('menuitemcheckbox', { name: /OTE/ });
    expect(ote).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(ote);
    expect(useOverlayStore.getState().toggles.ote).toBe(true);
    const structure = screen.getByRole('menuitemcheckbox', { name: /الهيكل/ });
    expect(structure).toHaveAttribute('aria-checked', String(DEFAULT_OVERLAYS.structure));
    fireEvent.click(structure);
    expect(useOverlayStore.getState().toggles.structure).toBe(false);
    expect(localStorage.getItem('wesetrade.overlays')).toContain('"ote":true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menuitemcheckbox', { name: /OTE/ })).toBeNull();
  });
});
