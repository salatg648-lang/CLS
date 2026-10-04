# CLS — Personal AI System (Phase 1–6)

## Start
```
python -m venv venv && venv\Scripts\activate      # Windows (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                            # Keys nur für externe Provider eintragen
npm ci --prefix desktop-shell                    # Node 24
python main.py
```
Tests (ohne Netzwerk/Keys/Display): `python -m unittest discover -s tests -v`

## Bedienung
- **Chat-Modi** oben rechts: *Chat* (automatisches Routing), *Research*, *Coding*
- Jede Antwort zeigt, welcher Provider geantwortet hat ("CLS · Perplexity")
- "Merk dir, dass ..." / "Merke: ..." speichert einen Fakt (ohne AI-Aufruf)
- Sidebar → **Provider**: Provider-Konfiguration, Status und bearbeitbare Routing-Prioritäten

## Routing (Phase 2)
Text/Modus → Capability → Provider. Regeln in `config/routing.py`,
Standardprioritäten in `config/providers.py`, Standardmodelle in `config/models.py`.
Gespeicherte Einstellungen aus **Provider** überschreiben diese Defaults in der bestehenden SQLite-`app_state`.
Ist ein Provider ohne Key oder schlägt er fehl, springt automatisch der nächste ein.

| Capability | zuerst | dann |
|---|---|---|
| coding | Perplexity | Gemini |
| web_search | Perplexity | Gemini |
| research | Gemini | Perplexity |
| general_reasoning | Gemini | Perplexity |

## Neuer Provider in 3 Schritten
1. `providers/xyz.py` mit `BaseProvider` (chat, is_available, capabilities)
2. In `capabilities/registry.py` in `create_provider` eintragen (kompatible APIs nutzen denselben Adapter)
3. In `config/providers.py` + `config/models.py` aktivieren

## Änderungen gegenüber Phase-1-Original
Siehe Chat-Zusammenfassung: Gemini bekam vorher nur die letzte Nachricht (kein System-Prompt/Verlauf),
UI-Freeze, doppelte Fakt-IDs, stiller Datenverlust bei kaputter JSON, doppelte Config u.a. — alles behoben.

## Knowledge & Projects (Phase 3)

Daten liegen in `data/cls.db` (SQLite, Volltextsuche über FTS5). Importierte Dokumente werden zusätzlich
nach `data/knowledge/documents/` kopiert. Chat-Verlauf und persönliche Fakten werden seit Phase 5 ebenfalls in SQLite gespeichert.
Vorhandene JSON-Dateien werden beim ersten Start einmalig übernommen und als Backup behalten.

**Wissen hat immer Herkunft, Vertrauen und Verlauf**
- *Provenance:* jede Quelle (Nutzer, Dokument+Teil, AI-Provider, Web-Link) wird gespeichert
- *Trust:* `CONFIRMED` (von dir) · `SUPPORTED` (Dokument/mehrere Quellen) · `UNCERTAIN` · `CONFLICTING` · `OUTDATED` · `CANDIDATE`
- *Versioning:* Änderungen erzeugen neue Versionen, nichts wird überschrieben; jede alte Version ist wiederherstellbar
- *Conflicts:* Kurze Fakten, die sich bei Zahlen/Versionen oder durch Verneinung widersprechen, werden markiert.
  Beide Einträge bleiben erhalten. Du entscheidest: A behalten / B behalten / beide gültig.
  Ein bestätigter Eintrag wird nie automatisch abgewertet.

**Controlled Learning:** Research- und Web-Antworten werden als *Kandidat* gespeichert (Knowledge-Ansicht →
Filter "KANDIDAT"), aber nie automatisch als Wissen genutzt. Erst wenn du bestätigst — oder zwei unabhängige
Quellen (z.B. zwei Provider) denselben Inhalt liefern — wird daraus Wissen. Ausschalten: `AUTO_CANDIDATES = False`
in `config/knowledge.py`.

**Im Chat**
- Jede Anfrage bekommt das *relevante* Wissen (max. 5 Einträge; nur bestätigt/gesichert/unsicher/widersprüchlich)
  plus das aktive Projekt in den Prompt. Der Antwortkopf zeigt "· Wissen: 2".
- "Was weißt du über X?" beantwortet CLS direkt aus der Wissensbasis, ohne AI-Aufruf. Steht dazu nichts drin,
  sagt CLS das ehrlich ("ich rate nicht"). Fragen nach dir selbst ("... über mich") gehen weiter an die AI.
- Wissensbasis-Inhalt ist als Referenz markiert, nicht als Anweisung (Schutz vor Prompt-Injection über Dokumente).

**Projekte:** Name, Beschreibung, eigene Anweisungen. Ein *aktives* Projekt sieht sein eigenes + globales Wissen;
ohne aktives Projekt gibt es nur globales Wissen. Löschen: Wissen stillgelegt mit ursprünglicher Herkunft
behalten oder mitlöschen. Es wird nicht automatisch global freigegeben.

**Dokument-Import:** `.txt .md .docx .pdf` und Code-/Textdateien. Sensible Dateien (`.env`, `*.key`, ...) werden
abgelehnt, dieselbe Datei wird pro Projekt nicht doppelt importiert, ein Fehler speichert nichts halb.
PDFs brauchen `pypdf`; gescannte PDFs (ohne Text) gehen noch nicht (kein OCR).

**Grenzen (bewusst)**
- Konflikt-Erkennung ist regelbasiert, ohne AI: sie liefert *Hinweise* (z.B. "17 ↔ 21"), keine Wahrheit. Dokument-Teile
  und lange Texte (> 800 Zeichen) werden nicht geprüft. Zwei Fakten zu verschiedenen Versionen können fälschlich als
  Widerspruch auftauchen — dann "Beide gültig" wählen.
- Die Suche ist Textsuche (Wortstamm-Präfixe, Umlaute egal), kein semantisches RAG.

## Struktur (neu in Phase 3)
```
infrastructure/database.py   SQLite (thread-sicher, Transaktionen, Migration)
config/knowledge.py          Trust-Levels, Limits, Ingestion-Einstellungen
knowledge/                   base · trust · versions · conflicts · search · ingestion · models
projects/manager.py          Projekte + aktives Projekt
prompts/knowledge.txt        Regeln für den Umgang mit Wissen
desktop/views/               knowledge_view.py, projects_view.py
desktop/components/dialogs.py
tests/test_phase3.py         Core-Tests
tests/test_ui_smoke.py       UI-Logik gegen den echten Core (mit Stubs, ohne Display)
```


## Tools & Agent (Phase 4)

