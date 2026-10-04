import { useEffect } from 'react';

import { resolveWsUrl } from '@/lib/env';
import { marketFeed } from '@/services/realtime/marketFeed';
import { RealtimeClient } from '@/services/realtime/RealtimeClient';
import { useAuthStore } from '@/stores/authStore';
import { useConnectionStore } from '@/stores/connectionStore';
import { useMarketStore } from '@/stores/marketStore';

/**
 * Owns the single app-wide realtime connection while the user is authenticated.
 * Future feature hooks subscribe to typed events through the exported client accessor.
 */
let activeClient: RealtimeClient | null = null;

export function getRealtimeClient(): RealtimeClient | null {
  return activeClient;
}

export function useRealtimeConnection(): void {
  const authenticated = useAuthStore((s) => s.status === 'authenticated');

  useEffect(() => {
    if (!authenticated) return;
    const { setState, markEvent, setReconnect } = useConnectionStore.getState();

    const client = new RealtimeClient({
      url: resolveWsUrl(),
      onStateChange: setState,
      onUnauthorized: () => {
        useAuthStore.getState().sessionExpired();
      },
    });
    const unsubscribe = client.subscribe('*', (event) => {
      markEvent(event.timestamp);
    });
    const onOnline = () => {
      if (client.connectionState !== 'connected') client.reconnectNow();
    };

    activeClient = client;
    marketFeed.attach(client);
    const offStatus = marketFeed.onStatus(useMarketStore.getState().setFeed);
    setReconnect(() => {
      client.reconnectNow();
    });
    window.addEventListener('online', onOnline);
    client.connect();

    return () => {
      window.removeEventListener('online', onOnline);
      unsubscribe();
      offStatus();
      marketFeed.detach();
      useMarketStore.getState().setFeed(null);
      client.disconnect();
      if (activeClient === client) activeClient = null;
      setReconnect(null);
    };
  }, [authenticated]);
}
