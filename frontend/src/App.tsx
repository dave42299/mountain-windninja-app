import { lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router";
import { Toaster } from "@/components/ui/sonner";
import ErrorBoundary from "@/components/ErrorBoundary";
import AppLayout from "@/layouts/AppLayout";
import NotFoundPage from "@/pages/NotFoundPage";

const MapPage = lazy(() => import("@/pages/MapPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const ForecastDetailPage = lazy(() => import("@/pages/ForecastDetailPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
    },
  },
});

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-muted-foreground">Loading...</p>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/" element={<MapPage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/forecasts/:id" element={<ForecastDetailPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
        <Toaster />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