1. Unter **Projects** einen Arbeitsordner eintragen und das Projekt aktivieren.
2. Unter **Tasks** ein Ziel anlegen und starten. Ein passender gespeicherter Workflow hat Vorrang.
3. Erkannte lokale Aktionen werden als strukturierter Workflow ausgeführt. Für andere Ziele benötigt der Agent einen Provider mit nativen Funktionen: Gemini, Ollama oder ein dafür konfiguriertes Groq-/OpenRouter-/CometAPI-Modell.
   Perplexity bleibt über `ask_ai` als Recherche-/Coding-Berater nutzbar.
4. Im Dialog die KI-Policy wählen (Standard: FALLBACK). Wissen bleibt standardmäßig vollständig verfügbar.
   Bestätigungspflichtige Projektinhalte haben eine separate externe Freigabe; Details siehe Task-Policies.
5. Schreib- und Terminalaktionen einzeln über **Aktion prüfen** kontrollieren und bestätigen oder ablehnen.
   Vollständige Argumente und der konfigurierte Befehl werden vor der Ausführung angezeigt.

Tools: `read_file`, `write_file`, `edit_file`, `search_files`, `copy_file`, `move_file`, `file_info`,
`open_path`, `clipboard_read`, `clipboard_write`, `run_command`, `run_build`, `run_tests`, `ask_ai`.
Nur native strukturierte Funktionsaufrufe werden ausgeführt; Antworttext wird niemals als Befehl interpretiert.
Der Plan wird über `set_plan` erstellt; `request_help` fragt nach Hilfe; `finish_task` verlangt einen Prüfbeleg.
Native Coding-Aufgaben verlangen **Build und Tests nach der letzten Änderung**. Lokale Datei-Workflows
prüfen stattdessen die konkreten Dateieffekte durch Zurücklesen und Inhaltsvergleich. Bei reinen
Leseaufgaben genügt eine erfolgreiche Lese-/Suchaktion; das beweist keinen fachlichen Wahrheitsgehalt.
Fehler werden dem Agenten für begrenztes Replanning zurückgegeben. Workflows stoppen bei Fehlern.

### Berechtigungen und Datenschutz

- `config/permissions.py`: `auto`, `confirm`, `never` und exakte Befehle. Keine freie Shell und keine
  vom Modell gewählten zusätzlichen Argumente. Standardbefehle: Python-Compileall und Unittest.
- `config/paths.py`: optional erlaubte Wurzelordner. Ohne Einschränkung gelten die vom Nutzer gewählten
  Projektordner. `resolve()` + `is_relative_to()` schützen gegen `..`/ähnliche Nachbarpfade;
  Symlinks, Hardlinks und sensible Dateinamen sind für Datei-Tools gesperrt.
- **Settings**: Datenschutzregel für Datei/Ordner speichern. Der spezifischste Pfad gewinnt.
  `BLOCKED` sperrt Verarbeitung, `LOCAL_ONLY` sperrt externes Senden, `SAFE_FOR_EXTERNAL` erlaubt es,
  `USER_CONFIRMATION_REQUIRED` ist der Standard. Im Agenten zählt die explizite externe Task-Freigabe;
  im Chat werden solche Dokumente bis zur Umstellung auf `SAFE_FOR_EXTERNAL` ausgelassen.
- Lokale AI-Kandidaten bleiben auch nach Bestätigung lokal. Im Wissensdetail kann die
  Datenschutzstufe explizit geändert werden; Dokumentregeln gelten weiterhin zusätzlich.
- Dokumentquellen werden vor jedem Chat-Kontext erneut geprüft. Ein Verlauf mit lokalen Antworten wird
  nicht an externe Provider weitergereicht. Persönliche Fakten benötigen für externen Kontext eine ausdrückliche Freigabe. Chat-Verläufe werden
  nach Projektscope gefiltert; manuelle Providerwahl umgeht keine Privacy-/Netzwerkregel.
- **Terminalbefehle führen Projektcode mit Benutzerrechten aus. Dies ist keine OS-Sandbox.** Nur vertraute
  Projekte bestätigen. Netzwerkzugriffe/Dateizugriffe innerhalb eines Builds sind nicht durch Python-
  Pfadprüfungen isoliert. API-Schlüssel werden nicht in die Prozessumgebung übernommen; Programm-Ausgaben
  können dennoch vertrauliche Inhalte enthalten. Extern freigegebene Tasks können diese Ausgaben senden.
- Grenzen in `config/agent.py`: 20 Schritte, 15 Tool-Aufrufe, 3 Fehlversuche pro identischer Aktion,
  60 Sekunden Prozess-/Gemini-Timeout und 10 API-Aufrufe. Ollama verwendet separat
  `config/providers.py → ollama.request_timeout` (180 Sekunden) und sendet immer `think: false`. Kosten werden konservativ je Aufruf reserviert;
  `API_CALL_RESERVATION`/`MAX_TOTAL_COST` sind lokale Budgeteinheiten, **keine Abrechnungsgarantie**.
- Bei Prozessabbruch während einer Aktion wird deren Ergebnis als unbekannt markiert. Der Task führt sie
  nicht automatisch erneut aus; erst Ergebnis manuell prüfen und bei Bedarf einen neuen Task anlegen.

## Tasks & Experience (Phase 5)

**Tasks** zeigt Plan, Status, Fortschritt und konkrete benötigte Hilfe. Start/Fortsetzen, Pause, Information
geben und einzelne Bestätigungen sind verfügbar. Pausen greifen zwischen Aktionen; ein laufender
Provider-/Prozessaufruf endet oder erreicht seinen Timeout.

**Activity** zeigt den persistenten Action Trail mit Task-/Art-Filter: Plan, AI-Aufrufe, Tool-Ergebnisse,
Fehler, Bestätigungszustände und Abschluss. Daraus entsteht beim verifizierten Abschluss ein separater
Experience-Eintrag. **Memory** verwaltet persönliche Fakten (Suchen, Hinzufügen, Bearbeiten, Löschen) und
zeigt Erfahrungen des aktiven Projekts. Die bisherigen JSON-Dateien werden bei der SQLite-Migration
nicht gelöscht und nicht erneut importiert.

**Ollama:** lokal installieren/starten und ein toolfähiges lokales Modell bereitstellen, anschließend in
`config/providers.py` bei `ollama` `enabled=True` setzen. Modell über `OLLAMA_MODEL` bzw. `config/models.py`,
Adresse über `OLLAMA_HOST` bzw. Provider-Konfiguration. Nur HTTP-Loopback-Adressen und lokale Modelle;
Cloud-Modellnamen sind gesperrt. Bei ungültiger Ollama-Host-Konfiguration wird dieser Provider mit
einem Log-Hinweis übersprungen; andere Provider und die App bleiben verfügbar. Die Provider-Anzeige bedeutet „konfiguriert“; Verbindungsfehler werden
beim Aufruf gemeldet. Ollama läuft optional, kein automatischer Modell-Download.

