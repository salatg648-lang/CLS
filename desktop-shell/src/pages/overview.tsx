import {
  ArrowUpRight,
  ArrowRight,
  Plus,
  FolderOpen,
  BookOpen,
  CircleCheck,
  ListTodo,
  Sparkles,
  ShieldCheck,
  Cpu,
  Clock3,
  Terminal,
  ChevronRight,
  Activity as ActivityIcon,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import { Badge, Button, Empty, PageTitle } from "@/components/primitives";
import { DataTable } from "@/components/data-table";
import type { Editor } from "@/components/editors";
import type { Task } from "@/lib/types";
import { date, clock } from "@/lib/utils";
export function Overview({
  edit,
  selectTask,
}: {
  edit: (editor: Editor) => void;
  selectTask: (task: Task) => void;
}) {
  const { data, navigate } = useCLS();
  if (!data) return null;
  const activeTasks = data.tasks.filter(
    (t) => !["COMPLETED", "CANCELLED", "FAILED"].includes(t.status),
  );
  const waiting = data.tasks.filter((t) =>
    ["NEEDS_CONFIRMATION", "NEEDS_PERMISSION", "NEEDS_INFORMATION"].includes(
      t.status,
    ),
  );
  const projects = data.projects.filter((p) => p.status === "active");
  const complete = data.tasks.filter((t) => t.status === "COMPLETED").length;
  const activity = Array.from({ length: 7 }, (_, index) => {
    const d = new Date();
    d.setDate(d.getDate() - 6 + index);
    return {
      day: d.toLocaleDateString("de-DE", { weekday: "short" }),
      count: data.activity.filter(
        (a) => new Date(a.created_at).toDateString() === d.toDateString(),
      ).length,
    };
  });
  const max = Math.max(1, ...activity.map((a) => a.count));
  return (
    <>
      <PageTitle
        eyebrow="DEIN PERSÖNLICHER ARBEITSRAUM"
        title={`Guten Tag, ${data.settings.user_name}.`}
        description="Weniger suchen. Klarer arbeiten. Alles an einem Ort."
        actions={
          <>
            <Button variant="outline" onClick={() => navigate("chat")}>
              <Sparkles size={16} />
              CLS fragen
            </Button>
            <Button onClick={() => edit({ kind: "task" })}>
              <Plus size={17} />
              Neue Aufgabe
            </Button>
          </>
        }
      />
      <div className="metric-grid">
        {[
          {
            label: "Aktive Aufgaben",
            value: activeTasks.length,
            foot: waiting.length
              ? `${waiting.length} brauchen deine Aufmerksamkeit`
              : "Alles auf dem aktuellen Stand",
            icon: ListTodo,
            page: "tasks" as const,
          },
          {
            label: "Projekte",
            value: projects.length,
            foot: "Deine getrennten Arbeitsbereiche",
            icon: FolderOpen,
            page: "projects" as const,
          },
          {
            label: "Wissenseinträge",
            value: data.stats.total,
            foot: `${data.stats.documents} Dokumente als Quellen`,
            icon: BookOpen,
            page: "knowledge" as const,
          },
          {
            label: "Abgeschlossen",
            value: complete,
            foot: "Mit nachvollziehbaren Ergebnissen",
            icon: CircleCheck,
            page: "tasks" as const,
          },
        ].map((m) => (
          <button
            className="metric"
            key={m.label}
            onClick={() => navigate(m.page)}
          >
            <div>
              <span>{m.label}</span>
              <m.icon size={17} />
            </div>
            <strong>{String(m.value).padStart(2, "0")}</strong>
            <footer>
              {m.foot}
              <ArrowUpRight size={14} />
            </footer>
          </button>
        ))}
      </div>
      <div className="overview-columns">
        <div className="main-column">
          {waiting.length > 0 && (
            <div className="attention-strip">
              <span className="attention-icon">
                <ShieldCheck size={20} />
              </span>
              <div>
                <strong>Du hast das letzte Wort.</strong>
                <p>
                  {waiting.length}{" "}
                  {waiting.length === 1 ? "Aufgabe wartet" : "Aufgaben warten"}{" "}
                  auf deine Freigabe oder eine Antwort.
                </p>
              </div>
              <Button variant="ghost" onClick={() => selectTask(waiting[0])}>
                Prüfen
                <ArrowRight size={16} />
              </Button>
            </div>
          )}
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>
                  Deine Aufgaben{" "}
                  <span className="count-pill">{data.tasks.length}</span>
                </h2>
                <p>Von der Idee bis zum verifizierten Ergebnis.</p>
              </div>
              <Button variant="ghost" onClick={() => navigate("tasks")}>
                Alle ansehen
                <ArrowUpRight size={15} />
              </Button>
            </div>
            <DataTable
              id="overview-tasks"
              data={data.tasks.slice(0, 4)}
              onRow={selectTask}
              placeholder="Aufgabe finden …"
              columns={[
                {
                  accessorKey: "goal",
                  header: "Aufgabe",
                  enableHiding: false,
                  cell: ({ row }) => (
                    <div className="task-name">
                      <span
                        className={`task-icon ${row.original.status === "COMPLETED" ? "finished" : ""}`}
                      >
                        <Terminal size={15} />
                      </span>
                      <span>
                        {row.original.goal}
                        <small>
                          {data.projects.find(
                            (p) => p.id === row.original.project_id,
                          )?.name || "Ohne Projekt"}
                        </small>
                      </span>
                    </div>
                  ),
                },
                {
                  accessorKey: "status",
                  header: "Status",
                  cell: ({ getValue }) => <Badge value={String(getValue())} />,
                },
                {
                  accessorKey: "updated_at",
                  header: "Aktualisiert",
                  cell: ({ getValue }) => (
                    <span className="muted">{date(String(getValue()))}</span>
                  ),
                },
              ]}
            />
          </section>
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>Wissen, das bleibt</h2>
                <p>Deine jüngsten Erkenntnisse und Entscheidungen.</p>
              </div>
              <Button
                variant="ghost"
                onClick={() => navigate("knowledge")}
                aria-label="Wissen öffnen"
              >
                <ArrowUpRight size={18} />
              </Button>
            </div>
            <div className="knowledge-preview">
              {data.knowledge.length ? (
                data.knowledge.slice(0, 3).map((k) => (
                  <button
                    className="knowledge-mini"
                    key={k.id}
                    onClick={() => navigate("knowledge")}
                  >
                    <BookOpen size={18} />
                    <span className="topic">{k.topic || "Allgemein"}</span>
                    <h3>{k.title || k.content.slice(0, 55)}</h3>
                    <p>{k.content}</p>
                    <footer>
                      <Badge value={k.trust} />
                      <ChevronRight size={14} />
                    </footer>
                  </button>
                ))
              ) : (
                <Empty
                  title="Ein guter Gedanke verdient einen Platz"
                  description="Halte deine erste Erkenntnis fest."
                  action={
                    <Button
                      variant="outline"
                      onClick={() => edit({ kind: "knowledge" })}
                    >
                      Wissen hinzufügen
                    </Button>
                  }
                />
              )}
            </div>
          </section>
        </div>
        <aside className="side-column">
          <section className="workspace-card">
            <div className="section-heading">
              <span className="eyebrow">AKTIVER WORKSPACE</span>
              <span className="online-dot" />
            </div>
            <div className="workspace-symbol">
              <FolderOpen size={27} />
              <span>↗</span>
            </div>
            <h2>{data.activeProject?.name || "Dein erster Workspace"}</h2>
            <p>
              {data.activeProject?.description ||
                "Gib deinen Aufgaben einen sicheren Ort."}
            </p>
            <div className="workspace-path">
              <Terminal size={13} />
              <span title={data.activeProject?.path}>
                {data.activeProject?.path || "Noch nicht eingerichtet"}
              </span>
            </div>
            <Button
              variant="outline"
              onClick={() =>
                data.activeProject
                  ? navigate("projects")
                  : edit({ kind: "project" })
              }
            >
              {data.activeProject ? "Projekt öffnen" : "Workspace einrichten"}
              <ArrowUpRight size={15} />
            </Button>
          </section>
          <section className="panel activity-card">
            <div className="section-heading">
              <h2>Im Flow</h2>
              <span className="muted text-xs">Letzte 7 Tage</span>
            </div>
            <div
              className="activity-chart"
              role="img"
              aria-label={`Aktionsverlauf: ${activity.map((a) => `${a.day}: ${a.count}`).join(", ")}`}
            >
              {activity.map((a, i) => (
                <div key={i}>
                  <div className="chart-track">
                    <span
                      style={{
                        height: a.count
                          ? `${Math.max(6, (a.count / max) * 100)}%`
                          : "2px",
                      }}
                      className={i === 6 ? "current" : ""}
                    />
                  </div>
                  <small>{a.day}</small>
                </div>
              ))}
            </div>
            <footer>
              <ActivityIcon size={14} />
              <span>
                {activity.reduce((n, a) => n + a.count, 0)} dokumentierte
                Aktionen
              </span>
            </footer>
          </section>
          <section className="panel provider-summary">
            <div className="section-heading">
              <h2>Deine Verbindung</h2>
              <Cpu size={17} />
            </div>
            <div className="connection-item">
              <span className="icon-tile">
                <ShieldCheck size={18} />
              </span>
              <div>
                <strong>Lokaler CLS-Core</strong>
                <small>Verbunden · Daten bleiben bei dir</small>
              </div>
              <span className="online-dot" />
            </div>
            <p>
              {data.providers.filter((p) => p.enabled && p.available).length}{" "}
              Provider konfiguriert · Verbindung ungeprüft
            </p>
            <Button variant="ghost" onClick={() => navigate("providers")}>
              Provider verwalten
              <ArrowRight size={15} />
            </Button>
          </section>
          <div className="shortcut-hint">
            <span>
              <kbd>Strg</kbd> <kbd>K</kbd>
            </span>
            <p>Ein Befehl. Direkt am Ziel.</p>
          </div>
        </aside>
      </div>
    </>
  );
}
