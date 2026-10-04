import { useState } from "react";
import { Activity as ActivityIcon } from "lucide-react";
import { useCLS } from "@/lib/store";
import { DataTable } from "@/components/data-table";
import {
  PageTitle,
  Badge,
  Modal,
  JsonDetails,
  useSavedState,
} from "@/components/primitives";
import type { Activity } from "@/lib/types";
import { date, clock } from "@/lib/utils";
const names: Record<string, string> = {
  created: "Aufgabe angelegt",
  status: "Status geändert",
  tool: "Tool ausgeführt",
  approved: "Aktion bestätigt",
  denied: "Aktion abgelehnt",
  plan: "Plan erstellt",
  replan: "Plan angepasst",
  error: "Fehler beobachtet",
  cancel_requested: "Abbruch angefordert",
  retry: "Erneuter Leseversuch",
  local_assessment: "Lokale Möglichkeiten geprüft",
  project_storage: "Projektwissen gespeichert",
  ai_call: "Provider angefragt",
  policy_blocked: "Policy hat Zugriff blockiert",
};
export function ActivityPage() {
  const { data } = useCLS();
  const [selected, setSelected] = useState<Activity | null>(null);
  const [kind, setKind] = useSavedState("activity-kind", "all");
  if (!data) return null;
  return (
    <>
      <PageTitle
        title="Aktivität"
        description="Jede Aktion hat eine Geschichte. Hier kannst du sie nachvollziehen."
      />
      <DataTable
        id="activity"
        data={data.activity.filter((a) => kind === "all" || a.kind === kind)}
        onRow={setSelected}
        toolbar={
          <select
            aria-label="Ereignistyp"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="all">Alle Ereignisse</option>
            {[...new Set(data.activity.map((a) => a.kind))].map((k) => (
              <option key={k} value={k}>
                {names[k] || k}
              </option>
            ))}
          </select>
        }
        columns={[
          {
            id: "event",
            header: "Ereignis",
            accessorFn: (a) => names[a.kind] || a.kind,
            enableHiding: false,
            cell: ({ getValue }) => (
              <span className="activity-label">
                <ActivityIcon size={16} />
                {String(getValue())}
              </span>
            ),
          },
          {
            id: "task",
            header: "Aufgabe",
            accessorFn: (a) =>
              data.tasks.find((t) => t.id === a.task_id)?.goal || a.task_id,
          },
          {
            id: "result",
            header: "Status / Tool",
            accessorFn: (a) => String(a.detail.status || a.detail.tool || "—"),
          },
          {
            accessorKey: "created_at",
            header: "Zeitpunkt",
            cell: ({ getValue }) =>
              `${date(String(getValue()))} · ${clock(String(getValue()))}`,
          },
        ]}
      />
      {selected && (
        <Modal
          open
          onClose={() => setSelected(null)}
          title={names[selected.kind] || selected.kind}
          description={`${selected.task_id} · ${date(selected.created_at)} ${clock(selected.created_at)}`}
          wide
        >
          <JsonDetails value={selected.detail} />
        </Modal>
      )}
    </>
  );
}
