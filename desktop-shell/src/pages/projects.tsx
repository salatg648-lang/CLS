import { useState } from "react";
import {
  Folder,
  FolderOpen,
  Plus,
  ArrowUpRight,
  MoreHorizontal,
  Pencil,
  Archive,
  Trash2,
  Check,
  LayoutGrid,
  List,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import {
  PageTitle,
  Button,
  Badge,
  Empty,
  Field,
  Modal,
  Confirm,
  useSavedState,
} from "@/components/primitives";
import { DataTable } from "@/components/data-table";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import type { Editor } from "@/components/editors";
import type { Project } from "@/lib/types";
import { date } from "@/lib/utils";
export function Projects({ edit }: { edit: (e: Editor) => void }) {
  const { data, action } = useCLS();
  const [query, setQuery] = useSavedState("projects-search", "");
  const [layout, setLayout] = useSavedState("projects-layout", "grid");
  const [archived, setArchived] = useState(false);
  const [selected, setSelected] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  if (!data) return null;
  const projects = data.projects.filter(
    (p) =>
      (archived || p.status === "active") &&
      (p.name + " " + p.description)
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const menu = (p: Project) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          aria-label={`Aktionen für ${p.name}`}
        >
          <MoreHorizontal size={19} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => edit({ kind: "project", item: p })}>
          <Pencil />
          Bearbeiten
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            void action(
              p.status === "active" ? "archive_project" : "unarchive_project",
              { project_id: p.id },
            ).catch(() => {});
          }}
        >
          <Archive />
          {p.status === "active" ? "Archivieren" : "Wieder aktivieren"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="text-destructive"
          onClick={() => setDeleting(p)}
        >
          <Trash2 />
          Projekt löschen
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
  return (
    <>
      <PageTitle
        title="Projekte"
        description="Eigene Workspaces. Passender Kontext. Klare Grenzen."
        actions={
          <Button onClick={() => edit({ kind: "project" })}>
            <Plus size={17} />
            Neues Projekt
          </Button>
        }
      />
      <div className="projects-toolbar">
        <input
          aria-label="Projekte suchen"
          placeholder="Projekt suchen …"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="check-field">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          Archivierte anzeigen
        </label>
        <div className="view-toggle">
          <Button
            aria-label="Kartenansicht"
            variant={layout === "grid" ? "secondary" : "ghost"}
            size="icon"
            onClick={() => setLayout("grid")}
          >
            <LayoutGrid size={17} />
          </Button>
          <Button
            aria-label="Tabellenansicht"
            variant={layout === "table" ? "secondary" : "ghost"}
            size="icon"
            onClick={() => setLayout("table")}
          >
            <List size={17} />
          </Button>
        </div>
      </div>
      {layout === "table" ? (
        <DataTable
          id="projects"
          data={projects}
          onRow={setSelected}
          columns={[
            { accessorKey: "name", header: "Projekt", enableHiding: false },
            { accessorKey: "path", header: "Workspace" },
            {
              accessorKey: "status",
              header: "Status",
              cell: ({ getValue }) => <Badge value={String(getValue())} />,
            },
            {
              accessorKey: "updated_at",
              header: "Aktualisiert",
              cell: ({ getValue }) => date(String(getValue())),
            },
          ]}
        />
      ) : (
        <div className="project-grid">
          {projects.map((p, i) => (
            <article
              key={p.id}
              className={`project-card ${data.activeProject?.id === p.id ? "is-active" : ""}`}
            >
              <header>
                <span className={`project-avatar color-${i % 3}`}>
                  <FolderOpen size={22} />
                </span>
                {menu(p)}
              </header>
              <button className="project-title" onClick={() => setSelected(p)}>
                {p.name}
                <ArrowUpRight size={17} />
              </button>
              <p>
                {p.description ||
                  "Ein eigener Ort für Aufgaben, Wissen und Erfahrungen."}
              </p>
              <div className="project-facts">
                <span>
                  {data.tasks.filter((t) => t.project_id === p.id).length}{" "}
                  Aufgaben
                </span>
                <span>
                  {data.knowledge.filter((k) => k.project_id === p.id).length}{" "}
                  Erkenntnisse
                </span>
              </div>
              <footer>
                {data.activeProject?.id === p.id ? (
                  <span className="active-project">
                    <Check size={14} />
                    Aktives Projekt
                  </span>
                ) : (
                  <Button
                    variant="ghost"
                    disabled={p.status !== "active"}
                    onClick={() => {
                      void action(
                        "set_active_project",
                        { project_id: p.id },
                        "Projekt gewechselt",
                      ).catch(() => {});
                    }}
                  >
                    Aktivieren
                    <ArrowUpRight size={15} />
                  </Button>
                )}
                <Badge value={p.status} />
              </footer>
            </article>
          ))}
          <button
            className="new-project-card"
            onClick={() => edit({ kind: "project" })}
          >
            <span>
              <Plus size={25} />
            </span>
            <strong>Raum für etwas Neues</strong>
            <p>Lege dein nächstes Projekt an.</p>
          </button>
        </div>
      )}
      {selected && (
        <Modal
          open
          onClose={() => setSelected(null)}
          title={selected.name}
          description={
            selected.description || "Projektkontext und Einstellungen"
          }
        >
          <Field label="Workspace">
            <code className="path-label">
              {selected.path || "Noch nicht konfiguriert"}
            </code>
          </Field>
          <Field label="Projektwissen speichern">
            <select
              value={
                data.projects.find((p) => p.id === selected.id)?.memory_mode ||
                "ASK"
              }
              onChange={(e) => {
                void action("set_project_memory_mode", {
                  project_id: selected.id,
                  mode: e.target.value,
                }).catch(() => {});
              }}
            >
              <option value="NEVER">Nie automatisch speichern</option>
              <option value="ASK">Vorher nachfragen</option>
              <option value="AUTO">
                Automatisch nach Memory-/Privacy-Regeln
              </option>
            </select>
          </Field>
          {selected.instructions && (
            <pre className="result-text">{selected.instructions}</pre>
          )}
          <div className="dialog-actions">
            <Button
              variant="outline"
              onClick={() => {
                edit({ kind: "project", item: selected });
                setSelected(null);
              }}
            >
              Bearbeiten
            </Button>
            <Button
              disabled={selected.status !== "active"}
              onClick={async () => {
                try {
                  await action("set_active_project", {
                    project_id: selected.id,
                  });
                  setSelected(null);
                } catch {}
              }}
            >
              Projekt aktivieren
            </Button>
          </div>
        </Modal>
      )}
      <Confirm
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title="Projekt löschen?"
        danger
        onConfirm={() =>
          action(
            "delete_project",
            { project_id: deleting?.id, delete_knowledge: false },
            "Projekt gelöscht",
          )
        }
      >
        <p>
          „{deleting?.name}“ wird aus CLS entfernt. Workspace-Dateien werden
          nicht gelöscht. Wissenseinträge bleiben nach den bestehenden
          Scope-Regeln erhalten.
        </p>
      </Confirm>
    </>
  );
}
