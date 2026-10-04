import { useState } from "react";
import {
  Cpu,
  Globe2,
  Settings2,
  ArrowRight,
  ShieldCheck,
  GripVertical,
  ChevronUp,
  ChevronDown,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import {
  PageTitle,
  Button,
  Empty,
  Badge,
  Field,
  BusyButton,
} from "@/components/primitives";
import type { Editor } from "@/components/editors";
export function Providers({ edit }: { edit: (e: Editor) => void }) {
  const { data, action } = useCLS();
  const [capability, setCapability] = useState("general_reasoning");
  const [order, setOrder] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const names = order || [
    ...(data.routing[capability] || []).map((p) => p.name),
    ...data.providers
      .map((p) => p.name)
      .filter(
        (n) => !(data.routing[capability] || []).some((p) => p.name === n),
      ),
  ];
  function move(index: number, offset: number) {
    const next = [...names];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    setOrder(next);
  }
  return (
    <>
      <PageTitle
        title="Provider"
        description="Das passende Modell für jede Aufgabe. Deine Regeln bestimmen den Weg."
      />
      <div className="info-banner">
        <ShieldCheck size={20} />
        <p>
          „Konfiguriert“ bedeutet: aktiviert und Zugangsdaten vorhanden. Eine
          erfolgreiche Verbindung wird erst durch eine echte Anfrage belegt.
        </p>
      </div>
      <div className="provider-grid">
        {data.providers.map((p) => (
          <article className="panel provider-card" key={p.name}>
            <header>
              <span className={`provider-logo ${p.is_local ? "local" : ""}`}>
                {p.is_local ? <Cpu size={25} /> : p.display_name.slice(0, 1)}
              </span>
              <span
                className={`connection-status ${p.enabled && p.available ? "configured" : ""}`}
              >
                <i />
                {p.enabled && p.available
                  ? "Konfiguriert"
                  : p.enabled
                    ? "Zugang fehlt"
                    : "Deaktiviert"}
              </span>
            </header>
            <h2>{p.display_name}</h2>
            <p>
              <span>
                {p.is_local ? <Cpu size={13} /> : <Globe2 size={13} />}
              </span>
              {p.is_local ? "Lokal auf deinem Gerät" : "Externer AI-Provider"}
            </p>
            <div className="model-label">
              {p.default_model || "Kein Modell ausgewählt"}
            </div>
            <div className="capabilities">
              {p.capabilities.map((c) => (
                <span key={c}>
                  {(
                    {
                      general_reasoning: "Allgemein",
                      research: "Recherche",
                      web_search: "Websuche",
                      coding: "Coding",
                      local_reasoning: "Lokal",
                    } as Record<string, string>
                  )[c] || c}
                </span>
              ))}
            </div>
            <Button
              variant="outline"
              onClick={() => edit({ kind: "provider", item: p })}
            >
              <Settings2 size={15} />
              Konfigurieren
            </Button>
          </article>
        ))}
      </div>
      {!data.providers.length && (
        <Empty
          title="Noch keine Provider eingerichtet"
          description="Lokale Dateiaktionen funktionieren auch ohne AI-Provider."
        />
      )}
      <section className="panel routing-panel">
        <div>
          <span className="eyebrow">AUTOMATISCHE AUSWAHL</span>
          <h2>Deine Reihenfolge. Ein klarer Fallback.</h2>
          <p>
            CLS berücksichtigt Fähigkeit, Modell, Verfügbarkeit und Task-Policy.
            Privacy- und Safety-Regeln haben immer Vorrang.
          </p>
          <Field label="Fähigkeit">
            <select
              value={capability}
              onChange={(e) => {
                setCapability(e.target.value);
                setOrder(null);
              }}
            >
              {[
                "general_reasoning",
                "research",
                "web_search",
                "coding",
                "local_reasoning",
              ].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="priority-list">
          {names.map((name, i) => (
            <div key={name}>
              <span className="priority-number">{i + 1}</span>
              <strong>
                {data.providers.find((p) => p.name === name)?.display_name ||
                  name}
              </strong>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`${name} höher priorisieren`}
                disabled={i === 0}
                onClick={() => move(i, -1)}
              >
                <ChevronUp size={16} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`${name} niedriger priorisieren`}
                disabled={i === names.length - 1}
                onClick={() => move(i, 1)}
              >
                <ChevronDown size={16} />
              </Button>
            </div>
          ))}
          <BusyButton
            busy={busy}
            disabled={!order}
            onClick={async () => {
              setBusy(true);
              try {
                await action(
                  "set_provider_priority",
                  { capability, names },
                  "Reihenfolge gespeichert",
                );
                setOrder(null);
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            Priorität speichern
          </BusyButton>
        </div>
      </section>
    </>
  );
}
