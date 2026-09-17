import React from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { RouterProvider } from '@tanstack/react-router';
import { queryClient } from '@/queries/queryClient';
import { router } from '@/routes/router';

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      {/* TanStack Router 주입 */}
      <RouterProvider router={router} />
      {/* TanStack Query Devtools */}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
};

export default App;