## Workflows & Automation (Phase 6)

Unter **Tasks → Workflow / Automation** eigene Schritte speichern, zum Beispiel:

```json
[{"tool": "search_files", "args": {"pattern": "*.py"}}]
```

Neue Workflows verwenden die Zustandsprüfungen der Datei-/Clipboard-Tools. Beliebige
`run_command`-Aktionen benötigen weiterhin Build und Tests; einfaches Lesen ersetzt diese Prüfung nicht.
Ältere Workflow-Snapshots behalten ihre Prüfregeln. Workflows verwenden nur registrierte lokale Tools und umgehen keine Freigaben. Beim Task-Start wird eine unveränderliche
Kopie des Workflows gespeichert. Ein exakt passendes Ziel verwendet den Workflow ohne AI; verifizierte
Erfahrungen im selben Projekt helfen bei der Auswahl. Unbekannte Ziele gehen an den Agenten.

Zeitpläne verwenden Intervalle ab 60 Sekunden oder `project.activated`, `document.imported`,
`task.completed`. Desktop tickt jede Sekunde; für andere Oberflächen gibt es `tick_scheduler()`.
Die App muss laufen. Nach Ausfall gibt es maximal eine neue Ausführung statt nachgeholter Task-Fluten.
Ein blockierter/pausierter Task verhindert weitere Ausführungen desselben Zeitplans; Automations-Tasks
lösen keine weiteren `task.completed`-Automationsketten aus. Zeitpläne lassen sich pausieren/aktivieren.

Phase 6 implementiert damit begrenzte Autonomie über bekannte Abläufe und überprüfte Aktionen.
Eine allgemeine, unbeaufsichtigte Selbstverbesserung oder freie Ausführung beliebiger Programme ist
kein zugesicherter Bestandteil.

## Verifikation und Provider-Protokolle

- Gesamte Testsuite: `python -m unittest discover -s tests -v`
- Phase 4–6: `python -m unittest tests.test_automation -v`
- Native Gemini-Parts inklusive Signaturen werden unverändert zurückgesendet;
  Ollama verwendet `/api/chat` und strukturierte `tool_calls`.
