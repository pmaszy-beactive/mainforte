import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { router } from "./router";
import { startSender } from "@/lib/sender";
import { startPushRegistration } from "@/lib/push";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

export function App() {
  useEffect(() => startSender(), []);
  useEffect(() => startPushRegistration(), []);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
