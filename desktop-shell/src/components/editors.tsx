import { useState } from "react";
import { FolderOpen, Plus, X } from "lucide-react";
import { useCLS } from "@/lib/store";
import { choosePath } from "@/lib/api";
import type {
  Project,
  Task,
  Knowledge,
  Memory,
  Provider,
  Workflow,
} from "@/lib/types";
import { Button, BusyButton, Field, Modal } from "./primitives";
import { toast } from "sonner";

export type Editor =
  | { kind: "task" }
  | { kind: "project"; item?: Project }
  | { kind: "knowledge"; item?: Knowledge }
  | { kind: "memory"; item?: Memory }
  | { kind: "provider"; item: Provider }
  | { kind: "workflow"; item?: Workflow };
const capabilities = [
  "general_reasoning",
  "research",
  "web_search",
  "coding",
  "local_reasoning",
];
export function EditorDialog({
  editor,
  onClose,
}: {
  editor: Editor;
  onClose: () => void;
}) {
  const { action, data } = useCLS();
  const item = "item" in editor ? editor.item : undefined;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() => {
    const i = item as
      (Project & Knowledge & Memory & Provider & Workflow) | undefined;
    return {
      name: i?.name || "",
      description: i?.description || "",
      path: i?.path || "",
      instructions: i?.instructions || "",
      content: i?.content || "",
      title: i?.title || "",
      topic: i?.topic || "",
      category: i?.category || "preference",
      model: i?.default_model || "",
      key: "",
      goal: i?.goal || "",
      project: String(data?.activeProject?.id || ""),
      policy: "NEVER",
      provider: "",
      capability: "",
      steps: JSON.stringify(
        i?.steps || [{ tool: "read_file", args: { path: "notizen.md" } }],
        null,
        2,
      ),
    };
  });
  const [auto, setAuto] = useState(!item);
  const [enabled, setEnabled] = useState(
    editor.kind === "provider" ? editor.item.enabled : false,
  );
  const [caps, setCaps] = useState(
    editor.kind === "provider" ? editor.item.capabilities : ([] as string[]),
  );
  const [external, setExternal] = useState(false);
  const [removeKey, setRemoveKey] = useState(false);
  const set = (key: string, value: string) =>
    setValues((prev) => ({ ...prev, [key]: value }));
  const titles = {
    task: "Neue Aufgabe",
    project: item ? "Projekt bearbeiten" : "Neues Projekt",
    knowledge: item ? "Wissen bearbeiten" : "Wissen festhalten",
    memory: item ? "Erinnerung bearbeiten" : "Information vorschlagen",
    provider: "Provider konfigurieren",
    workflow: item ? "Workflow bearbeiten" : "Neuer Workflow",
  };
  const input = (key: string, placeholder = "", required = false) => (
    <input
      value={values[key]}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      required={required}
    />
  );
  const textarea = (key: string, placeholder = "", required = false) => (
    <textarea
      value={values[key]}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      required={required}
      rows={4}
    />
  );
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (editor.kind === "project") {
        const params = {
          name: values.name,
          description: values.description,
          instructions: values.instructions,
          path: values.path,
        };
        if (editor.item)
          await action(
            "update_project",
            { project_id: editor.item.id, ...params },
            "Projekt aktualisiert",
          );
        else {
          const project = await action<Project>(
            "create_project",
            { ...params, auto_workspace: auto },
            "Projekt angelegt",
          );
          await action("set_active_project", { project_id: project.id });
        }
      } else if (editor.kind === "task") {
        await action(
          "create_task",
          {
            goal: values.goal,
            project_id: Number(values.project),
            ai_policy: {
              mode: values.policy,
              local_only: !external,
              allow_external: external,
              selected_provider: values.provider || null,
              required_capability: values.capability || null,
            },
            allow_external: external,
          },
          "Aufgabe angelegt",
        );
      } else if (editor.kind === "knowledge") {
        await action(
          editor.item ? "update_knowledge" : "add_knowledge",
          {
            ...(editor.item
              ? { entry_id: editor.item.id }
              : { project_id: values.project ? Number(values.project) : null }),
            title: values.title,
            content: values.content,
            topic: values.topic,
          },
          "Wissen gespeichert",
        );
      } else if (editor.kind === "memory") {
        await action(
          editor.item ? "update_memory" : "propose_memory",
          editor.item
            ? { fact_id: editor.item.id, content: values.content }
            : { content: values.content, category: values.category },
          "Erinnerung gespeichert",
        );
      } else if (editor.kind === "provider") {
        await action(
          "configure_provider",
          {
            name: editor.item.name,
            enabled,
            model: values.model || null,
            capabilities: caps,
            ...(!editor.item.is_local && (removeKey || values.key)
              ? { api_key: removeKey ? "" : values.key }
              : {}),
          },
          "Provider-Konfiguration gespeichert",
        );
        set("key", "");
      } else if (editor.kind === "workflow") {
        await action(
          "save_workflow",
          {
            name: values.name,
            goal: values.goal,
            steps: JSON.parse(values.steps),
            ...(editor.item ? { workflow_id: editor.item.id } : {}),
          },
          "Workflow gespeichert",
        );
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Speichern fehlgeschlagen.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={titles[editor.kind]}
      description={
        editor.kind === "task"
          ? "Beschreibe das Ziel. CLS plant die Schritte; schreibende Aktionen benötigen deine Freigabe."
          : editor.kind === "memory"
            ? "Neue Informationen starten als Kandidat und bleiben bis zur Bestätigung ungeprüft."
            : undefined
      }
      wide={editor.kind === "task" || editor.kind === "workflow"}
    >
      <form onSubmit={save} className="form-stack">
        {editor.kind === "project" && (
          <>
            <Field label="Projektname">
              {input("name", "z. B. Mein Arbeitsraum", true)}
            </Field>
            <Field label="Beschreibung">
              {textarea("description", "Worum geht es in diesem Projekt?")}
            </Field>
            <Field
              label="Workspace"
              hint="Ein expliziter absoluter Pfad hat immer Vorrang."
            >
              <div className="input-action">
                {input("path", "D:\\Projekte\\Mein Projekt")}
                <Button
                  type="button"
                  variant="outline"
                  aria-label="Workspace auswählen"
                  onClick={async () => {
                    try {
                      const value = await choosePath("directory");
                      if (value) set("path", value);
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                >
                  <FolderOpen size={17} />
                </Button>
              </div>
            </Field>
            {!editor.item && (
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={auto}
                  onChange={(e) => setAuto(e.target.checked)}
                />
                Workspace aus dem Projektnamen erstellen, wenn kein Pfad
                angegeben ist
              </label>
            )}
            <details>
              <summary>Projektanweisungen</summary>
              <Field label="Kontext für CLS">
                {textarea(
                  "instructions",
                  "Hinweise zur Arbeitsweise in diesem Projekt",
                )}
              </Field>
            </details>
          </>
        )}
        {editor.kind === "task" && (
          <>
            <Field label="Was möchtest du erreichen?">
              {textarea(
                "goal",
                "z. B. Lies notizen.md und fasse den Inhalt zusammen",
                true,
              )}
            </Field>
            <Field label="Projekt">
              <select
                value={values.project}
                onChange={(e) => set("project", e.target.value)}
                required
              >
                <option value="">Projekt auswählen</option>
                {data?.projects
                  .filter((p) => p.status === "active")
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </Field>
            <div className="form-grid">
              <Field label="AI-Nutzung">
                <select
                  value={values.policy}
                  onChange={(e) => set("policy", e.target.value)}
                >
                  <option value="NEVER">Nur lokale Tools</option>
                  <option value="ALLOWED">AI erlaubt</option>
                  <option value="FALLBACK">AI bei Bedarf</option>
                </select>
              </Field>
              <Field label="Provider">
                <select
                  value={values.provider}
                  onChange={(e) => set("provider", e.target.value)}
                >
                  <option value="">Automatisch</option>
                  {data?.providers.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.display_name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Benötigte Fähigkeit">
              <select
                value={values.capability}
                onChange={(e) => set("capability", e.target.value)}
              >
                <option value="">Automatisch erkennen</option>
                {capabilities.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
            <label className="check-field">
              <input
                type="checkbox"
                checked={external}
                onChange={(e) => setExternal(e.target.checked)}
                disabled={values.policy === "NEVER"}
              />
              Externe Provider für diesen Task erlauben
            </label>
            <p className="field-hint">
              Workspace-, Privacy- und Safety-Regeln gelten unabhängig von
              dieser Auswahl.
            </p>
          </>
        )}
        {editor.kind === "knowledge" && (
          <>
            <Field label="Titel">{input("title", "Ein klarer Titel")}</Field>
            <Field label="Inhalt">
              {textarea(
                "content",
                "Welche Erkenntnis möchtest du festhalten?",
                true,
              )}
            </Field>
            <Field label="Thema">{input("topic", "z. B. Architektur")}</Field>
            {!editor.item && (
              <Field label="Geltungsbereich">
                <select
                  value={values.project}
                  onChange={(e) => set("project", e.target.value)}
                >
                  <option value="">Globales Wissen</option>
                  {data?.projects
                    .filter((p) => p.status === "active")
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </Field>
            )}
          </>
        )}
        {editor.kind === "memory" && (
          <>
            <Field label="Information">
              {textarea(
                "content",
                "Interessen, Ziele oder bevorzugte Arbeitsweisen …",
                true,
              )}
            </Field>
            {!editor.item && (
              <Field label="Kategorie">
                <select
                  value={values.category}
                  onChange={(e) => set("category", e.target.value)}
                >
                  <option value="preference">Präferenz</option>
                  <option value="skill">Kenntnisse</option>
                  <option value="goals">Ziele</option>
                  <option value="user_profile">Über mich</option>
                </select>
              </Field>
            )}
          </>
        )}
        {editor.kind === "provider" && (
          <>
            <div className="callout">
              {editor.item.is_local
                ? "Lokales Modell · Daten bleiben auf deinem Gerät"
                : "Externer Provider · Privacy-Regeln gelten immer"}
            </div>
            <label className="check-field">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Provider aktiviert
            </label>
            <Field label="Modell">
              {input("model", "Modellname beim Provider")}
            </Field>
            <fieldset>
              <legend>Fähigkeiten</legend>
              <div className="cap-checks">
                {capabilities
                  .filter(
                    (c) => c !== "local_reasoning" || editor.item.is_local,
                  )
                  .map((c) => (
                    <label key={c} className="check-field">
                      <input
                        type="checkbox"
                        checked={caps.includes(c)}
                        onChange={(e) =>
                          setCaps(
                            e.target.checked
                              ? [...caps, c]
                              : caps.filter((x) => x !== c),
                          )
                        }
                      />
                      {c}
                    </label>
                  ))}
              </div>
            </fieldset>
            {!editor.item.is_local && (
              <>
                <Field
                  label="Neuer API-Key"
                  hint="Leer lassen, um den vorhandenen Key zu behalten. Er wird niemals zurück an die Oberfläche übertragen."
                >
                  <input
                    autoComplete="off"
                    type="password"
                    value={values.key}
                    onChange={(e) => set("key", e.target.value)}
                    disabled={removeKey}
                  />
                </Field>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={removeKey}
                    onChange={(e) => setRemoveKey(e.target.checked)}
                  />
                  Gespeicherten API-Key entfernen
                </label>
              </>
            )}
          </>
        )}
        {editor.kind === "workflow" && (
          <>
            <Field label="Name">{input("name", "Mein Ablauf", true)}</Field>
            <Field label="Exaktes Ziel für die Wiederverwendung">
              {input("goal", "Notizen lesen", true)}
            </Field>
            <Field
              label="Tool-Schritte (JSON)"
              hint="Vorherige Ergebnisse können mit {step: 0, field: 'path'} referenziert werden. Alle Aktionen nutzen die bestehende Safety-Schicht."
            >
              <textarea
                className="mono"
                rows={10}
                value={values.steps}
                onChange={(e) => set("steps", e.target.value)}
                required
              />
            </Field>
          </>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={onClose}
          >
            Abbrechen
          </Button>
          <BusyButton busy={busy} type="submit">
            {editor.kind === "task" ? "Aufgabe erstellen" : "Speichern"}
          </BusyButton>
        </div>
      </form>
    </Modal>
  );
}