- Referenzen: [Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling),
  [Ollama Chat API](https://docs.ollama.com/api/chat).
- Protokolltests verwenden synthetische SDK-/HTTP-Antworten. Ein erfolgreicher Test ersetzt keine
  Live-Prüfung mit dem tatsächlich konfigurierten Modell/API-Konto.

## Granulare Task-Policies (Phase 5/6)

**Tasks → Aufgabe erstellen** bietet drei KI-Modi, optionale Provider-Checkboxen und standardmäßig
**Alle verfügbaren Wissensquellen**. Erst „Wissensquellen einschränken“ zeigt die einzelnen Kategorien.
„Policy / Vorlage“ lädt gespeicherte Einstellungen und Teilziele; Speichern erstellt eine neue Aufgabe.
Bestehende Aufgaben werden dadurch nicht verändert. Die zusätzliche Freigabe für bestätigungspflichtige
Projektinhalte ist unabhängig von der KI-Auswahl; `LOCAL_ONLY` und `BLOCKED` bleiben verbindlich.

Die Policy wird im vorhandenen SQLite-Task-Datensatz gespeichert, beispielsweise:

```json
{
  "mode": "FALLBACK",
  "allowed_providers": null,
  "knowledge_sources": "ALL_AVAILABLE",
  "areas": {
    "backend": {"mode": "NEVER"},
    "frontend": {"mode": "ALLOWED", "allowed_providers": ["perplexity"]},
    "tests": {"mode": "NEVER", "knowledge_sources": ["PROJECT_KNOWLEDGE"]}
  }
}
```

- **NEVER** sperrt sämtliche CLS-Provider-Aufrufe, einschließlich lokalem Ollama. Wissen und lokale Tools
  bleiben verfügbar. **FALLBACK** prüft zuerst relevantes Wissen, Erfahrungen, vorhandene Dokumentation,
  gespeicherte Workflows und bekannte lokale Tool-Abläufe. Erst ein vom Core protokollierter Befund, dass
  dafür kein ausführbarer lokaler Ablauf vorliegt, gibt einen erlaubten Provider frei. Ein Modell kann
  diesen Befund nicht setzen. **ALLOWED** gestattet eine passende Provider-Auswahl ohne diesen Fallback-Schritt.
- Ohne Provider-Liste gilt das normale Routing. Eine leere Liste sperrt alle Provider. Netzwerkverbote
  haben Vorrang; eine explizite AI-Policy gibt nur zulässige AI-Aufrufe frei, keine Datei-/Terminalrechte.
- Ohne gespeicherte Policy bleibt das bisherige Verhalten erhalten: lokaler Provider bzw. externe
  Task-Freigabe. Knowledge bleibt `ALL_AVAILABLE`. Neue Dialog-Aufgaben starten mit `FALLBACK`.
- „Bereich hinzufügen“ benötigt Namen und konkretes Teilziel; optional begrenzt ein relativer Ordner
  die Datei-Tools. Teilaufgaben verwenden dieselbe Task-Zustandsmaschine, eigene unveränderliche
  Bereichszuordnung und ein gemeinsames Schritt-/Tool-/API-/Kostenbudget. Ohne Bereichsmodus oder
  Provider-Auswahl gilt der Task-Default. **Ohne Bereichs-Wissensregel gilt ausdrücklich ALL_AVAILABLE**,
  auch bei eingeschränktem Task-Wissen. Bereichsregeln ohne konkrete Teilziele stoppen mit Informationsbedarf.
- Der Core prüft Policy, Provider, aktuelle Privacy und bisherigen Kontext vor jedem nativen Aufruf,
  jedem Berateraufruf und jedem Provider-Fallback. Gesperrte Aufrufe erscheinen als `policy_blocked` im
  Action Trail. Andere lokale Aktionen bleiben ausführbar. Nach einem verweigerten benötigten AI-Schritt
  genügt bloßes Lesen nicht für einen Erfolg; Änderungen brauchen weiterhin Build und Tests.

### Wissensauswahl und Herkunft

`ALL_AVAILABLE` erlaubt die relevanten und zugänglichen Quellen; es erzwingt keine ungezielte Vollübernahme.
Die vorhandene Textsuche, Trust-Stufen, Versionen, Konfliktpartner, Projekt-Isolation und Privacy gelten weiter.
Der Task-Kontext und Action Trail enthalten Kategorie, Referenz und bei Knowledge-Einträgen Version/Herkunft.
Das gemeinsame Retrieval-Budget begrenzt Quellen und relevante Ausschnitte; Details siehe Context Minimization.

| Kategorie | Bestehende Quellen |
|---|---|
| `CLS_KNOWLEDGE` | globales Knowledge |
| `PROJECT_KNOWLEDGE` | projektgebundene Fakten, Projektbeschreibung/-anweisungen, Code-Datei-Tools |
| `EXPERIENCE` | verifizierte Abschlüsse desselben Projekts, mit Privacy-Prüfung ihrer Herkunft |
| `DOCUMENTATION` | Dokumenteinträge und relevante lokale Textdokumente; Datei-Tools für `.md/.txt/.rst/.pdf/.docx/.markdown` |
| `EXTERNAL_RESEARCH` | freigegebene Knowledge-Einträge mit Web-Provenance und erlaubte Recherche-Berater |
| `OTHER_RELEVANT_KNOWLEDGE` | relevante, vom Nutzer gespeicherte persönliche Fakten |

Dokument-/Web-Provenance hat bei der Kategorie Vorrang vor globaler oder projektgebundener Ablage.
Quellenbeschränkungen gelten auch für Lese-/Such-Tools. Unzuordenbare Befehlsausgaben werden bei
Einschränkungen der Datei-Quellen nicht in den Modellkontext übernommen. Befehle bleiben ausdrücklich
vertrauenswürdiger Projektcode mit den oben beschriebenen OS-Grenzen.

### Ausführungsgrenzen

Ohne AI kann CLS passende gespeicherte Workflows, die bekannten Ziele „Tests ausführen“ / „Build und Tests
ausführen“ und belegbare „Was weißt du über …?“-Abfragen ausführen. Für beliebige neue Implementierungsziele
existiert kein allgemeiner lokaler Codegenerator: ohne erlaubten ausführbaren Plan bleibt der Task blockiert.
Ein ausschließlich erlaubter Textberater wie Perplexity kann Beratung liefern; seine Prosa wird nicht in
Tool-Aufrufe umgewandelt. Ohne passenden Workflow oder nativen Tool-Provider bleibt dann Informationsbedarf.
Erst alle erfolgreich geprüften Teilaufgaben schließen eine Gesamtaufgabe ab. Phase 7 ist nicht enthalten.

Gezielte Tests: `python -m unittest tests.test_task_policy -v`. Diese verwenden synthetische Provider;
sie belegen keine Live-Inferenz bei Gemini, Perplexity oder Ollama.

## Selektives Retrieval und Context Minimization (Phase 5/6)

`ContextManager.retrieve_task` kombiniert die bestehende FTS-/Textsuche mit Projekt-/Privacy-/Quellenfiltern.
`core/context_minimizer.py` wählt passende Sätze/Zeilen und bei langen Absätzen kurze Trefferfenster aus.
Dadurch bleiben auch relevante Stellen am Dateiende auffindbar. Duplikate werden vor dem Senden entfernt;
eine gefundene Knowledge-Datei wird nicht vollständig als Standardkontext übernommen.

Die Grenzen stehen in `config/knowledge.py`: höchstens **8 Quellen**, **700 Zeichen Text je Quelle** und
**10.000 Zeichen für die serialisierten Referenzen einschließlich Herkunft**. Eine Suche betrachtet höchstens
100 Knowledge-Treffer; weitere passende Treffer werden als `not_retrieved` ausgewiesen. Die Dateisuche ist
weiter auf den sicheren Projektordner und 300 besuchte Einträge begrenzt. Trust, Version, Änderungsdatum
und kompakte Provenance bleiben nachvollziehbar. Unzugängliche Konfliktpartner werden nicht als Referenz
exportiert. `ALL_AVAILABLE` bedeutet Zugriff auf zulässige Quellen, keinen vollständigen Export.

Vor nativen Modellaufrufen wird der Kontext zum aktuellen Planschritt bzw. der letzten Nutzerinformation
gebildet. Berater bekommen ihre konkrete Frage mit dem ermittelten Prüfbedarf. Nur die aktuelle native
Tool-Runde samt Call-IDs/Signaturen und ein kurzer Ausführungsstand werden weitergereicht. Große
Tool-Texte bis 1.200 Zeichen bleiben für die Ausführung vollständig erhalten; größere Texte werden
auf relevante Ausschnitte begrenzt (ohne Treffer auf einen begrenzten Anfang). `read_file` akzeptiert
optional `query` für eine gezielte Stelle. Alte Tool-Inhalte werden nicht erneut angehängt. Bei mehr als
40.000 serialisierten Nachrichtenzeichen wird vor dem Provider-Aufruf blockiert und eine kleinere Aufgabe
verlangt; native Signaturen werden nicht abgeschnitten. Automatischer Chat-Knowledge-Kontext verwendet
ebenfalls die Ausschnittsauswahl; externe Chat-History/Fakten werden begrenzt.

**Einfache Wissenslücken:** `missing_knowledge`, `low_confidence`, `conflicting_knowledge`,
`freshness_unverified` (älter als 365 Tage), `context_budget`; fehlende lokale Ausführungsfähigkeit wird
separat als `missing_local_plan` protokolliert. Das sind regelbasierte Hinweise, keine semantische
Vollständigkeits- oder Wahrheitsprüfung. Eine unsichere/widersprüchliche Wissensfrage wird nicht automatisch
als lokal gelöst abgeschlossen. Auch ALLOWED prüft vorhandene lokale Fähigkeiten zuerst; es benötigt
keine Fallback-Freigabe als Bedingung für erlaubte AI-Aufrufe.

**Antwortprüfung:** Beraterantworten und reine Textantworten des Task-Providers werden gegen die tatsächlich
mitgesendeten Knowledge-Ausschnitte verglichen. Neue Antworten bleiben `CANDIDATE`; einfache Zahlen-/Negations-
Widersprüche werden über das bestehende Konfliktsystem markiert. Unverändert bestätigte Einträge werden
nicht überschrieben oder durch ein identisches AI-Ergebnis umklassifiziert. Abgeleitete Kandidaten
behalten Belegreferenzen/Versionen; spätere Privacy-Änderungen gelten auch nach ihrer Bestätigung. „Kein Konflikt gefunden“
bedeutet weiterhin ungeprüft. Offene erkannte Antwortkonflikte verhindern einen erfolgreichen Task-Abschluss.
`AUTO_CANDIDATES=False` verhindert weiterhin automatisches Speichern; dann bleibt ein erkannter Konflikt
als Task-Blocker bestehen. Reine strukturierte Tool-Pläne werden über Ausführung, Build und Tests geprüft.

**Kompakter Action Trail:** `knowledge_selected` enthält Quellenanzahl, Kontextgröße, Referenzen sowie
Zahlen für Privacy-, Quellenpolicy-, Duplikat- und Budgetausschlüsse. `eligible_entries`, `matching_entries`
und `unrelated_entries` zählen Knowledge im erlaubten Projektscope/Trust-Scope; `not_retrieved` kennzeichnet
Treffer außerhalb des Suchlimits. Ausschlüsse zählen tatsächlich geprüfte Kandidaten, keine hochgerechneten
Dateiinhalte. Volltexte werden dafür nicht geloggt. `ai_call` protokolliert Provider, Modus und Bereich;
`ai_verification` protokolliert das Vergleichsergebnis und ggf. Kandidat-/Konflikt-IDs.

**Policies bearbeiten:** Auf der Task-Karte öffnet „Policy ändern“ den vorhandenen Dialog. Task- und
Bereichsregeln lassen sich atomar ändern, solange keine AI-/Tool-Aktion ausgeführt wurde. IDs und Teilziele
bleiben erhalten; ein Neustart lädt die neue Revision. Bereits ausgeführte Tasks können über „Policy / Vorlage“
neu angelegt werden, damit frühere Aktionen nicht nachträglich einer anderen Policy zugeordnet werden.

Regressionstests: `python -m unittest tests.test_context_minimization -v`.
Keine Erweiterung um Phase 7, Embeddings oder autonome Hypothesenbildung.

## Experience → Procedural Learning: vorbereitete Schnittstellen

Die Grundlage nutzt **Experience, Knowledge, Projects, Trust/Provenance und Context Manager**
in derselben SQLite-Datenbank. Es gibt keinen zusätzlichen Memory-Speicher.
Maßgeblich ist der aktuelle Code. Die frühere Architektur-PDF dient als Hintergrund.
Der vorhandene Action Trail bleibt die Quelle der Episode.

### Jetzt implementiert

- Neue Experiences enthalten weiterhin `steps`, `errors`, `solutions`, `result`, `verified` und
  `status`. `schema_version=2` ergänzt eine chronologische `timeline` mit Action-IDs, Zeitpunkten,
  Aktionsarten und beobachteten Ergebnissen sowie einen Snapshot von Verification und Provenance.
  `timeline_complete=false` kennzeichnet die Begrenzung auf die letzten 5000 Aktionen.
  Alte Experiences bleiben unverändert lesbar; ihnen wird keine fehlende Evidenz hinzuerfunden.
- `CLSCore.propose_strategy(...)` speichert einen **explizit formulierten** Reflexionsvorschlag
  als Knowledge-Eintrag mit `kind="strategy"`. Kein Task-Abschluss erzeugt automatisch Regeln.
- Strategie-Metadaten enthalten Anwendungsbedingungen, Begründung, ursprünglichen Scope,
  Episode-Referenzen samt SHA-256-Fingerprint, `status="CANDIDATE"`, `confidence=null`
  (noch nicht bewertet) und `verification=null`. Knowledge-Trust beginnt bei `CANDIDATE`.
  Provenance und initiale Version liegen in den vorhandenen Knowledge-Tabellen.
- Doppelte Task-IDs zählen einmal. Der Scope wird aus den Episoden übernommen. Gemischte Projekte
  oder Projekt-/Global-Belege werden abgelehnt. Projektwissen wird damit nicht verallgemeinert.
- Auch erfolgreiche Wiederholung und zusätzliche Quellen geben einen Vorschlag noch nicht frei.
  Der allgemeine Quellenzähler zählt Experiences nicht als unabhängige Bestätigung.
  Knowledge-Bestätigung und Inhaltsänderungen sind für Strategien gesperrt; neue Erkenntnisse
  benötigen einen neuen Vorschlag mit Belegen. Veraltete Kandidaten können stillgelegt werden.
- Knowledge-Verwaltung und Detailansicht zeigen Kandidaten und Herkunft. Alle Strategien bleiben
  aus Chat-, lokalem Antwort- und Task-Kontext ausgeschlossen, auch bei indirekt verändertem Trust.
  Nach Projektlöschung bleiben erhaltene Strategien `RETIRED`/`OUTDATED` und behalten den
  ursprünglichen Projektscope in ihren Metadaten. Sie werden nicht zu global gültigen Regeln.
- Schema v4 ergänzt lediglich eine JSON-Spalte an `knowledge_entries`; bestehende Daten bleiben erhalten.

Beispiel über die Core-API (keine automatische Ausführung):

```python
candidate = cls.propose_strategy(
    "Bei vergleichbaren Importfehlern zuerst Methode B prüfen.",
    experience_ids=[completed_task_id],
    applicability="Dasselbe Projekt, derselbe Importer und dasselbe Fehlermuster",
    rationale="Im Action Trail scheiterte A; B war danach erfolgreich. Ursache noch zu prüfen.",
)
# candidate['trust'] == 'CANDIDATE'
# candidate['strategy']['confidence'] is None
```

### Späterer Ausbauvertrag

```text
Experience → Reflection / Pattern Detection → Candidate Strategy
           → Verification / Repeated Success → Trusted Procedural Knowledge
           → Context Manager → zukünftige ähnliche Tasks
```

Reflection und Verifikation sind **noch nicht implementiert**. Ein zukünftiger Verifikationsschritt
muss die tatsächliche Anwendung einer Strategie von bloß ähnlichen erfolgreichen Tasks unterscheiden,
Gegenbeispiele und unabhängige Wiederholungen berücksichtigen und die Verifikation mit Prüfer,
Begründung, Belegen, Zeitpunkt und Strategieversion speichern. Eine feste Anzahl erfolgreicher Tasks
allein ist kein Nachweis. `verified` an einer Episode bestätigt den bisherigen Task-Prüfpfad; bereits
Lesen kann dort erfolgreich sein. Daraus folgt keine bestätigte Kausalität oder Allgemeingültigkeit.

Erst dieser Schritt darf einen zusätzlichen Status wie `VERIFIED` und begründete Confidence setzen
und den Knowledge-Trust kontrolliert anheben. Die heutige Kandidaten-API darf diesen Übergang nicht
übernehmen. Für eine globale Strategie aus Projekterfahrungen ist eine gesonderte Prüfung des
Geltungsbereichs nötig; der ursprüngliche Projektbezug muss erhalten bleiben.

Vor einer künftigen Kontextfreigabe müssen aktueller Episoden-Fingerprint, vollständige Belege,
Trust, Strategieversion/Status, Anwendungsbedingungen, Konflikte und Scope erneut geprüft werden.
Geänderte oder fehlende Belege entwerten die Verifikation. Herkunftsreferenzen haben die Form
`derived:experience:<task-id>@<fingerprint>`. Privacy muss wie bei anderen Ableitungen rekursiv bis
zu den Task-Quellen geprüft werden; eine Freigabe des Knowledge-Eintrags ersetzt keine Quellfreigabe.
Der Context Manager muss zusätzlich die vorhandenen Task-Policies und Kontextbudgets einhalten.
Vorgehensweisen bleiben Referenzmaterial und erweitern keine Tool-Berechtigungen.

Gezielte Regressionen: `python -m unittest tests.test_procedural_foundation -v`.


## Flexible Provider und kontrollierte Wiederverwendung (bestehende Phasen 1–6)

### Provider konfigurieren

**Provider → Konfigurieren** verwaltet Enabled, Modell und Capabilities. Ein neuer Key wird ausschließlich
in der zentralen `.env` gespeichert (Dateirechte unter POSIX: 0600); leer lässt den bisherigen Key
unverändert, „entfernen“ löscht seinen Wert. Key-Werte erscheinen weder in Settings-Antworten noch
in SQLite oder Logs. Die bekannten Variablen stehen leer in `.env.example`:
`GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `COMETAPI_API_KEY`.

Groq, OpenRouter und CometAPI sind über `BaseProvider`/Registry integriert und verwenden einen
gemeinsamen Chat-Completions-Adapter mit nativen Tool-Calls. Ihre Defaults sind **deaktiviert und ohne
vorausgewähltes Modell**: erst Key und einen im eigenen Account verfügbaren Modellnamen konfigurieren.
Capabilities sind konfigurierbar; `research` ist an keinen bestimmten Anbieter gebunden.
`web_search` setzt ein entsprechend geeignetes Provider-Modell voraus; die Konfiguration erzeugt
keine zusätzliche Suchfunktion. Perplexity bleibt ein Text-/Recherche-Provider; native Tasks benötigen
weiterhin ein toolfähiges Modell. Lokaler Status ist eine Eigenschaft des Adapters: Externe Endpunkte
können nicht durch ein Settings-Feld als lokal deklariert werden. Ollama behält seine Loopback-/Cloud-Sperre.

API-Grundlagen: [Groq-Kompatibilität](https://console.groq.com/docs/openai),
[OpenRouter API](https://openrouter.ai/docs/api/reference/overview),
[CometAPI Quick Start](https://www.cometapi.com/en/quick-start).

„Konfiguriert“ bedeutet **keinen geprüften Live-Zugriff**. Erreichbarkeit, Berechtigungen und
Modellverfügbarkeit werden beim tatsächlichen Request geprüft. HTTP-/Protokollfehler, leere Antworten,
fehlformatierte native Calls und unvollständige Chat-Completions sind Fehler. Antwortvalidierung erfolgt
zusätzlich im Core; Fehlertexte werden nicht als Antworten oder erfolgreiche Task-Ergebnisse gespeichert.

### Auswahl, Priorität und Fallback

Im Chat: **Automatic** oder einen einzelnen Provider wählen; „Nur lokale Provider“ ist zusätzlich möglich.
Manuelle Auswahl ist strikt: Scheitert dieser Provider oder fehlt die Capability, erfolgt kein versteckter
Wechsel zu einem anderen Anbieter. Automatic folgt den konfigurierten Capability-Prioritäten und dem
vorhandenen Capability-Fallback des Routers. Nicht gelistete passende Provider folgen in Registry-Reihenfolge.

Task-Policies erweitern die bisherigen Felder optional um:

```python
ai_policy = {
    "mode": "ALLOWED",
    "allowed_providers": ["ollama", "groq", "openrouter"],
    "preferred_providers": ["ollama", "groq"],
    "required_capability": "coding",
    "selected_provider": None,  # z. B. "groq" für feste manuelle Auswahl
    "local_only": False,
    "allow_external": True,
}
```

Bereiche übernehmen nicht gesetzte Routing-Felder. `local_only=True` oder `allow_external=False` am
Task bleiben auch für Bereiche verbindlich. `allow_external` erlaubt den Provider; der bestehende
Task-Schalter `allow_external` beim **Erstellen des Tasks** erteilt getrennt davon die Zustimmung für
`USER_CONFIRMATION_REQUIRED`-Projektinhalte. `LOCAL_ONLY`/`BLOCKED` werden durch keinen Schalter aufgehoben.

Registry und bestehende Aufrufschleifen filtern Enabled, Konfiguration, Capability, manuelle Auswahl,
Präferenz und Task-Policy. Privacy/Safety und bereits verwendete Referenzen werden vor jedem Request
neu geprüft. Fallback zählt jeden tatsächlichen Versuch zum bestehenden API-Budget. Nach einer
abgeschlossenen Tool-Runde kann ein nativer Provider wechseln; er bekommt den aktuellen Ausführungszustand
und beobachtete Ergebnisse, niemals fremde Signaturen/Call-IDs. Ausgeführte Aktionen werden dadurch nicht
im Core erneut ausgeführt. Bereits gespeicherte Workflows, Scheduler und Decision Engine bleiben bestehen.

### Kontrolliertes Kennenlernen

**Memory → Kennenlernen** oder `Lernvorschlag: …` erstellt einen persönlichen `CANDIDATE`, standardmäßig
`LOCAL_ONLY`. Interessen, Arbeitsweise, Kenntnisse, Ziele und Tools können so ausdrücklich vorgeschlagen
werden. Normale Gespräche werden nicht automatisch persönliches Memory. **Bestätigen** macht einen
Vorschlag nutzbar; **Bearbeiten**, **Löschen** und Privacy-Auswahl bleiben im vorhandenen Memory-Bereich.
`Merk dir …` und manuelles Hinzufügen bleiben ausdrückliche Speicheraufträge und sind lokal voreingestellt.

Die bestehende Long-Term-Memory-Persistenz trägt Trust, Kategorie, Provenance, Version/Änderungsverlauf
und Privacy. Nur bestätigte, zulässige Fakten kommen in den Kontext; Export verlangt `SAFE_FOR_EXTERNAL`.
Alte Memory-Daten bleiben kompatibel und behalten ihre bisherige Interpretation. Neue Chatbeiträge tragen
ihren Projektscope. Alter unzugeordneter Verlauf wird nur ohne aktives Projekt verwendet. Wird persönliches
Wissen gelöscht oder seine Exportfreigabe widerrufen, wird davon abhängiger Antwortverlauf nicht extern gesendet.
Abgeleitete Knowledge-Kandidaten referenzieren verwendete Memory-/Knowledge-Versionen und ihren
Projektscope. Änderungen oder Löschungen der Belege sperren ihre weitere Verwendung entsprechend;
eine identische AI-Antwort ergänzt keinen unabhängigen Beleg und erzeugt keine Selbstreferenz.

### Projects als Referenzquelle

Im Task-Dialog **Relevante Referenzprojekte suchen** liefert eine lokale, begrenzte Stichwortsuche über
Projektmetadaten und ausdrücklich freigegebene Belege. Treffer sind Vorschläge und zunächst nicht ausgewählt.
Ein Task speichert ausgewählte IDs in `reference_project_ids`; ohne Auswahl gilt ausschließlich sein
bisheriger Scope. Quellprojekte können auch archiviert sein.

Zusätzlich muss jeder Knowledge-Eintrag in seiner Detailansicht bzw. jede Experience unter **Memory**
ausdrücklich als Referenz freigegeben sein. Fremdes Knowledge wird nur mit `CONFIRMED`/`SUPPORTED` und ohne
offenen Konflikt berücksichtigt; Experiences brauchen weiterhin einen verifizierten Abschluss.
Der Context Manager liefert relevante Ausschnitte im bestehenden Budget, Herkunftsprojekt und
`reference_only`-Kennzeichnung. Experiences sind historische Beobachtungen, keine allgemeinen Regeln.
Alte Projektdateien werden nicht automatisch kopiert, importiert oder ausgeführt. Aktuelle Projektdateien,
Knowledge, Aufgaben und Action Trail bleiben ihre vorhandenen getrennten Quellen.

Widerrufene Referenzfreigaben, geänderte Knowledge-Versionen, gelöschte Projekte und veränderte Privacy
sperren auch bereits verwendete Referenzen vor dem nächsten Provider-Aufruf. Ein nachträgliches Umbenennen
von Trust oder Scope hebt diese Grenzen nicht auf. Projektlöschung stellt erhaltenes Wissen auf `OUTDATED`,
bewahrt `origin_project_id` und verhindert eine normale Wiederfreigabe als globales Wissen.

### Projekt-Speichermodi

**Projects** bietet pro Projekt:

| Modus | Verhalten nach einem passenden verifizierten Task |
|---|---|
| Nie | Kein automatischer Project-Knowledge-Vorschlag |
| Nachfragen (Default) | Task-Karte bietet „Ja, als Kandidat“, „Nein“, „Nur Erfahrungen speichern“ |
| Automatisch (Kandidaten) | Lokalen Project-Knowledge-Kandidaten speichern, niemals eine bestätigte Regel |

Die Auswahl ist deterministisch und bewusst begrenzt: abgeschlossener, verifizierter, nicht mehr dirty
Task mit Ergebnis und tatsächlichen Schreib-/Edit-/Build-/Test-Tools; reine Chats und bloßes Lesen lösen
keine Projektspeicherung aus. Gespeichert wird eine begrenzte historische Task-Beobachtung mit
Experience-Fingerprint/Provenance, nicht der Projektcode. Privacy und aktuelle Belege werden vor dem
Speichern erneut geprüft. Experience und Action Trail bleiben unabhängig davon erhalten, auch bei „Nein“.
Schema v5 ergänzt Einstellungen/Referenzfreigaben/Herkunft an bestehenden Tabellen; keine neue Memory-Datenbank.

### Bewusste Grenze

Die bereits implementierten chronologischen Experiences und Strategiekandidaten werden weiterverwendet.
Strategien bleiben `CANDIDATE`, mit Scope, Provenance, Evidence, Trust, Status und noch nicht bewerteter
Confidence. Sie sind weder normale Kontextdaten noch ausführbare Regeln. Es gibt weiterhin **keine**
autonome Reflection, Pattern Detection, Strategieableitung/-verifikation, automatische Confidence,
Trusted Procedural Knowledge, automatische Strategy-Reuse, Agent-Hierarchie oder Phase 7.

Gezielte Tests: `python -m unittest tests.test_flexible_cls tests.test_procedural_foundation -v`.
Die Tests verwenden synthetische Provider-Protokolle und eine lokale HTTP-Fixture. Sie behaupten keine
Live-Inferenz oder Modellverfügbarkeit bei externen Anbietern. UI-Logik wird durch die vorhandenen Stubs
abgedeckt; native Desktop-Layouts können mit Tk unter Xvfb ohne Provider-Aufruf geprüft werden.


## Lokale Aktionen, Ergebnisse und Workspace

Die vorhandene Kette lautet: Planner/Decision Engine → Task/Workflow → ToolRegistry → Safety →
Ausführung/Zustandsprüfung → `task.tool_results` → deterministische Ergebnisanzeige. Der Planner verwendet
Wort-/Aktionszuordnungen und gemeinsame Argumentrollen (Quelle, Ziel, Verzeichnis, Inhalt), keine
Dateinamen-Sonderfälle oder Satz-Regex-Sammlung. Er ist eine begrenzte Grammatik, kein allgemeines
Sprachmodell: unbekannte Ziele bleiben beim vorhandenen Agenten, unvollständige erkannte Aktionen fragen
nach. Pfade mit Leerzeichen und wörtliche Inhalte bitte in Anführungszeichen setzen.

Beispiele (in einem aktiven Projekt):

- `Lies note.txt` oder `Lies note.txt aus "D:\Desktop\Projekte"`
- `Suche in "D:\Desktop\Projekte" nach *.txt`
- `Erstelle test.txt mit "HELLO" und lies die Datei danach wieder aus`
- `Suche note.txt und lies anschließend den Inhalt`
- `Ändere "AAA" zu "BBB" in note.txt`
- `Kopiere note.txt nach backup.txt` / `Verschiebe note.txt nach archive/note.txt`
- `Existiert note.txt?` / `Wie groß ist note.txt?` / `Zeig mir die Dateien im Projekt`
- `Öffne den Projektordner` / `Öffne note.txt`
- `Kopiere "Hallo CLS" in die Zwischenablage`
- `Kopiere den Inhalt von note.txt in meine Zwischenablage`
- `Schreibe meinen Clipboard-Inhalt in clipboard.txt`

„Erstelle“ ohne Inhalt erzeugt eine leere Datei. Bestehende Dateien können nach Bestätigung durch
`write_file` ersetzt werden; Copy/Move überschreiben keine vorhandenen Ziele. Zielordner müssen
bereits existieren. Eine eigenständige Delete-Funktion wurde nicht ergänzt.

Projektpfade müssen absolut sein und auf vorhandene Ordner zeigen. Sie werden bei der Konfiguration
kanonisiert und beim Task-Start als Workspace gespeichert. Relative Tool-Pfade beziehen sich immer darauf,
niemals auf das Startverzeichnis von `main.py`. Windows-Laufwerks-/UNC-Pfade werden auf Windows geprüft;
auf anderen Betriebssystemen werden sie nicht in scheinbar relative Dateinamen umgedeutet. Beide Seiten
von Copy/Move passieren Safety; Traversal, Symlinks/Junctions, Hardlinks, sensible Dateien und Gerätepfade
bleiben gesperrt. Betriebssystem-Öffnen benötigt eine Execute-Bestätigung und meldet nur die Übergabe an
das Betriebssystem, keine behauptete Anzeigeprüfung.

Im Projektdialog lässt sich bei leerem Pfad ausdrücklich ein eigener Workspace erzeugen. Basis:
`config.paths.WORKSPACE_BASE` (standardmäßig `~/CLS/workspaces`). Der Name wird Windows-tauglich bereinigt;
ein existierender automatisch berechneter Ordner wird nicht stillschweigend übernommen. Ein expliziter
Workspace hat immer Vorrang, auch wenn die automatische Option aktiviert ist.

Alle ausgeführten Tool-Ergebnisse bleiben mit Aufruf, Argumenten und Schritt im vorhandenen Task-JSON.
Die Abschlussanzeige verwendet diese Beobachtungen, keine frei erfundene Modell-Zusammenfassung.
Ausgaben bleiben begrenzt und Kürzungen werden angezeigt. Workflow-Argumente können vorherige Ergebnisse
referenzieren, z. B. `{"step": 0, "field": "matches"}` als `path` eines Leseschritts. Listen benötigen genau
einen Treffer; leere, mehrdeutige oder gekürzte Ergebnisse führen zu einer Rückfrage statt einer geratenen
Dateiauswahl. Jeder aufgelöste Pfad wird anschließend erneut durch Safety geprüft.

Build/Test-Aktionen verwenden ausschließlich konfigurierte Commands. Ohne expliziten Command wählt CLS
Python-Tests bei vorhandenem `tests/`-Ordner und Python-Syntaxkompilierung bei Python-Projektmerkmalen.
Ohne passende Merkmale wird kein Erfolg behauptet. Ergebnisdaten enthalten Command, argv, Workspace,
Exit-Code, Timeout und die zusammengeführte stdout/stderr-Ausgabe. `ask_ai` bleibt in der bisherigen
Agent-/Provider-Policy; Ergebnisdaten unterscheiden lokale Tools, lokale Modelle und externe Provider.
Gespeicherte lokale Workflows führen weiterhin kein `ask_ai` aus.

Clipboard verwendet Tk aus der vorhandenen Desktop-Anwendung; Worker kommunizieren über eine Queue
mit deren UI-Thread. Ohne Desktop-Sitzung schlägt die Funktion ausdrücklich fehl. Nach Schreiben wird
zurückgelesen und verglichen. Clipboard-Tasks, ihre Erfahrungen und daraus geschriebene Dateien bleiben
lokal; ein späterer Provider-Fallback darf diese Inhalte nicht extern senden. Erkannte lokale Chat-Aufträge
nutzen denselben Task-Pfad. Bestätigungen und spätere Ergebnisse erscheinen im vorhandenen Aufgabenbereich.

### Ergänzungen der Basis-UX

Die gleichen Registry-/Safety-/Task-Schnittstellen unterstützen außerdem:

- `Erstelle Ordner Archiv` (ein Ordner; Elternordner muss vorhanden sein)
- `Benenne Archiv/bericht.txt in neu.txt um` (gleicher Ordner, kein Überschreiben)
- `Liste Dateien in Archiv` / `Zeige Dateien im Projekt` (direkte Dateien **und** Ordner;
  bis zu 100 erlaubte Einträge, gekürzte Ergebnisse werden gekennzeichnet)
- `Lösche Archiv/neu.txt` (endgültig, einzelne reguläre Datei, immer konkrete Bestätigung;
  keine Ordner, Links, geschützten Pfade oder Workspace-Löschung)
- `In welchem Projekt bin ich?` / `Zeige den aktuellen Workspace`
- `Wechsle zu Projekt "Mein Projekt"` (im Chat; bestehende Tasks behalten ihren Workspace)
- `Uhrzeit`, `Datum`, `Zeige Systeminfos`, `Zeige Speicherplatz`, `Zeige laufende Prozesse`.
  Diese Beobachtungen bleiben lokal. Prozesslisten enthalten nur PID und Namen, keine
  Kommandozeilen/Umgebungsvariablen. Die OS-Abfrage verwendet festes `tasklist`/`ps` ohne Shell.
  Netzwerkstatus und weitere Desktop-Automation sind nicht enthalten.

**Abbrechen** im Aufgabenbereich setzt `CANCELLED` und verwirft offene Bestätigungen.
Die gerade laufende Aktion darf noch enden und ihr Ergebnis sichern; danach startet kein weiterer
Schritt. Änderungen werden nicht zurückgerollt. Dies gilt auch für bestehende Aufgabengruppen.
Ein abgebrochener Task lässt sich nicht fortsetzen. Ein wiederkehrender Zeitplan bleibt aktiv und
kann später einen neuen Task erzeugen; zum dauerhaften Stoppen den Zeitplan deaktivieren.

Vorübergehende Betriebssystemfehler (`EINTR`, `EAGAIN`, `ETIMEDOUT`) bei lesenden Tools dürfen innerhalb
von `MAX_RETRIES_PER_STEP` erneut versucht werden. Jeder Versuch bleibt im Ergebnis-/Aktionsverlauf.
Schreiboperationen, Desktop-Öffnen und Kommandos werden nicht automatisch wiederholt.

## Neue Desktop-Oberfläche (Electron)

Die neue Oberfläche verwendet **Electron, React, TypeScript, Tailwind CSS v4, shadcn/Radix,
lucide-react und TanStack Table**. Sie nutzt den bestehenden Python-Core und dieselben Safety-,
Trust-, Project- und Memory-Systeme.

- Start aus dem Quellcode: `npm ci --prefix desktop-shell`, danach `python main.py`.
- Bisherige Tk-Oberfläche als Rückfalloption: `python main.py --legacy-ui`.
- Windows-Installer bauen: `powershell -ExecutionPolicy Bypass -File desktop-shell/scripts/build-windows.ps1`.
- **[Design, Architektur, Bedienung, Datenübernahme und Build-Anleitung](docs/desktop-ui.md)**.

Die Browser-Vorschau enthält klar gekennzeichnete, isolierte Beispieldaten. Die installierte
Desktop-App öffnet echte lokale Daten und benötigt keinen Webserver.
