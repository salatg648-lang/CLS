declare global {
  interface Window {
    cls?: {
      call: <T = unknown>(
        method: string,
        params?: Record<string, unknown>,
      ) => Promise<T>;
      choosePath: (kind: "directory" | "document") => Promise<string | null>;
      window: (action: "close" | "minimize" | "maximize") => Promise<void>;
      platform: string;
    };
  }
}
export async function call<T = unknown>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  if (window.cls) return window.cls.call<T>(method, params);
  const response = await fetch("/__cls", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CLS-Client": "preview" },
    body: JSON.stringify({ method, params }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error)
    throw new Error(payload.error || "CLS ist nicht erreichbar.");
  return payload.result as T;
}
export async function choosePath(kind: "directory" | "document") {
  if (!window.cls)
    throw new Error(
      "Die native Dateiauswahl ist in der installierten Desktop-App verfügbar. Einen Pfad kannst du auch direkt eingeben.",
    );
  return window.cls.choosePath(kind);
}
