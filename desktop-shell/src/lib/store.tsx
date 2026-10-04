import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { call } from "./api";
import type { Snapshot, Page } from "./types";
interface Store {
  data?: Snapshot;
  loading: boolean;
  error: Error | null;
  page: Page;
  navigate: (page: Page) => void;
  refresh: () => Promise<void>;
  action: <T = unknown>(
    method: string,
    params?: Record<string, unknown>,
    success?: string,
  ) => Promise<T>;
}
const Context = createContext<Store | null>(null);
export function StoreProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<Page>("overview");
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["snapshot"],
    queryFn: () => call<Snapshot>("snapshot"),
    refetchInterval: 5000,
    retry: false,
  });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["snapshot"] });
  };
  const action = async <T,>(
    method: string,
    params: Record<string, unknown> = {},
    success?: string,
  ) => {
    try {
      const result = await call<T>(method, params);
      await refresh();
      if (success) toast.success(success);
      return result;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Aktion fehlgeschlagen.",
      );
      throw error;
    }
  };
  return (
    <Context.Provider
      value={{
        data: query.data,
        loading: query.isPending,
        error: query.error,
        page,
        navigate: setPage,
        refresh,
        action,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export const useCLS = () => {
  const value = useContext(Context);
  if (!value) throw new Error("CLS provider missing");
  return value;
};
