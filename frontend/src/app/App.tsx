import { QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { RouterProvider } from 'react-router';

import { onUnauthorized } from '@/lib/http';
import { useAuthStore } from '@/stores/authStore';

import { createQueryClient } from './queryClient';
import { router } from './router';

export function App() {
  const [queryClient] = useState(createQueryClient);

  useEffect(() => {
    void useAuthStore.getState().initialize();
    return onUnauthorized(() => {
      useAuthStore.getState().sessionExpired();
      queryClient.clear();
    });
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
