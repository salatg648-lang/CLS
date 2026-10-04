import { tabKeys } from "@/components/primitives";
import { useState } from "react";
import {
  Plus,
  Workflow as WorkflowIcon,
  Play,
  Pause,
  Ban,
  ArrowUpRight,
  ShieldCheck,
  MessageSquare,
  Check,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import { call } from "@/lib/api";
import {
  PageTitle,
  Badge,
  Button,
  BusyButton,
  Modal,
  Confirm,
  JsonDetails,
  Field,
  useSavedState,
} from "@/components/primitives";
import { DataTable } from "@/components/data-table";
import type { Task } from "@/lib/types";
import type { Editor } from "@/components/editors";
import { date } from "@/lib/utils";
export function Tasks({
  edit,
  selectTask,
}: {
  edit: (e: Editor) => void;
  selectTask: (t: Task) => void;
}) {
  const { data, action } = useCLS();
  const [filter, setFilter] = useSavedState("task-filter", "all");
  const [tab, setTab] = useSavedState("task-tab", "tasks");
  const [schedule, setSchedule] = useState(false);
  if (!data) return null;
  const tasks = data.tasks.filter(
    (t) =>
      filter === "all" ||
      (filter === "open"
        ? !["COMPLETED", "FAILED", "CANCELLED"].includes(t.status)
        : filter === "waiting"
          ? t.status.startsWith("NEEDS_")
          : t.status === "COMPLETED"),
  );
  return (
    <>
      <PageTitle
        title="Aufgaben"
        description="Klare Ziele. Sichere Schritte. Nachvollziehbare Ergebnisse."
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => edit({ kind: "workflow" })}
            >
              <WorkflowIcon size={16} />
              Workflow
            </Button>
            <Button onClick={() => edit({ kind: "task" })}>
              <Plus size={17} />
              Neue Aufgabe
            </Button>
          </>
        }
      />
      <div
        className="page-tabs"
        onKeyDown={tabKeys}
        role="tablist"
        aria-label="Aufgabenbereiche"
      >
        {[
          ["tasks", "Aufgaben"],
          ["workflows", "Workflows"],
          ["schedules", "Zeitpläne"],
        ].map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            key={key}
            onClick={() => setTab(key)}
          >
            {label}
            <span>
              {key === "tasks"
                ? data.tasks.length
                : key === "workflows"
                  ? data.workflows.length
                  : data.schedules.length}
            </span>
          </button>
        ))}
      </div>
      {tab === "tasks" && (
        <DataTable
          id="tasks"
          data={tasks}
          onRow={selectTask}
          placeholder="Aufgaben durchsuchen …"
          toolbar={
            <select
              aria-label="Status filtern"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">Alle Status</option>
              <option value="open">Offen</option>
              <option value="waiting">Benötigt Aufmerksamkeit</option>
              <option value="done">Abgeschlossen</option>
            </select>
          }
          columns={[
            {
              accessorKey: "goal",
              header: "Aufgabe",
              enableHiding: false,
              cell: ({ row }) => (
                <span className="table-title">
                  {row.original.goal}
                  <small>#{row.original.id.slice(0, 6)}</small>
                </span>
              ),
            },
            {
              accessorKey: "status",
              header: "Status",
              cell: ({ getValue }) => <Badge value={String(getValue())} />,
            },
            {
              id: "project",
              accessorFn: (t) =>
                data.projects.find((p) => p.id === t.project_id)?.name || "—",
              header: "Projekt",
            },
            {
              accessorKey: "updated_at",
              header: "Aktualisiert",
              cell: ({ getValue }) => date(String(getValue())),
            },
            {
              id: "progress",
              header: "Fortschritt",
              accessorFn: (t) => t.progress.percent,
              cell: ({ getValue }) => (
                <div className="progress-cell">
                  <progress max={100} value={Number(getValue())} />
                  {String(getValue())}%
                </div>
              ),
            },
          ]}
        />
      )}
      {tab === "workflows" && (
        <DataTable
          id="workflows"
          data={data.workflows}
          onRow={(w) => edit({ kind: "workflow", item: w })}
          columns={[
            { accessorKey: "name", header: "Name", enableHiding: false },
            { accessorKey: "goal", header: "Ziel" },
            { accessorKey: "version", header: "Version" },
            {
              id: "steps",
              header: "Schritte",
              accessorFn: (w) => w.steps.length,
            },
          ]}
        />
      )}
      {tab === "schedules" && (
        <>
          <div className="mb-4 flex justify-end">
            <Button variant="outline" onClick={() => setSchedule(true)}>
              <Plus size={16} />
              Zeitplan anlegen
            </Button>
          </div>
          <DataTable
            id="schedules"
            data={data.schedules}
            columns={[
              {
                id: "name",
                header: "Workflow",
                accessorFn: (s) =>
                  data.workflows.find((w) => w.id === s.workflow_id)?.name ||
                  s.workflow_id,
              },
              {
                id: "trigger",
                header: "Auslöser",
                accessorFn: (s) => s.event || `Alle ${s.interval} Sekunden`,
              },
              {
                id: "enabled",
                header: "Status",
                accessorFn: (s) => (s.enabled ? "Aktiv" : "Pausiert"),
              },
              {
                id: "action",
                header: "Aktion",
                enableHiding: false,
                cell: ({ row }) => (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void action("enable_schedule", {
                        schedule_id: row.original.id,
                        enabled: !row.original.enabled,
                      }).catch(() => {});
                    }}
                  >
                    {row.original.enabled ? "Pausieren" : "Aktivieren"}
                  </Button>
                ),
              },
            ]}
          />
        </>
      )}
      {schedule && <ScheduleDialog onClose={() => setSchedule(false)} />}
    </>
  );
}
function ScheduleDialog({ onClose }: { onClose: () => void }) {
  const { data, action } = useCLS();
  const [workflow, setWorkflow] = useState(data?.workflows[0]?.id || "");
  const [seconds, setSeconds] = useState(3600);
  const [busy, setBusy] = useState(false);
  return (
    <Modal open title="Zeitplan anlegen" onClose={onClose}>
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await action(
              "create_schedule",
              {
                workflow_id: workflow,
                project_id: data?.activeProject?.id,
                interval: seconds,
              },
              "Zeitplan angelegt",
            );
            onClose();
          } catch {
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Workflow">
          <select
            required
            value={workflow}
            onChange={(e) => setWorkflow(e.target.value)}
          >
            <option value="">Workflow wählen</option>
            {data?.workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Intervall in Sekunden">
          <input
            type="number"
            min={60}
            required
            value={seconds}
            onChange={(e) => setSeconds(Number(e.target.value))}
          />
        </Field>
        <p className="field-hint">
          Projekt:{" "}
          {data?.activeProject?.name || "Bitte zuerst ein Projekt aktivieren"}.
          Schreibende Schritte benötigen weiterhin deine Freigabe.
        </p>
        <BusyButton busy={busy} disabled={!data?.activeProject}>
          Zeitplan speichern
        </BusyButton>
      </form>
    </Modal>
  );
}
export function TaskDetail({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const { data, action } = useCLS();
  const task = data?.tasks.find((t) => t.id === id);
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<"approve" | "cancel" | null>(
    null,
  );
  const [info, setInfo] = useState("");
  if (!task) return null;
  const terminal = ["COMPLETED", "CANCELLED", "FAILED"].includes(task.status);
  const pending = task.pending;
  async function run(params: Record<string, unknown> = {}) {
    setBusy(true);
    try {
      await action("run_task", { task_id: id, ...params });
    } catch {
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title={task.goal}
      description={`Workspace: ${task.subtasks?.find((t) => t.id === task.active_subtask_id)?.root || task.root}`}
      wide
    >
      <div className="detail-meta">
        <Badge value={task.status} />
        <span className="muted">#{task.id.slice(0, 8)}</span>
        <span>{task.progress.percent}%</span>
      </div>
      {task.blocking && (
        <div className="callout warning">{task.blocking.reason}</div>
      )}
      <div className="task-steps">
        {task.plan.map((step, i) => (
          <div key={i}>
            <span>{i + 1}</span>
            <p>{step}</p>
          </div>
        ))}
      </div>
      {!terminal && (
        <div className="detail-actions">
          {pending ? (
            <Button onClick={() => setConfirmation("approve")}>
              <ShieldCheck size={16} />
              Aktion prüfen
            </Button>
          ) : (
            task.status !== "IN_PROGRESS" && (
              <BusyButton busy={busy} onClick={() => run()}>
                <Play size={16} />
                Starten / fortsetzen
              </BusyButton>
            )
          )}
          {task.status === "IN_PROGRESS" && (
            <Button
              variant="outline"
              onClick={() => {
                void action("pause_task", { task_id: id }).catch(() => {});
              }}
            >
              <Pause size={16} />
              Pausieren
            </Button>
          )}
          <Button variant="outline" onClick={() => setConfirmation("cancel")}>
            <Ban size={16} />
            Abbrechen
          </Button>
        </div>
      )}
      {!terminal && !pending && task.status !== "IN_PROGRESS" && (
        <form
          className="input-action"
          onSubmit={(e) => {
            e.preventDefault();
            if (info.trim()) {
              void run({ information: info });
              setInfo("");
            }
          }}
        >
          <input
            aria-label="Information für die Aufgabe"
            placeholder="Fehlende Information ergänzen …"
            value={info}
            onChange={(e) => setInfo(e.target.value)}
          />
          <BusyButton busy={busy} disabled={!info.trim()} type="submit">
            <MessageSquare size={16} />
            Senden
          </BusyButton>
        </form>
      )}
      {task.result && (
        <section>
          <h3>Ergebnis</h3>
          <pre className="result-text">{task.result}</pre>
        </section>
      )}
      {task.tool_results?.map((r, i) => (
        <details key={i}>
          <summary>
            {r.tool} · {r.result.ok ? "Ergebnis vorhanden" : "Fehlgeschlagen"}
          </summary>
          <JsonDetails value={r.result} />
        </details>
      ))}
      {task.project_storage?.status === "PENDING" && (
        <div className="callout">
          <p>Diese Beobachtung als Projektwissen speichern?</p>
          <div className="detail-actions">
            {[
              ["save", "Als Kandidat speichern"],
              ["experience_only", "Nur Erfahrung"],
              ["discard", "Verwerfen"],
            ].map(([decision, label]) => (
              <Button
                key={decision}
                variant="outline"
                onClick={() => {
                  void action("resolve_project_storage", {
                    task_id: id,
                    decision,
                  }).catch(() => {});
                }}
              >
                {label}
              </Button>
            ))}
          </div>
        </div>
      )}
      <Confirm
        open={confirmation === "cancel"}
        onClose={() => setConfirmation(null)}
        title="Aufgabe abbrechen?"
        onConfirm={() => action("cancel_task", { task_id: id })}
      >
        <p>
          Die laufende Aktion wird noch beendet. Weitere Schritte stoppen;
          ausgeführte Änderungen bleiben erhalten.
        </p>
      </Confirm>
      {pending && (
        <Confirm
          open={confirmation === "approve"}
          onClose={() => setConfirmation(null)}
          title={`${pending.name} freigeben?`}
          onConfirm={() =>
            action("run_task", {
              task_id: id,
              approve: true,
              confirmation_id: pending.confirmation_id,
            })
          }
        >
          <p className="muted">
            Diese Freigabe gilt nur für den gezeigten Aufruf.
          </p>
          <JsonDetails value={pending.arguments} />
          <Button
            variant="outline"
            onClick={async () => {
              try {
                await action("run_task", {
                  task_id: id,
                  approve: false,
                  confirmation_id: pending.confirmation_id,
                });
                setConfirmation(null);
              } catch {}
            }}
          >
            Aktion ablehnen
          </Button>
        </Confirm>
      )}
    </Modal>
  );
}
