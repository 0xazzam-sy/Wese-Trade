import { createBrowserRouter } from 'react-router';

import { ProtectedRoute } from '@/features/auth/ProtectedRoute';
import { AppShell } from '@/layouts/AppShell';
import { BacktestsPage } from '@/pages/BacktestsPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { ForwardTestPage } from '@/pages/ForwardTestPage';
import { LoginPage } from '@/pages/LoginPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          {
            element: <ProtectedRoute roles={['admin', 'analyst']} />,
            children: [
              { path: 'backtests', element: <BacktestsPage /> },
              { path: 'forward-test', element: <ForwardTestPage /> },
            ],
          },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
