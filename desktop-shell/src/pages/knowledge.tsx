import { tabKeys } from "@/components/primitives";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Plus,
  Upload,
  BookOpen,
  ShieldCheck,
  Trash2,
  Pencil,
  FileText,
} from "lucide-react";
import { call, choosePath } from "@/lib/api";
import { useCLS } from "@/lib/store";
import { DataTable } from "@/components/data-table";
import {
  PageTitle,
  Button,
  Badge,
  Field,
  Modal,
  Confirm,
  JsonDetails,
  BusyButton,
  useSavedState,
} from "@/components/primitives";
import type { Knowledge as Entry } from "@/lib/types";
import type { Editor } from "@/components/editors";
import { date } from "@/lib/utils";
import { toast } from "sonner";
export function KnowledgePage({
  edit,
  selectEntry,
}: {
  edit: (e: Editor) => void;
  selectEntry: (id: number) => void;
}) {
  const { data, action } = useCLS();
  const [trust, setTrust] = useSavedState("knowledge-trust", "all");
  const [tab, setTab] = useSavedState("knowledge-tab", "entries");
  const [importing, setImporting] = useState(false);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const entries = data.knowledge.filter(
    (k) => trust === "all" || k.trust === trust,
  );
  return (
    <>
      <PageTitle
        title="Wissen"
        description="Erkenntnisse mit Herkunft, Kontext und klarer Vertrauensbasis."
        actions={
          <>
            <Button variant="outline" onClick={() => setImporting(true)}>
              <Upload size={16} />
              Importieren
            </Button>
            <Button onClick={() => edit({ kind: "knowledge" })}>
              <Plus size={17} />
              Wissen hinzufügen
            </Button>
          </>
        }
      />
      <div
        className="page-tabs"
        onKeyDown={tabKeys}
        role="tablist"
        aria-label="Wissensbereiche"
      >
        {[
          ["entries", "Einträge", data.knowledge.length],
          ["documents", "Dokumente", data.documents.length],
          ["conflicts", "Widersprüche", data.conflicts.length],
        ].map(([key, label, count]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(String(key))}
          >
            {label}
            <span>{count}</span>
          </button>
        ))}
      </div>
      {tab === "entries" && (
        <DataTable
          id="knowledge"
          data={entries}
          onRow={(k) => selectEntry(k.id)}
          placeholder="Wissen durchsuchen …"
          toolbar={
            <select
              aria-label="Vertrauen filtern"
              value={trust}
              onChange={(e) => setTrust(e.target.value)}
            >
              <option value="all">Alle Vertrauensstufen</option>
              {[
                "CONFIRMED",
                "SUPPORTED",
                "CANDIDATE",
                "UNCERTAIN",
                "CONFLICTING",
                "OUTDATED",
              ].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          }
          columns={[
            {
              id: "title",
              accessorFn: (k) => k.title || k.content,
              header: "Erkenntnis",
              enableHiding: false,
              cell: ({ row }) => (
                <span className="table-title">
                  {row.original.title || row.original.content.slice(0, 80)}
                  <small>
                    {row.original.topic || "Allgemein"} ·{" "}
                    {row.original.kind === "strategy"
                      ? "Strategiekandidat"
                      : row.original.kind}
                  </small>
                </span>
              ),
            },
            {
              accessorKey: "trust",
              header: "Vertrauen",
              cell: ({ getValue }) => <Badge value={String(getValue())} />,
            },
            {
              id: "scope",
              header: "Geltungsbereich",
              accessorFn: (k) =>
                data.projects.find((p) => p.id === k.project_id)?.name ||
                (k.project_id ? "Projekt" : "Global"),
            },
            {
              accessorKey: "updated_at",
              header: "Aktualisiert",
              cell: ({ getValue }) => date(String(getValue())),
            },
          ]}
        />
      )}
      {tab === "documents" && (
        <DataTable
          id="documents"
          data={data.documents}
          columns={[
            { accessorKey: "filename", header: "Dokument" },
            { accessorKey: "chunk_count", header: "Abschnitte" },
            {
              accessorKey: "ingested_at",
              header: "Importiert",
              cell: ({ getValue }) => date(String(getValue())),
            },
            {
              id: "action",
              header: "Aktion",
              cell: ({ row }) => (
                <DeleteDocument
                  id={row.original.id}
                  name={row.original.filename}
                />
              ),
            },
          ]}
        />
      )}
      {tab === "conflicts" && (
        <div className="form-stack">
          {!data.conflicts.length && (
            <div className="callout">
              <ShieldCheck size={20} />
              Keine offenen Widersprüche.
            </div>
          )}
          {data.conflicts.map((c) => (
            <section key={c.id} className="panel p-6">
              <h3>Widerspruch #{c.id}</h3>
              <div className="form-grid">
                {[c.entry_a, c.entry_b].map((id) => (
                  <div className="callout" key={id}>
                    <strong>#{id}</strong>
                    <p>
                      {data.knowledge.find((k) => k.id === id)?.content ||
                        "Eintrag nicht in dieser Liste"}
                    </p>
                  </div>
                ))}
              </div>
              <p>{c.reason}</p>
              <div className="detail-actions">
                {[
                  ["keep_a", "A behalten"],
                  ["keep_b", "B behalten"],
                  ["both_valid", "Beide gelten"],
                ].map(([resolution, label]) => (
                  <Button
                    variant="outline"
                    key={resolution}
                    onClick={() => {
                      void action(
                        "resolve_conflict",
                        { conflict_id: c.id, resolution },
                        "Widerspruch bearbeitet",
                      ).catch(() => {});
                    }}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      <Modal
        open={importing}
        onClose={() => {
          if (!busy) setImporting(false);
        }}
        title="Dokument importieren"
        description="CLS übernimmt eine Kopie als Wissensquelle im aktiven Projekt."
      >
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await action(
                "ingest_document",
                { path, project_id: data.activeProject?.id || null },
                "Dokument importiert",
              );
              setImporting(false);
              setPath("");
            } catch {
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Dateipfad">
            <div className="input-action">
              <input
                required
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="Absoluter Pfad zu PDF, Text oder DOCX"
              />
              <Button
                type="button"
                variant="outline"
                aria-label="Dokument auswählen"
                onClick={async () => {
                  try {
                    const value = await choosePath("document");
                    if (value) setPath(value);
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
              >
                <FileText size={17} />
              </Button>
            </div>
          </Field>
          <BusyButton busy={busy}>Importieren</BusyButton>
        </form>
      </Modal>
    </>
  );
}
function DeleteDocument({ id, name }: { id: number; name: string }) {
  const { action } = useCLS();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        aria-label={`${name} entfernen`}
        onClick={() => setOpen(true)}
      >
        <Trash2 size={16} />
      </Button>
      <Confirm
        title="Importiertes Dokument entfernen?"
        open={open}
        onClose={() => setOpen(false)}
        danger
        onConfirm={() => action("delete_document", { doc_id: id })}
      >
        <p>
          {name}: Die importierte Kopie und zugehörige Wissensabschnitte werden
          entfernt.
        </p>
      </Confirm>
    </>
  );
}
export function KnowledgeDetail({
  id,
  onClose,
  edit,
}: {
  id: number;
  onClose: () => void;
  edit: (e: Editor) => void;
}) {
  const { action } = useCLS();
  const [deleting, setDeleting] = useState(false);
  const query = useQuery({
    queryKey: ["knowledge", id],
    queryFn: () => call<Entry>("get_knowledge_entry", { entry_id: id }),
  });
  const privacy = useQuery({
    queryKey: ["knowledge-privacy", id],
    queryFn: () => call<string>("get_knowledge_privacy", { entry_id: id }),
  });
  const entry = query.data;
  const run = async (method: string, params: Record<string, unknown>) => {
    try {
      await action(method, params);
      await query.refetch();
      await privacy.refetch();
    } catch {}
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={entry?.title || "Wissenseintrag"}
      description="Herkunft, Geltungsbereich und Versionen bleiben nachvollziehbar."
      wide
    >
      {query.isPending ? (
        <p role="status">Eintrag wird geladen …</p>
      ) : query.error ? (
        <p role="alert">{query.error.message}</p>
      ) : (
        entry && (
          <>
            <div className="detail-meta">
              <Badge value={entry.trust} />
              <span>
                {entry.kind === "strategy"
                  ? "Strategiekandidat · keine ausführbare Regel"
                  : entry.topic}
              </span>
            </div>
            <pre className="result-text">{entry.content}</pre>
            {entry.kind === "strategy" ? (
              <div className="callout warning">
                Dieser Kandidat wird nicht automatisch angewendet, verifiziert
                oder globalisiert.
                <JsonDetails value={entry.strategy} />
              </div>
            ) : (
              <div className="detail-actions">
                <Button
                  variant="outline"
                  onClick={() => {
                    edit({ kind: "knowledge", item: entry });
                    onClose();
                  }}
                >
                  <Pencil size={16} />
                  Bearbeiten
                </Button>
                <Button
                  onClick={() => run("confirm_knowledge", { entry_id: id })}
                >
                  <ShieldCheck size={16} />
                  Bestätigen
                </Button>
                <Button
                  variant="outline"
                  onClick={() =>
                    run("mark_knowledge_outdated", { entry_id: id })
                  }
                >
                  Als veraltet markieren
                </Button>
              </div>
            )}
            <Field label="Datenschutz">
              <select
                value={privacy.data || "LOCAL_ONLY"}
                onChange={(e) =>
                  run("set_knowledge_privacy", {
                    entry_id: id,
                    level: e.target.value,
                  })
                }
              >
                {[
                  "LOCAL_ONLY",
                  "SAFE_FOR_EXTERNAL",
                  "USER_CONFIRMATION_REQUIRED",
                  "BLOCKED",
                ].map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </Field>
            <details>
              <summary>Quellen & Provenance</summary>
              <JsonDetails value={entry.sources} />
            </details>
            <details>
              <summary>Versionsverlauf</summary>
              <JsonDetails value={entry.versions} />
            </details>
            <Button
              variant="ghost"
              className="text-destructive justify-start"
              onClick={() => setDeleting(true)}
            >
              <Trash2 size={16} />
              Eintrag löschen
            </Button>
            <Confirm
              open={deleting}
              onClose={() => setDeleting(false)}
              title="Wissenseintrag löschen?"
              danger
              onConfirm={async () => {
                await action("delete_knowledge", { entry_id: id });
                onClose();
              }}
            >
              <p>{entry.title || entry.content.slice(0, 100)}</p>
            </Confirm>
          </>
        )
      )}
    </Modal>
  );
}
