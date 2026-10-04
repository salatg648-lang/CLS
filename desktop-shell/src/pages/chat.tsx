import { useState, useRef, useEffect } from "react";
import {
  ArrowUp,
  Sparkles,
  FolderOpen,
  ShieldCheck,
  CornerDownLeft,
  MessageSquare,
  Terminal,
  Trash2,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import { Button, BusyButton, Empty, Confirm } from "@/components/primitives";
import { clock } from "@/lib/utils";
interface Reply {
  text: string;
  error?: boolean;
  provider?: string;
  task_id?: string;
}
export function Chat({ selectTask }: { selectTask: (id: string) => void }) {
  const { data, action } = useCLS();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("chat");
  const [provider, setProvider] = useState("");
  const [local, setLocal] = useState(true);
  const [last, setLast] = useState<Reply | null>(null);
  const [clear, setClear] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [data?.conversation.length, busy, last]);
  if (!data) return null;
  async function send() {
    if (!draft.trim() || busy) return;
    const text = draft.trim();
    setDraft("");
    setBusy(true);
    setLast(null);
    try {
      const reply = await action<Reply>("chat", {
        text,
        mode,
        provider: provider || null,
        local_only: local,
      });
      setLast(reply);
    } catch {
      setDraft(text);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }
  const inHistory =
    last &&
    data.conversation.some(
      (m) => m.role === "assistant" && m.content === last.text,
    );
  return (
    <div className="chat-page">
      <div className="chat-top">
        <div>
          <h1>Chat mit CLS</h1>
          <p>
            <FolderOpen size={13} />
            {data.activeProject?.name || "Kein Projekt ausgewählt"}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Chatverlauf löschen"
          onClick={() => setClear(true)}
        >
          <Trash2 size={17} />
        </Button>
      </div>
      <div className="chat-messages">
        {!data.conversation.length && !last ? (
          <div className="chat-welcome">
            <div className="cls-glyph large">
              <Sparkles size={34} />
            </div>
            <span className="eyebrow">DEIN KONTEXT. DEIN ASSISTENT.</span>
            <h2>Womit fangen wir an?</h2>
            <p>Gedanken ordnen, Wissen finden oder lokal etwas erledigen.</p>
            <div className="suggestions">
              {[
                ["Zeige Dateien im Projekt", "Deinen Workspace erkunden"],
                ["In welchem Projekt bin ich?", "Kontext im Blick behalten"],
                ["Uhrzeit", "Eine lokale Aktion ausprobieren"],
              ].map(([text, label]) => (
                <button
                  key={text}
                  onClick={() => {
                    setDraft(text);
                    input.current?.focus();
                  }}
                >
                  <Terminal size={18} />
                  <strong>{label}</strong>
                  <span>{text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          data.conversation.map((m, i) => (
            <article className={`message ${m.role}`} key={i}>
              <span className="message-avatar">
                {m.role === "user" ? (
                  data.settings.user_name[0]
                ) : (
                  <Sparkles size={16} />
                )}
              </span>
              <div>
                <header>
                  <strong>{m.role === "user" ? "Du" : "CLS"}</strong>
                  <span>{clock(m.timestamp)}</span>
                  {m.meta?.provider && <small>{m.meta.provider}</small>}
                </header>
                <div className="message-content">{m.content}</div>
              </div>
            </article>
          ))
        )}
        {last && !inHistory && (
          <div
            className={last.error ? "callout warning" : "callout"}
            role={last.error ? "alert" : "status"}
          >
            {last.text}
          </div>
        )}
        {last?.task_id && (
          <Button variant="outline" onClick={() => selectTask(last.task_id!)}>
            Aufgabe und Freigabe öffnen
          </Button>
        )}
        {busy && (
          <div className="thinking" role="status">
            <span />
            <span />
            <span />
            CLS arbeitet …
          </div>
        )}
        <div ref={end} />
      </div>
      <div className="composer-area">
        <div className="composer">
          <textarea
            ref={input}
            aria-label="Nachricht an CLS"
            placeholder="Frag CLS oder beschreibe eine Aufgabe …"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                void send();
              }
            }}
            rows={3}
          />
          <div className="composer-toolbar">
            <div>
              <select
                aria-label="Chatmodus"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="chat">Chat</option>
                <option value="research">Recherche</option>
                <option value="coding">Coding</option>
              </select>
              <select
                aria-label="Chatprovider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="">Automatisch</option>
                {data.providers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.display_name}
                  </option>
                ))}
              </select>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={local}
                  onChange={(e) => setLocal(e.target.checked)}
                />
                Nur lokal
              </label>
            </div>
            <BusyButton
              busy={busy}
              disabled={!draft.trim()}
              aria-label="Nachricht senden"
              size="icon"
              onClick={() => send()}
            >
              <ArrowUp size={19} />
            </BusyButton>
          </div>
        </div>
        <footer>
          <span>
            <ShieldCheck size={12} />
            Du behältst die Kontrolle über Daten und Aktionen.
          </span>
          <span>
            <CornerDownLeft size={12} />
            Senden · Shift + Enter für neue Zeile
          </span>
        </footer>
      </div>
      <Confirm
        open={clear}
        onClose={() => setClear(false)}
        title="Chatverlauf löschen?"
        danger
        onConfirm={() => action("clear_conversation", {}, "Verlauf gelöscht")}
      >
        <p>
          Gespeicherte Fakten und Wissen bleiben erhalten. Der Chatverlauf wird
          entfernt.
        </p>
      </Confirm>
    </div>
  );
}
