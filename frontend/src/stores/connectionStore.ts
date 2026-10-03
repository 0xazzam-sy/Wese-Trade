import { create } from 'zustand';

import type { ConnectionState } from '@/types/realtime';

interface ConnectionStoreState {
  state: ConnectionState;
  lastEventAt: string | null;
  /** Set by the realtime hook; lets UI controls request an immediate reconnect. */
  reconnect: (() => void) | null;
  setState: (state: ConnectionState) => void;
  markEvent: (timestamp: string) => void;
  setReconnect: (reconnect: (() => void) | null) => void;
}

export const useConnectionStore = create<ConnectionStoreState>()((set) => ({
  state: 'disconnected',
  lastEventAt: null,
  reconnect: null,
  setState: (state) => {
    set({ state });
  },
  markEvent: (lastEventAt) => {
    set({ lastEventAt });
  },
  setReconnect: (reconnect) => {
    set({ reconnect });
  },
}));
