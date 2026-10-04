export interface Project {
  id: number;
  name: string;
  description: string;
  instructions: string;
  path: string;
  status: string;
  memory_mode: string;
  knowledge_count?: number;
  updated_at: string;
}
export interface Task {
  id: string;
  goal: string;
  status: string;
  root: string;
  project_id: number;
  plan: string[];
  result: string;
  progress: { percent: number; current_step: string };
  blocking: { reason: string } | null;
  pending: {
    name: string;
    arguments: Record<string, unknown>;
    confirmation_id: string;
  } | null;
  ai_policy: Record<string, unknown> | null;
  policy_editable: boolean;
  created_at: string;
  updated_at: string;
  tool_results?: { tool: string; result: Record<string, unknown> }[];
  subtasks?: Task[];
  active_subtask_id?: string;
  project_storage?: { status: string };
}
export interface Knowledge {
  id: number;
  title: string;
  content: string;
  topic: string;
  kind: string;
  trust: string;
  project_id: number | null;
  updated_at: string;
  sources?: Record<string, unknown>[];
  versions?: Record<string, unknown>[];
  strategy?: Record<string, unknown>;
  reference_allowed?: boolean;
}
export interface Memory {
  id: number;
  content: string;
  category: string;
  trust: string;
  privacy: string;
  created_at: string;
}
export interface Provider {
  name: string;
  display_name: string;
  available: boolean;
  enabled: boolean;
  is_local: boolean;
  capabilities: string[];
  default_model: string;
  tool_calls: boolean;
}
export interface Activity {
  id: number;
  task_id: string;
  kind: string;
  detail: Record<string, unknown>;
  created_at: string;
}
export interface Experience {
  task_id: string;
  goal: string;
  project_id: number | null;
  created_at: string;
  summary: {
    status: string;
    verified: boolean;
    reference_allowed?: boolean;
    [key: string]: unknown;
  };
}
export interface Workflow {
  id: string;
  name: string;
  goal: string;
  steps: { tool: string; args: Record<string, unknown> }[];
  version: number;
}
export interface Schedule {
  id: string;
  workflow_id: string;
  project_id: number;
  interval: number | null;
  event: string | null;
  enabled: boolean;
}
export interface Snapshot {
  settings: { user_name: string; app_version: string; theme: string };
  projects: Project[];
  activeProject: Project | null;
  tasks: Task[];
  knowledge: Knowledge[];
  memory: Memory[];
  providers: Provider[];
  activity: Activity[];
  experiences: Experience[];
  conversation: {
    role: string;
    content: string;
    timestamp: string;
    meta?: { provider?: string };
  }[];
  stats: { total: number; documents: number; open_conflicts: number };
  conflicts: {
    id: number;
    entry_a: number;
    entry_b: number;
    reason: string;
    status: string;
  }[];
  documents: {
    id: number;
    filename: string;
    chunk_count: number;
    ingested_at: string;
  }[];
  workflows: Workflow[];
  schedules: Schedule[];
  routing: Record<string, { name: string; available: boolean }[]>;
  demo: boolean;
}
export type Page =
  | "overview"
  | "chat"
  | "tasks"
  | "projects"
  | "knowledge"
  | "memory"
  | "activity"
  | "providers"
  | "settings";
