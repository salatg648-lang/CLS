import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { StoreProvider } from "./lib/store";
import { App } from "./app";
import "./styles.css";
const client = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } },
});
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="loading-state">
        <h1>Die Ansicht konnte nicht geladen werden.</h1>
        <p>Deine Daten bleiben im lokalen Core erhalten.</p>
        <button onClick={() => location.reload()}>Oberfläche neu laden</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={client}>
        <StoreProvider>
          <App />
          <Toaster richColors position="bottom-right" closeButton />
        </StoreProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
