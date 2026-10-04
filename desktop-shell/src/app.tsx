import { useState, useEffect } from "react";
import { Command } from "cmdk";
import {
  LayoutDashboard,
  MessageSquare,
  ListTodo,
  FolderOpen,
  BookOpen,
  Brain,
  Activity,
  Cpu,
  Settings2,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronDown,
  Plus,
  Sparkles,
  Command as CommandIcon,
  ShieldCheck,
  Minus,
  Square,
  X,
  RefreshCw,
  Moon,
  Sun,
  ArrowUpRight,
  Loader2,
} from "lucide-react";
import { useCLS } from "./lib/store";
import type { Page } from "./lib/types";
import { Button, Modal, useSavedState, Empty } from "./components/primitives";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "./components/ui/dropdown-menu";
import { EditorDialog, type Editor } from "./components/editors";
import { Overview } from "./pages/overview";
import { Tasks, TaskDetail } from "./pages/tasks";
import { Projects } from "./pages/projects";
import { KnowledgePage, KnowledgeDetail } from "./pages/knowledge";
import { MemoryPage } from "./pages/memory";
import { Providers } from "./pages/providers";
import { Chat } from "./pages/chat";
import { ActivityPage } from "./pages/activity";
import { Settings } from "./pages/settings";
import { cn } from "./lib/utils";
const navigation: {
  id: Page;
  label: string;
  icon: typeof LayoutDashboard;
  group: string;
}[] = [
  {
    id: "overview",
    label: "Übersicht",
    icon: LayoutDashboard,
    group: "ARBEITSRAUM",
  },
  { id: "chat", label: "Chat", icon: MessageSquare, group: "ARBEITSRAUM" },
  { id: "tasks", label: "Aufgaben", icon: ListTodo, group: "ARBEITSRAUM" },
  { id: "projects", label: "Projekte", icon: FolderOpen, group: "ARBEITSRAUM" },
  { id: "knowledge", label: "Wissen", icon: BookOpen, group: "GEDÄCHTNIS" },
  { id: "memory", label: "Memory", icon: Brain, group: "GEDÄCHTNIS" },
  { id: "activity", label: "Aktivität", icon: Activity, group: "GEDÄCHTNIS" },
  { id: "providers", label: "Provider", icon: Cpu, group: "SYSTEM" },
  { id: "settings", label: "Einstellungen", icon: Settings2, group: "SYSTEM" },
];
export function App() {
  const { data, loading, error, page, navigate, action, refresh } = useCLS();
  const [collapsed, setCollapsed] = useSavedState("sidebar-collapsed", false);
  const [theme, setTheme] = useSavedState("theme", "dark");
  const [command, setCommand] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [selectedKnowledge, setSelectedKnowledge] = useState<number | null>(
    null,
  );
  const [commandQuery, setCommandQuery] = useState("");
  const attention =
    data?.tasks.filter((t) => t.status.startsWith("NEEDS_")).length || 0;
  const openEditor = () =>
    setEditor(
      page === "projects"
        ? { kind: "project" }
        : page === "knowledge"
          ? { kind: "knowledge" }
          : page === "memory"
            ? { kind: "memory" }
            : { kind: "task" },
    );
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () =>
      document.documentElement.classList.toggle(
        "dark",
        theme === "dark" || (theme === "system" && media.matches),
      );
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [theme]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (
        (event.ctrlKey || event.metaKey) &&
        ["k", "n", "b"].includes(event.key.toLowerCase())
      ) {
        event.preventDefault();
        if (event.key.toLowerCase() === "k") setCommand((value) => !value);
        if (event.key.toLowerCase() === "n") openEditor();
        if (event.key.toLowerCase() === "b") setCollapsed((value) => !value);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [page, setCollapsed]);
  function choose(page: Page) {
    navigate(page);
    setCommand(false);
    setCommandQuery("");
  }
  return (
    <div className={cn("app-shell", collapsed && "sidebar-collapsed")}>
      <a href="#main-content" className="skip-link">
        Zum Arbeitsbereich
      </a>
      <aside className="app-sidebar" aria-label="Hauptnavigation">
        <div className="brand">
          <span className="cls-glyph">
            <Sparkles size={22} />
          </span>
          {!collapsed && (
            <>
              <span className="brand-word">
                CLS<span>PERSONAL INTELLIGENCE</span>
              </span>
              <span className="version-tag">β</span>
            </>
          )}
        </div>
        <button
          className="sidebar-search"
          onClick={() => setCommand(true)}
          aria-label="Globale Suche öffnen"
        >
          <Search size={17} />
          {!collapsed && (
            <>
              <span>Suche & Befehle</span>
              <kbd>Strg K</kbd>
            </>
          )}
        </button>
        <nav>
          {["ARBEITSRAUM", "GEDÄCHTNIS", "SYSTEM"].map((group) => (
            <div className="nav-group" key={group}>
              {!collapsed && <p>{group}</p>}
              {navigation
                .filter((n) => n.group === group)
                .map((item) => (
                  <button
                    key={item.id}
                    className={cn("nav-item", page === item.id && "selected")}
                    aria-current={page === item.id ? "page" : undefined}
                    title={collapsed ? item.label : undefined}
                    aria-label={item.label}
                    onClick={() => navigate(item.id)}
                  >
                    <item.icon size={19} />
                    {!collapsed && (
                      <>
                        <span>{item.label}</span>
                        {item.id === "tasks" && attention > 0 && (
                          <span className="nav-count">{attention}</span>
                        )}
                        {item.id === "chat" && (
                          <span className="new-label">AI</span>
                        )}
                      </>
                    )}
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {!collapsed && (
            <div className="local-note">
              <ShieldCheck size={16} />
              <div>
                <strong>Dein Wissen bleibt deins.</strong>
                <span>Kontrolle, die sich gut anfühlt.</span>
              </div>
            </div>
          )}
          <button
            className="profile-button"
            onClick={() => navigate("settings")}
            aria-label="Persönliche Einstellungen"
          >
            <span className="avatar">
              {data?.settings.user_name?.[0] || "R"}
            </span>
            {!collapsed && (
              <>
                <span>
                  <strong>{data?.settings.user_name || "CLS"}</strong>
                  <small>Persönlicher Arbeitsraum</small>
                </span>
                <Settings2 size={16} />
              </>
            )}
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="header-left">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCollapsed((v) => !v)}
              aria-label={
                collapsed ? "Sidebar ausklappen" : "Sidebar einklappen"
              }
            >
              {collapsed ? (
                <PanelLeftOpen size={18} />
              ) : (
                <PanelLeftClose size={18} />
              )}
            </Button>
            <span className="header-divider" />
            <span className="breadcrumb">
              Arbeitsraum <span>/</span>{" "}
              <strong>{navigation.find((n) => n.id === page)?.label}</strong>
            </span>
          </div>
          <div className="header-right">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="project-switch">
                  <span className="project-dot" />
                  {data?.activeProject?.name || "Projekt wählen"}
                  <ChevronDown size={13} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Aktives Projekt</DropdownMenuLabel>
                {data?.projects
                  .filter((p) => p.status === "active")
                  .map((p) => (
                    <DropdownMenuItem
                      key={p.id}
                      onClick={() => {
                        void action(
                          "set_active_project",
                          { project_id: p.id },
                          "Projekt gewechselt",
                        ).catch(() => {});
                      }}
                    >
                      <FolderOpen size={15} />
                      {p.name}
                      {p.id === data.activeProject?.id && " ✓"}
                    </DropdownMenuItem>
                  ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => setEditor({ kind: "project" })}
                >
                  <Plus size={15} />
                  Neues Projekt
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Farbschema wechseln"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </Button>
            {window.cls && (
              <div className="window-controls">
                <button
                  aria-label="Fenster minimieren"
                  onClick={() => window.cls?.window("minimize")}
                >
                  <Minus size={14} />
                </button>
                <button
                  aria-label="Fenster maximieren"
                  onClick={() => window.cls?.window("maximize")}
                >
                  <Square size={12} />
                </button>
                <button
                  className="close-window"
                  aria-label="Fenster schließen"
                  onClick={() => window.cls?.window("close")}
                >
                  <X size={16} />
                </button>
              </div>
            )}
          </div>
        </header>
        <main
          id="main-content"
          tabIndex={-1}
          className={cn("workspace-content", page === "chat" && "chat-content")}
        >
          {error && (
            <div className="connection-error" role="alert">
              <span>CLS-Verbindung unterbrochen: {error.message}</span>
              <Button
                variant="outline"
                onClick={() => {
                  void refresh();
                }}
              >
                <RefreshCw size={15} />
                Erneut verbinden
              </Button>
            </div>
          )}
          {loading ? (
            <div className="loading-state" role="status">
              <Loader2 className="animate-spin" size={25} />
              <h2>Dein Arbeitsraum wird geöffnet …</h2>
              <p>CLS verbindet sich mit deinem lokalen Core.</p>
            </div>
          ) : (
            data && (
              <>
                {page === "overview" && (
                  <Overview
                    edit={setEditor}
                    selectTask={(t) => setSelectedTask(t.id)}
                  />
                )}
                <div hidden={page !== "chat"} className="chat-holder">
                  <Chat selectTask={setSelectedTask} />
                </div>
                {page === "tasks" && (
                  <Tasks
                    edit={setEditor}
                    selectTask={(t) => setSelectedTask(t.id)}
                  />
                )}
                {page === "projects" && <Projects edit={setEditor} />}
                {page === "knowledge" && (
                  <KnowledgePage
                    edit={setEditor}
                    selectEntry={setSelectedKnowledge}
                  />
                )}
                {page === "memory" && <MemoryPage edit={setEditor} />}
                {page === "activity" && <ActivityPage />}
                {page === "providers" && <Providers edit={setEditor} />}
                {page === "settings" && (
                  <Settings theme={theme} setTheme={setTheme} />
                )}
              </>
            )
          )}
        </main>
        <footer className="status-bar">
          <span>
            <i className={error ? "offline-dot" : "online-dot"} />
            {error
              ? "Core nicht erreichbar"
              : loading
                ? "Verbinde …"
                : "Lokaler Core verbunden"}
          </span>
          <span className="status-workspace">
            <FolderOpen size={12} />
            {data?.activeProject?.path || "Kein Workspace ausgewählt"}
          </span>
          <span>
            {data?.demo
              ? "Vorschau · isolierte Beispieldaten"
              : `CLS ${data?.settings.app_version || ""}`}
            <button
              aria-label="Tastaturbefehle öffnen"
              onClick={() => setCommand(true)}
            >
              <CommandIcon size={13} />
            </button>
          </span>
        </footer>
      </div>
      <Modal
        open={command}
        onClose={() => setCommand(false)}
        title="Suchen & ausführen"
        description="Navigation, Aufgaben, Projekte und Wissen an einem Ort."
      >
        <Command className="command-palette" loop>
          <div className="command-input">
            <Search size={19} />
            <Command.Input
              autoFocus
              placeholder="Was möchtest du tun?"
              value={commandQuery}
              onValueChange={setCommandQuery}
            />
            <kbd>Esc</kbd>
          </div>
          <Command.List>
            <Command.Empty>
              Keine Ergebnisse. Versuche einen anderen Begriff.
            </Command.Empty>
            <Command.Group heading="Schnellaktionen">
              <Command.Item
                onSelect={() => {
                  setCommand(false);
                  setEditor({ kind: "task" });
                }}
              >
                <Plus size={17} />
                Neue Aufgabe<kbd>Strg N</kbd>
              </Command.Item>
              <Command.Item
                onSelect={() => {
                  setCommand(false);
                  setEditor({ kind: "project" });
                }}
              >
                <FolderOpen size={17} />
                Neues Projekt
              </Command.Item>
            </Command.Group>
            <Command.Group heading="Navigation">
              {navigation.map((n) => (
                <Command.Item
                  key={n.id}
                  value={`Seite ${n.label}`}
                  onSelect={() => choose(n.id)}
                >
                  <n.icon size={17} />
                  {n.label}
                  <ArrowUpRight size={13} />
                </Command.Item>
              ))}
            </Command.Group>
            {commandQuery && (
              <>
                <Command.Group heading="Projekte">
                  {data?.projects
                    .filter((p) => p.status === "active")
                    .map((p) => (
                      <Command.Item
                        key={p.id}
                        value={`Projekt ${p.name}`}
                        onSelect={() => {
                          void action("set_active_project", {
                            project_id: p.id,
                          }).catch(() => {});
                          choose("projects");
                        }}
                      >
                        <FolderOpen size={16} />
                        {p.name}
                      </Command.Item>
                    ))}
                </Command.Group>
                <Command.Group heading="Aufgaben">
                  {data?.tasks.slice(0, 50).map((t) => (
                    <Command.Item
                      key={t.id}
                      value={`Aufgabe ${t.goal}`}
                      onSelect={() => {
                        setSelectedTask(t.id);
                        setCommand(false);
                      }}
                    >
                      <ListTodo size={16} />
                      {t.goal}
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Wissen">
                  {data?.knowledge.slice(0, 50).map((k) => (
                    <Command.Item
                      key={k.id}
                      value={`Wissen ${k.title} ${k.content}`}
                      onSelect={() => {
                        setSelectedKnowledge(k.id);
                        choose("knowledge");
                      }}
                    >
                      <BookOpen size={16} />
                      {k.title || k.content.slice(0, 70)}
                    </Command.Item>
                  ))}
                </Command.Group>
              </>
            )}
          </Command.List>
        </Command>
      </Modal>
      {editor && (
        <EditorDialog
          key={
            editor.kind +
            (editor.kind === "provider"
              ? editor.item.name
              : "item" in editor && editor.item
                ? String(editor.item.id)
                : "")
          }
          editor={editor}
          onClose={() => setEditor(null)}
        />
      )}
      {selectedKnowledge !== null && (
        <KnowledgeDetail
          id={selectedKnowledge}
          onClose={() => setSelectedKnowledge(null)}
          edit={setEditor}
        />
      )}
      {selectedTask && (
        <TaskDetail id={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
    </div>
  );
}
