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
 