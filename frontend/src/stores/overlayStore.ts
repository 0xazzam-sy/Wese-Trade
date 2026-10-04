import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type OverlayKey =
  | 'structure'
  | 'liquidity'
  | 'fvg'
  | 'orderBlocks'
  | 'premiumDiscount'
  | 'ote'
  | 'signals'
  | 'tradePlan';

export type OverlayToggles = Record<OverlayKey, boolean>;

/** Readable by default: zones that overlap a lot (premium/discount, OTE) start hidden. */
export const DEFAULT_OVERLAYS: OverlayToggles = {
  structure: true,
  liquidity: true,
  fvg: true,
  orderBlocks: true,
  premiumDiscount: false,
  ote: false,
  signals: true,
  tradePlan: true,
};

export const OVERLAY_LABELS: { key: OverlayKey; label: string }[] = [
  { key: 'structure', label: 'الهيكل' },
  { key: 'liquidity', label: 'السيولة' },
  { key: 'fvg', label: 'FVG' },
  { key: 'orderBlocks', label: 'Order Blocks' },
  { key: 'premiumDiscount', label: 'Premium/Discount' },
  { key: 'ote', label: 'OTE' },
  { key: 'signals', label: 'علامات الإشارات' },
  { key: 'tradePlan', label: 'خطة الصفقة' },
];

interface OverlayState {
  toggles: OverlayToggles;
  toggle: (key: OverlayKey) => void;
  reset: () => void;
}

export const useOverlayStore = create<OverlayState>()(
  persist(
    (set) => ({
      toggles: DEFAULT_OVERLAYS,
      toggle: (key) => {
        set((s) => ({ toggles: { ...s.toggles, [key]: !s.toggles[key] } }));
      },
      reset: () => {
        set({ toggles: DEFAULT_OVERLAYS });
      },
    }),
    {
      name: 'wesetrade.overlays',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      merge: (persisted, current) => ({
        ...current,
        toggles: { ...DEFAULT_OVERLAYS, ...(persisted as Partial<OverlayState>).toggles },
      }),
    },
  ),
);
