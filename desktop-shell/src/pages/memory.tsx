import { tabKeys } from "@/components/primitives";
import { useState } from "react";
import { Plus, Brain, Pencil, Trash2, ShieldCheck } from "lucide-react";
import { useCLS } from "@/lib/store";
import { DataTable } from "@/components/data-table";
import {
  PageTitle,
  Button,
  Badge,
  Modal,
  Confirm,
  Field,
  JsonDetails,
  useSavedState,
  BusyButton,
} from "@/components/primitives";
import type { Editor } from "@/components/editors";
import type { Memory as Fact, Experience } from "@/lib/types";
import { date } from "@/lib/utils";
export function MemoryPage({ edit }: { edit: (e: Editor) => void }) {
  const { data, action } = useCLS();
  const [tab, setTab] = useSavedState("memory-tab", "personal");
  const [fact, setFact] = useState<Fact | null>(null);
  const [experience, setExperience] = useState<Experience | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [strategy, setStrategy] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const current = fact ? data.memory.find((m) => m.id === fact.id) : null;
  return (
    <>
      <PageTitle
        title="Memory"
        description="Was CLS über dich weiß. Und was aus deinen Aufgaben bleibt."
        actions={
          <Button onClick={() => edit({ kind: "memory" })}>
            <Plus size={17} />
            Information vorschlagen
          </Button>
        }
      />
      <div
        className="page-tabs"
        onKeyDown={tabKeys}
        role="tablist"
        aria-label="Memory-Bereiche"
      >
        <button
          role="tab"
          aria-selected={tab === "personal"}
          onClick={() => setTab("personal")}
        >
          Persönliche Informationen<span>{data.memory.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "experience"}
          onClick={() => setTab("experience")}
        >
          Erfahrungen<span>{data.experiences.length}</span>
        </button>
      </div>
      {tab === "personal" ? (
        <>
          <div className="info-banner">
            <Brain size={19} />
            <p>
              Du entscheidest, was bleibt. Neue Vorschläge sind ungeprüfte
              Kandidaten.
            </p>
          </div>
          <DataTable
            id="memory"
            data={data.memory}
            onRow={setFact}
            columns={[
              {
                accessorKey: "content",
                header: "Information",
                enableHiding: false,
              },
              { accessorKey: "category", header: "Kategorie" },
              {
                accessorKey: "trust",
                header: "Status",
                cell: ({ getValue }) => <Badge value={String(getValue())} />,
              },
              {
                accessorKey: "privacy",
                header: "Datenschutz",
                cell: ({ getValue }) => <Badge value={String(getValue())} />,
              },
            ]}
          />
        </>
      ) : (
        <DataTable
          id="experiences"
          data={data.experiences}
          onRow={setExperience}
          columns={[
            { accessorKey: "goal", header: "Aufgabe", enableHiding: false },
            {
              id: "status",
              header: "Ergebnis",
              accessorFn: (e) => e.summary.status,
              cell: ({ getValue }) => <Badge value={String(getValue())} />,
            },
            {
              id: "project",
              header: "Projekt",
              accessorFn: (e) =>
                data.projects.find((p) => p.id === e.project_id)?.name ||
                "Global",
            },
            {
              accessorKey: "created_at",
              header: "Erstellt",
              cell: ({ getValue }) => date(String(getValue())),
            },
          ]}
        />
      )}
      {current && (
        <Modal
          open
          onClose={() => setFact(null)}
          title="Persönliche Information"
        >
          <pre className="result-text">{current.content}</pre>
          <Badge value={current.trust} />
          <Field label="Datenschutz">
            <select
              value={current.privacy}
              onChange={(e) => {
                void action("set_memory_privacy", {
                  fact_id: current.id,
                  level: e.target.value,
                }).catch(() => {});
              }}
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
          <div className="detail-actions">
            <Button
              variant="outline"
              onClick={() => {
                edit({ kind: "memory", item: current });
                setFact(null);
              }}
            >
              <Pencil size={16} />
              Bearbeiten
            </Button>
            {current.trust === "CANDIDATE" && (
              <Button
                onClick={() => {
                  void action(
                    "confirm_memory",
                    { fact_id: current.id },
                    "Information bestätigt",
                  ).catch(() => {});
                }}
              >
                <ShieldCheck size={16} />
                Bestätigen
              </Button>
            )}
            <Button
              variant="ghost"
              className="text-destructive"
              onClick={() => setDeleting(true)}
            >
              <Trash2 size={16} />
              Löschen
            </Button>
          </div>
          <Confirm
            open={deleting}
            onClose={() => setDeleting(false)}
            title="Information vergessen?"
            danger
            onConfirm={async () => {
              await action("delete_memory", { fact_id: current.id });
              setFact(null);
            }}
          >
            <p>{current.content}</p>
          </Confirm>
        </Modal>
      )}
      {experience && (
        <Modal
          open
          onClose={() => setExperience(null)}
          title={experience.goal}
          description="Beobachtete Ergebnisse aus dem tatsächlichen Aktionsverlauf."
          wide
        >
          <Badge value={experience.summary.status} />
          <pre className="result-text">
            {String(experience.summary.result || "")}
          </pre>
          <details>
            <summary>Timeline, Prüfbelege & Provenance</summary>
            <JsonDetails value={experience.summary} />
          </details>
          <p className="field-hint">
            Eine Erfahrung ist kein Beweis für eine allgemeine Regel.
            Projektgrenzen und Privacy gelten weiterhin.
          </p>
          <div className="detail-actions">
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const updated = await action<Experience>(
                    "set_experience_reference",
                    {
                      task_id: experience.task_id,
                      allowed: !experience.summary.reference_allowed,
                    },
                  );
                  setExperience(updated);
                } catch {}
              }}
            >
              {experience.summary.reference_allowed
                ? "Referenzfreigabe zurücknehmen"
                : "Als Referenz freigeben"}
            </Button>
            <Button onClick={() => setStrategy(true)}>
              Strategiekandidat vorschlagen
            </Button>
          </div>
        </Modal>
      )}
      {strategy && experience && (
        <Modal
          open
          onClose={() => setStrategy(false)}
          title="Strategiekandidat"
          description="Bleibt CANDIDATE. Keine automatische Verifikation oder Anwendung."
        >
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              setBusy(true);
              try {
                await action(
                  "propose_strategy",
                  {
                    content: form.get("content"),
                    applicability: form.get("applicability"),
                    rationale: form.get("rationale"),
                    experience_ids: [experience.task_id],
                  },
                  "Strategiekandidat im Wissen angelegt",
                );
                setStrategy(false);
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Mögliche Vorgehensweise">
              <textarea name="content" required />
            </Field>
            <Field label="Wann könnte sie passen?">
              <input name="applicability" required />
            </Field>
            <Field label="Begründung aus dieser Erfahrung">
              <textarea name="rationale" required />
            </Field>
            <BusyButton busy={busy}>Als Kandidat speichern</BusyButton>
          </form>
        </Modal>
      )}
    </>
  );
}
