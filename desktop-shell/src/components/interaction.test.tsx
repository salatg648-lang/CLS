import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable } from "./data-table";
import { EditorDialog } from "./editors";
import { TaskDetail } from "@/pages/tasks";
import { KnowledgePage } from "@/pages/knowledge";
import { App } from "@/app";
import * as store from "@/lib/store";
import type { Snapshot } from "@/lib/types";
const task = {
  id: "task1",
  goal: "Datei schreiben",
  status: "NEEDS_CONFIRMATION",
  root: "C:\\Workspace",
  project_id: 1,
  plan: ["write_file"],
  result: "",
  progress: { percent: 0, current_step: "" },
  blocking: { reason: "Bestätigung erforderlich" },
  pending: {
    name: "write_file",
    arguments: { path: "note.txt", content: "HELLO" },
    confirmation_id: "bound-token",
  },
  ai_policy: null,
  policy_editable: false,
  created_at: "2026-01-01T12:00:00",
  updated_at: "2026-01-01T12:00:00",
};
const data: Snapshot = {
  settings: { user_name: "Robin", app_version: "0.6.0", theme: "dark" },
  projects: [
    {
      id: 1,
      name: "Workspace",
      path: "C:\\Workspace",
      status: "active",
      description: "",
      instructions: "",
      memory_mode: "ASK",
      updated_at: "",
    },
  ],
  activeProject: {
    id: 1,
    name: "Workspace",
    path: "C:\\Workspace",
    status: "active",
    description: "",
    instructions: "",
    memory_mode: "ASK",
    updated_at: "",
  },
  tasks: [task],
  knowledge: [],
  memory: [],
  providers: [],
  activity: [],
  experiences: [],
  conversation: [],
  stats: { total: 0, documents: 0, open_conflicts: 0 },
  conflicts: [],
  documents: [],
  workflows: [],
  schedules: [],
  routing: {},
  demo: false,
};
let action = vi.fn(),
  navigate = vi.fn();
beforeEach(() => {
  action = vi.fn().mockResolvedValue({ id: 2 });
  navigate = vi.fn();
  vi.spyOn(store, "useCLS").mockReturnValue({
    data,
    loading: false,
    error: null,
    page: "overview",
    navigate,
    refresh: vi.fn(),
    action,
  });
});
describe("desktop interactions", () => {
  it("navigates knowledge tabs with arrow keys and keeps selection visible", async () => {
    const user = userEvent.setup();
    render(<KnowledgePage edit={vi.fn()} selectEntry={vi.fn()} />);
    const entries = screen.getByRole("tab", { name: /Einträge/ });
    entries.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /Dokumente/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /Dokumente/ })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(entries).toHaveAttribute("aria-selected", "true");
    expect(entries).toHaveFocus();
  });
  it("filters, sorts and hides table columns through accessible controls", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        id="test"
        data={[
          { name: "Zeta", status: "Offen" },
          { name: "Alpha", status: "Fertig" },
        ]}
        columns={[
          { accessorKey: "name", header: "Name", enableHiding: false },
          { accessorKey: "status", header: "Status" },
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Alpha");
    await user.type(screen.getByRole("textbox"), "Zeta");
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Spalten auswählen" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Status" }));
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("columnheader", { name: "Status" }),
    ).not.toBeInTheDocument();
  });
  it("binds a write confirmation to the exact pending token and never approves on open", async () => {
    const user = userEvent.setup();
    render(<TaskDetail id="task1" onClose={vi.fn()} />);
    expect(action).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Aktion prüfen" }));
    expect(screen.getByText(/HELLO/)).toBeInTheDocument();
    expect(action).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Bestätigen" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("run_task", {
        task_id: "task1",
        approve: true,
        confirmation_id: "bound-token",
      }),
    );
  });
  it("keeps explicit workspace and auto-create flag separate", async () => {
    const user = userEvent.setup();
    render(<EditorDialog editor={{ kind: "project" }} onClose={vi.fn()} />);
    await user.type(screen.getByLabelText("Projektname"), "Explicit");
    await user.type(
      screen.getByLabelText("Workspace"),
      "D:\\Projects\\Explicit",
    );
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith(
        "create_project",
        expect.objectContaining({
          path: "D:\\Projects\\Explicit",
          auto_workspace: true,
        }),
        "Projekt angelegt",
      ),
    );
  });
  it("opens Ctrl+K, moves with the keyboard and persists theme/sidebar preferences", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.type(screen.getByRole("combobox"), "Einstellungen");
    await user.keyboard("{Enter}");
    expect(navigate).toHaveBeenCalledWith("settings");
    await user.click(
      screen.getByRole("button", { name: "Farbschema wechseln" }),
    );
    expect(localStorage.getItem("cls:theme")).toBe('"light"');
    await user.keyboard("{Control>}b{/Control}");
    expect(
      screen.getByRole("button", { name: "Sidebar ausklappen" }),
    ).toBeInTheDocument();
  });
  it("shows backend validation errors without closing an editor or claiming success", async () => {
    action.mockRejectedValueOnce(
      new Error("Workspace liegt außerhalb erlaubter Roots."),
    );
    const user = userEvent.setup(),
      close = vi.fn();
    render(<EditorDialog editor={{ kind: "project" }} onClose={close} />);
    await user.type(screen.getByLabelText("Projektname"), "Blocked");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("außerhalb");
    expect(close).not.toHaveBeenCalled();
  });
});
