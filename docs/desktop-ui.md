# CLS Desktop · Electron + React

## Bestehende UX: konkrete Probleme

Die bisherige Tk-Oberfläche ersetzte beim Navigieren alle Widgets. Filter, Scrollpositionen und
angefangene Eingaben gingen dabei häufig verloren. Wissen, Projekte, Memory und Tasks erschienen
überwiegend als lange Kartenlisten; Spaltenvergleich, Sortierung und eine zentrale Suche fehlten.
Viele gleich gewichtete Aktionen konkurrierten um Aufmerksamkeit. Projekt/Workspace und blockierte
Aufgaben waren nicht durchgehend sichtbar. Theme-Wechsel war eine Python-Konfigurationsänderung.

## Vorbilder und Lizenzen

Recherchiert am 2. Oktober 2026. Öffentliche Seiten und Repository direkt abgerufen; der integrierte
Suchdienst war nicht authentifiziert. Behance-Detailseiten und Figma lieferten HTTP403. Dribbble
lieferte keinen auswertbaren Inhalt; Mobbin, Refero und Page Flows waren nur auf Katalogebene zugänglich.
Keine Screenshots oder Layoutbehauptungen über nicht zugängliche Entwürfe.

Vier gewählte Referenzen:

1. [shadcn-admin](https://github.com/satnaing/shadcn-admin): bevorzugte technische Basis/Inspiration;
   Radix/shadcn-Primitives für Buttons, Dialoge und Menüs adaptiert, Vite/React-Struktur, Datenansichten.
   MIT-Lizenz in `desktop-shell/THIRD_PARTY_NOTICES.md`. Keine Demo-Auth-, Analytics- oder SaaS-Module übernommen.
2. [Linear](https://linear.app/docs/conceptual-model): Workspace stets sichtbar, kompakte Navigation,
   Aufgaben als zentraler Arbeitsgegenstand. Kein Nachbau von Produktmarken oder Grafiken.
3. [VS Code](https://code.visualstudio.com/docs/getstarted/userinterface): feste Navigation, großer
   Arbeitsbereich, Statuszeile und tastaturorientierter Einstieg.
4. [shadcn Sidebar Blocks](https://ui.shadcn.com/blocks/sidebar): Navigation in Gruppen,
   einklappbare Sidebar, wiederverwendbare Oberflächenbausteine.

Die eigene Farbwelt verwendet Graphit, Violett und sachliche Grün-/Amber-Statusfarben. Light/Dark/System
werden lokal gespeichert. Systemschrift (unter Windows Segoe UI), Monospace nur für Pfade/Ergebnisse.
8px-Abstandsgrundraster, übliche Eingaben und Buttons mindestens 44 px hoch, sichtbarer Tastaturfokus,
Radix-Fokusführung, Escape und reduzierte Bewegung. Automatisierte Kontrastprüfungen ergänzen die
Sichtprüfung; sie garantieren keine vollständige Barrierefreiheit.

## Navigation und Komponenten

- **Übersicht:** echte Task-/Wissenszahlen, Freigaben, aktueller Workspace und beobachtete Aktivität.
- **Chat:** Routing/Provider-Auswahl, lokale Einschränkung, echte Antworten und Task-Verknüpfung.
- **Aufgaben:** TanStack-Tabelle, Statusfilter, Detail/Ergebnisse, gebundene Bestätigung, Pause/Cancel,
  Informationen ergänzen, Workflow-Editor und Zeitpläne.
- **Projekte:** Karten/Tabelle, Anlegen/Bearbeiten/Archivieren/Löschen, aktive Auswahl, Speichermodus.
- **Wissen:** Suche/Trustfilter, Quellen/Versionen/Strategiekandidaten, Dokumentimport, Widersprüche.
- **Memory:** persönliche Kandidaten bearbeiten/bestätigen/löschen, Privacy, Erfahrungen mit Timeline,
  explizite Strategie-Vorschläge. Keine autonome Ableitung, Freigabe oder Anwendung.
- **Aktivität:** filterbarer Action Trail, Details aus dem tatsächlichen Core.
- **Provider:** Modelle, Schlüssel ersetzen/entfernen, Capabilities, Enabled, Prioritäten.
- **Einstellungen:** Theme, Tastaturhilfe, Datei-Privacy und lokale Konfiguration.

`src/app.tsx` enthält die Desktop-Hülle und Command Palette. `src/components` enthält gemeinsame
Tabellen, Formulare und Dialoge; `src/pages` die Fachansichten. `src/lib/api.ts` ist die einzige
Renderer-Verbindung. Tabellen behalten Suche, Spalten und Sortierung; persönliche Inhalte werden
nicht als UI-Präferenzen gespeichert. Die globale Suche öffnet Navigation, Aufgaben und Wissen.
Die aktuelle Verwaltungs-Liste ist begrenzt (500 Wissenseinträge, 200 Aktionen); die UI ersetzt
keine unbegrenzte Volltextsuche über alle historischen Daten.

## Architektur und Sicherheit

```text
React → schmale Preload-API → validierter Electron-IPC-Sender
      → JSON-lines über stdin/stdout → DesktopBridge-Allowlist → CLSCore
      → bestehende Tasks / Tools / Safety / Knowledge / Memory / SQLite
```

Kein HTTP-Server in der installierten App. Renderer: `nodeIntegration:false`, `contextIsolation:true`,
`sandbox:true`, lokale `cls://app`-Origin, CSP, keine neuen Fenster/Navigation oder Browser-Permissions.
Grundlage: [Electron Security Checklist](https://www.electronjs.org/docs/latest/tutorial/security).
Kein generisches eval/Tool/DB-Interface. Clipboard wird erst nach Core-Toolprüfung über einen
internen Rückkanal vom Electron-Mainprozess bedient. API-Keys werden nicht an den Renderer gelesen.

Die Browser-Vorschau verwendet einen **isolierten echten CLS-Core mit synthetischen Daten**.
Dort sind externe Provider, Systemkonfiguration, Import beliebiger Dokumente und Command-/Desktop-
Ausführung blockiert. Dateiaktionen bleiben im temporären Preview-Workspace. Native Dateidialoge
und Clipboard benötigen Electron. Die Vorschau ist nur Entwicklung, kein zu veröffentlichender Webdienst.

## Entwicklung

Python 3.10+ mit `requirements.txt`, Node 24, npm gemäß Lockfile:

```bash
npm ci --prefix desktop-shell
python main.py
```

`main.py` übergibt seinen Python-Interpreter an Electron. Alte UI ausdrücklich mit
`python main.py --legacy-ui`. Electron-Entwicklung nutzt die vorhandenen Repo-Daten und `.env`;
keine automatische Migration oder Löschung. Nicht beide Oberflächen gleichzeitig gegen dieselbe DB starten.

Browser-Vorschau:

```bash
cd desktop-shell
# Unter Windows z. B. $env:CLS_PYTHON='..\.venv\Scripts\python.exe'
# Unter Linux z. B. export CLS_PYTHON=/absoluter/pfad/zur/venv/bin/python
npm run dev
```

## Windows-EXE

Auf Windows mit Python 3.10+ und Node 24, im Repository:

```powershell
powershell -ExecutionPolicy Bypass -File desktop-shell/scripts/build-windows.ps1
```

Das Skript erstellt eine eigene `.venv-build`, bündelt den Python-Core mit PyInstaller und baut mit
Electron Builder einen NSIS-Installer in `desktop-shell/release/CLS Setup 0.7.0.exe`.
Für CLS selbst sind nach Installation **weder Python noch Node erforderlich**.
Builds und Tests fremder Projekte benötigen weiterhin deren Entwicklungswerkzeuge; Python-Tasks
verwenden in der gebündelten App den installierten Python-Interpreter aus dem PATH. Fehlt er,
wird der Task verständlich blockiert.
Alternativ den Workflow **Build CLS for Windows** manuell in GitHub Actions starten. Er führt zuerst
Python-/Frontend-/Transport-Tests aus und stellt den Installer als Artefakt bereit. Es gibt kein
automatisches Release, keinen Auto-Updater und kein eingebettetes Signing-Zertifikat.
Der Installer ist ohne eigenes Zertifikat unsigniert; Windows kann deshalb SmartScreen anzeigen.
Ein Linux-Pakettest ersetzt keinen nativen Windows-Installations-/Clipboard-Test.

## Vorhandene Daten übernehmen

Die installierte App nutzt standardmäßig Electron `userData/data` (Windows: normalerweise
`%APPDATA%/<Appname>/data`). Für einen bestehenden Datenordner:

```powershell
& 'Pfad\zu\CLS.exe' '--data-dir=D:\Mein CLS\data'
```

Vorher CLS schließen und den Datenordner sichern. Dieser Schalter wählt die bestehende SQLite-DB,
Memory-Dateien, Dokumente und Logs; er legt kein paralleles Memory-System an. Bestehende Repo-Keys
stehen häufig eine Ebene oberhalb in `.env`; bei Verwendung von `--data-dir` erwartet die App die
Key-Datei im gewählten Datenordner. Diese bewusst lokal übernehmen oder Provider-Keys neu eingeben.
Kein Datenimport und keine Überschreibung passieren ohne diese explizite Wahl.

## Tests

```bash
python -m unittest discover -s tests -v
npm test --prefix desktop-shell
# CLS_PYTHON auf denselben Python-Interpreter setzen:
npm run test:bridge --prefix desktop-shell
npm run build --prefix desktop-shell
python -m compileall .
git diff --check
```

Der optionale Linux-Paket-Smoke läuft nach Core- und Electron-Paketbau unter Xvfb:
`xvfb-run -a node scripts/native-smoke.mjs` im `desktop-shell`-Ordner. Er verwendet temporäre Daten,
prüft Renderer-Isolation, bestätigtes Schreiben und natives Clipboard und beendet danach nur seine
Test-App. Für öffentliche Distribution Windows-Build, Installer und Signierung separat prüfen.
