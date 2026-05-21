import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router";
import { Toaster } from "@/components/ui/sonner";
import AppLayout from "@/layouts/AppLayout";
import MapPage from "@/pages/MapPage";
import DashboardPage from "@/pages/DashboardPage";
import ForecastDetailPage from "@/pages/ForecastDetailPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<MapPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/forecasts/:id" element={<ForecastDetailPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster />
    </QueryClientProvider>
  );
}
