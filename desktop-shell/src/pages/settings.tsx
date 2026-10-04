import { useState } from "react";
import {
  Moon,
  Sun,
  Monitor,
  ShieldCheck,
  Keyboard,
  FolderOpen,
} from "lucide-react";
import { useCLS } from "@/lib/store";
import { Button, BusyButton, Field, PageTitle } from "@/components/primitives";
export function Settings({
  theme,
  setTheme,
}: {
  theme: string;
  setTheme: (theme: string) => void;
}) {
  const { data, action } = useCLS();
  const [path, setPath] = useState("");
  const [privacy, setPrivacy] = useState("LOCAL_ONLY");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <PageTitle
        title="Einstellungen"
        description="Dein Arbeitsraum soll zu dir passen."
      />
      <div className="settings-grid">
        <section className="panel settings-section">
          <header>
            <Sun size={19} />
            <div>
              <h2>Erscheinungsbild</h2>
              <p>Wähle, wie sich CLS für dich anfühlt.</p>
            </div>
          </header>
          <div className="theme-options">
            {[
              { id: "dark", label: "Dunkel", Icon: Moon },
              { id: "light", label: "Hell", Icon: Sun },
              { id: "system", label: "System", Icon: Monitor },
            ].map(({ id, label, Icon }) => (
              <button
                key={id}
                aria-pressed={theme === id}
                className={theme === id ? "selected" : ""}
                onClick={() => setTheme(id)}
              >
                <div className={`theme-preview ${id}`}>
                  <span />
                  <section>
                    <i />
                    <i />
                    <i />
                  </section>
                </div>
                <span>
                  <Icon size={15} />
                  {label}
                </span>
              </button>
            ))}
          </div>
        </section>
        <section className="panel settings-section">
          <header>
            <Keyboard size={19} />
            <div>
              <h2>Schneller mit der Tastatur</h2>
              <p>Weniger Umwege, mehr Fokus.</p>
            </div>
          </header>
          <div className="shortcut-row">
            <span>Suche und Befehle</span>
            <span>
              <kbd>Strg</kbd> + <kbd>K</kbd>
            </span>
          </div>
          <div className="shortcut-row">
            <span>Neu im aktuellen Bereich</span>
            <span>
              <kbd>Strg</kbd> + <kbd>N</kbd>
            </span>
          </div>
          <div className="shortcut-row">
            <span>Sidebar ein-/ausklappen</span>
            <span>
              <kbd>Strg</kbd> + <kbd>B</kbd>
            </span>
          </div>
          <div className="shortcut-row">
            <span>Dialog schließen</span>
            <kbd>Esc</kbd>
          </div>
        </section>
        <section className="panel settings-section">
          <header>
            <ShieldCheck size={19} />
            <div>
              <h2>Datenschutz für Dateien</h2>
              <p>Die bestehenden Regeln gelten für alle Provider und Tools.</p>
            </div>
          </header>
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await action(
                  "set_path_privacy",
                  { path, level: privacy },
                  "Datenschutzregel gespeichert",
                );
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Absoluter Datei- oder Ordnerpfad">
              <input
                required
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder={data?.activeProject?.path || "Pfad eingeben"}
              />
            </Field>
            <Field label="Freigabe">
              <select
                value={privacy}
                onChange={(e) => setPrivacy(e.target.value)}
              >
                <option value="LOCAL_ONLY">Nur lokal</option>
                <option value="USER_CONFIRMATION_REQUIRED">
                  Externe Nutzung nach Bestätigung
                </option>
                <option value="SAFE_FOR_EXTERNAL">
                  Für externe Provider freigegeben
                </option>
                <option value="BLOCKED">Verarbeitung blockieren</option>
              </select>
            </Field>
            <BusyButton busy={busy} variant="outline">
              Regel speichern
            </BusyButton>
          </form>
        </section>
        <section className="panel settings-section">
          <header>
            <Monitor size={19} />
            <div>
              <h2>Über CLS</h2>
              <p>
                Ein persönlicher Assistent mit nachvollziehbaren Entscheidungen.
              </p>
            </div>
          </header>
          <dl className="about-list">
            <dt>Core-Version</dt>
            <dd>{data?.settings.app_version}</dd>
            <dt>Desktop-Oberfläche</dt>
            <dd>Electron · React</dd>
            <dt>Benutzer</dt>
            <dd>{data?.settings.user_name}</dd>
            <dt>Aktives Projekt</dt>
            <dd>{data?.activeProject?.name || "Keines"}</dd>
            <dt>Datenspeicherung</dt>
            <dd>Lokal · SQLite</dd>
            <dt>Verbindung</dt>
            <dd>{data?.demo ? "Isolierte Vorschau" : "Lokaler Python-Core"}</dd>
          </dl>
          <p className="field-hint">
            API-Keys und Modelle verwaltest du im Bereich Provider. Es gibt
            keine automatische Freigabe von Strategiekandidaten.
          </p>
        </section>
      </div>
    </>
  );
}
