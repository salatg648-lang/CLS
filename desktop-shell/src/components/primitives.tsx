import { type ReactNode, useState, useEffect } from "react";
import {
  Loader2,
  X,
  CircleCheck,
  CircleDashed,
  CirclePause,
  AlertCircle,
  Ban,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";
export { Button };
export const labels: Record<string, string> = {
  CREATED: "Offen",
  IN_PROGRESS: "In Arbeit",
  COMPLETED: "Abgeschlossen",
  NEEDS_CONFIRMATION: "Freigabe nötig",
  NEEDS_INFORMATION: "Rückfrage",
  NEEDS_PERMISSION: "Berechtigung nötig",
  WAITING_FOR_USER: "Wartet auf dich",
  BLOCKED: "Blockiert",
  PAUSED: "Pausiert",
  FAILED: "Fehlgeschlagen",
  CANCELLED: "Abgebrochen",
  CONFIRMED: "Bestätigt",
  SUPPORTED: "Gesichert",
  CANDIDATE: "Kandidat",
  UNCERTAIN: "Ungeprüft",
  OUTDATED: "Veraltet",
  CONFLICTING: "Widerspruch",
  LOCAL_ONLY: "Nur lokal",
  SAFE_FOR_EXTERNAL: "Extern erlaubt",
  USER_CONFIRMATION_REQUIRED: "Nachfragen",
  active: "Aktiv",
  archived: "Archiviert",
};
export function Badge({ value }: { value: string }) {
  const success = ["COMPLETED", "CONFIRMED", "SUPPORTED", "active"].includes(
    value,
  );
  const warning = [
    "NEEDS_CONFIRMATION",
    "NEEDS_INFORMATION",
    "WAITING_FOR_USER",
    "CANDIDATE",
    "UNCERTAIN",
  ].includes(value);
  const danger = [
    "FAILED",
    "BLOCKED",
    "CONFLICTING",
    "NEEDS_PERMISSION",
  ].includes(value);
  const Icon = success
    ? CircleCheck
    : warning || danger
      ? AlertCircle
      : value === "PAUSED"
        ? CirclePause
        : value === "CANCELLED"
          ? Ban
          : CircleDashed;
  return (
    <span
      className={cn(
        "badge",
        success && "badge-success",
        warning && "badge-warning",
        danger && "badge-danger",
      )}
    >
      <Icon size={12} />
      {labels[value] || value}
    </span>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="heading-actions">{actions}</div>
    </div>
  );
}
export function Empty({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <CircleDashed size={24} />}</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <DialogContent
        className={cn("max-h-[88vh] overflow-y-auto", wide && "sm:max-w-3xl")}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description ||
              "Änderungen werden über den bestehenden CLS-Core verarbeitet."}
          </DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="field">
      <label>
        <span>{label}</span>
        {children}
      </label>
      {hint && <small>{hint}</small>}
    </div>
  );
}
export function BusyButton({
  busy,
  children,
  ...props
}: React.ComponentProps<typeof Button> & { busy?: boolean }) {
  return (
    <Button {...props} disabled={busy || props.disabled}>
      {busy && <Loader2 size={16} className="animate-spin" />}
      {children}
    </Button>
  );
}
export function JsonDetails({ value }: { value: unknown }) {
  return <pre className="json-details">{JSON.stringify(value, null, 2)}</pre>;
}
export function Confirm({
  open,
  onClose,
  onConfirm,
  title,
  children,
  danger = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<unknown>;
  title: string;
  children: ReactNode;
  danger?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title={title}
      description="Bitte prüfe die konkrete Aktion, bevor du bestätigst."
    >
      {children}
      <div className="dialog-actions">
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Zurück
        </Button>
        <BusyButton
          busy={busy}
          variant={danger ? "destructive" : "default"}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } catch {
            } finally {
              setBusy(false);
            }
          }}
        >
          Bestätigen
        </BusyButton>
      </div>
    </Modal>
  );
}
export function useSavedState<T>(
  key: string,
  fallback: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    try {
      const item = localStorage.getItem("cls:" + key);
      return item ? JSON.parse(item) : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    localStorage.setItem("cls:" + key, JSON.stringify(state));
  }, [key, state]);
  return [state, setState];
}

/** Roving focus for the local page tabs; no global shortcut captures typing. */
export function tabKeys(event: React.KeyboardEvent<HTMLDivElement>) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  );
  const current = tabs.indexOf(document.activeElement as HTMLButtonElement);
  if (current < 0) return;
  event.preventDefault();
  const index =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  tabs[index]?.focus();
  tabs[index]?.click();
}
