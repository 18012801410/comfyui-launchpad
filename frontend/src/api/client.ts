/** 统一 API 客户端：令牌注入、错误包络解析、401 处理。 */

const TOKEN_KEY = "launchpad_token";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

interface Envelope<T> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export async function request<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let payload: Envelope<T>;
  try {
    payload = (await resp.json()) as Envelope<T>;
  } catch {
    throw new ApiError("internal", `响应解析失败 (HTTP ${resp.status})`, resp.status);
  }
  if (resp.status === 401) {
    clearToken();
    if (location.pathname !== "/login") location.href = "/login";
    throw new ApiError("auth_required", "登录已失效，请重新输入令牌", 401);
  }
  if (!resp.ok || !payload.ok) {
    const err = payload.error ?? { code: "internal", message: `HTTP ${resp.status}` };
    throw new ApiError(err.code, err.message, resp.status);
  }
  return payload.data as T;
}

// ---------- 各模块 API ----------

export interface ComfyStatus {
  state: "stopped" | "starting" | "running" | "stopping" | "failed";
  pid: number | null;
  started_at: string | null;
  stopped_at: string | null;
  exit_code: number | null;
  version: string | null;
  port: number | null;
  port_ready: boolean;
}

export interface LaunchConfig {
  listen_port: number;
  listen_host: "127.0.0.1" | "0.0.0.0";
  preset: "default" | "low_vram" | "fp16_fast" | "custom";
  extra_args: string;
  academic_accel: boolean;
}

export interface SystemStatus {
  gpu: { name: string | null; count: number; driver: string | null; vram_total_mb: number | null; vram_used_mb: number | null; available: boolean; error: string | null };
  memory: { limit_mb: number | null; used_mb: number | null; host_total_mb: number | null; error: string | null };
  disk: { sys_total_gb: number | null; sys_free_gb: number | null; data_total_gb: number | null; data_free_gb: number | null; error: string | null };
  cuda: { available: boolean; version: string | null; error: string | null };
  python_version: string;
  comfy_process: string;
}

export interface VersionEntry {
  version: string;
  release_date?: string;
  torch_baseline?: string;
  size_mb?: number;
  sha256?: string;
  url?: string;
  notes?: string;
  deprecated?: boolean;
  installed?: boolean;
}

export interface InstalledVersion {
  version: string;
  installed_at: string | null;
  disk_size_mb: number | null;
  status: string;
}

export interface VersionsOverview {
  current: string | null;
  installed: InstalledVersion[];
  available: VersionEntry[];
  index_cached_at: string | null;
  index_stale: boolean;
  index_unreachable: boolean;
}

export interface PluginItem {
  name: string;
  dir_name: string;
  enabled: boolean;
  summary: string;
  git_url: string;
  git_ref: string;
  update_status: "up_to_date" | "behind" | "unknown";
  has_remote: boolean;
}

export interface DependencyItem {
  model_file: string;
  category: string;
  present: boolean;
  suggest_dir: string;
}

export interface WorkflowItem {
  workflow_id: string;
  name: string;
  source: "official" | "upload";
  library_slug: string | null;
  library_version: string | null;
  file_path: string;
  imported_at: string;
  preview_url: string;
  dependency_report: DependencyItem[];
}

export interface LibraryWorkflow {
  slug: string;
  name: string;
  category: string;
  description: string;
  preview_url: string;
  models_required: string[];
  updated_at: string;
}

export interface PanelSettingsData {
  panel_port: number;
  academic_accel_default: boolean;
  theme: "system" | "light" | "dark";
  autostart_enabled: boolean;
  channels: { versions: string; workflows: string; self: string };
  restart_required?: boolean;
}

export interface PanelUpdateInfo {
  current_version: string;
  latest_version: string;
  available: boolean;
  notes: string;
  checking: boolean;
}

export const api = {
  // auth
  verify: (token: string) =>
    request<{ panel_version: string }>("POST", "/api/auth/verify", { token }),
  rotate: () => request<{ token: string }>("POST", "/api/auth/rotate"),
  // comfy
  comfyStatus: () => request<ComfyStatus>("GET", "/api/comfy/status"),
  comfyStart: () => request<ComfyStatus>("POST", "/api/comfy/start"),
  comfyStop: () => request<ComfyStatus>("POST", "/api/comfy/stop"),
  comfyRestart: () => request<ComfyStatus>("POST", "/api/comfy/restart"),
  comfyLogs: (tail = 300) =>
    request<{ lines: { cursor: string; ts: string; source: string; line: string }[] }>(
      "GET",
      `/api/comfy/logs?tail=${tail}`,
    ),
  launchConfig: () => request<LaunchConfig>("GET", "/api/comfy/launch-config"),
  saveLaunchConfig: (cfg: Partial<LaunchConfig>) =>
    request<LaunchConfig & { warnings: string[] }>("PUT", "/api/comfy/launch-config", cfg),
  // system
  systemStatus: () => request<SystemStatus>("GET", "/api/system/status"),
  // versions
  versions: () => request<VersionsOverview>("GET", "/api/versions"),
  refreshVersionIndex: () =>
    request<{ updated_at: string; count: number }>("POST", "/api/versions/refresh"),
  installVersion: (v: string) =>
    request<{ task: string }>("POST", `/api/versions/${v}/install`),
  switchVersion: (v: string) => request<{ current: string }>("POST", `/api/versions/${v}/switch`),
  deleteVersion: (v: string) => request<{ removed: string }>("DELETE", `/api/versions/${v}`),
  // plugins
  plugins: (checkUpdates = false) =>
    request<{ items: PluginItem[] }>(
      "GET",
      `/api/plugins?check_updates=${checkUpdates ? 1 : 0}`,
    ),
  updatePlugin: (dir: string) => request<{ message: string }>("POST", `/api/plugins/${encodeURIComponent(dir)}/update`),
  enablePlugin: (dir: string, enabled: boolean) =>
    request<{ message: string }>("POST", `/api/plugins/${encodeURIComponent(dir)}/enable`, { enabled }),
  // workflows
  workflows: () => request<{ items: WorkflowItem[] }>("GET", "/api/workflows"),
  workflowLibrary: (refresh = false) =>
    request<{ workflows: LibraryWorkflow[]; cached_at: string | null; stale: boolean }>(
      "GET",
      `/api/workflows/library${refresh ? "?refresh=1" : ""}`,
    ),
  importWorkflow: (slug: string) => request<WorkflowItem>("POST", "/api/workflows/import", { slug }),
  deleteWorkflow: (id: string) => request<{ removed: string }>("DELETE", `/api/workflows/${id}`),
  uploadWorkflow: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/workflows/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: form,
    }).then(async (resp) => {
      const payload = (await resp.json()) as Envelope<WorkflowItem>;
      if (!resp.ok || !payload.ok) {
        throw new ApiError(payload.error?.code ?? "internal", payload.error?.message ?? "上传失败", resp.status);
      }
      return payload.data as WorkflowItem;
    });
  },
  // panel
  panelSettings: () => request<PanelSettingsData>("GET", "/api/panel/settings"),
  savePanelSettings: (patch: Partial<PanelSettingsData>) =>
    request<PanelSettingsData>("PUT", "/api/panel/settings", patch),
  panelUpdateInfo: () => request<PanelUpdateInfo>("GET", "/api/panel/update"),
  panelUpdate: () => request<{ phase: string }>("POST", "/api/panel/update"),
  panelLogs: (tail = 500) =>
    request<{ lines: string[] }>("GET", `/api/panel/logs?tail=${tail}`),
};

// ---------- SSE（fetch 流式，带 Bearer 与自动重连） ----------

export interface SseHandlers {
  onEvent?: (topic: string, payload: Record<string, unknown>) => void;
  onStateChange?: (connected: boolean) => void;
}

export function connectSse(topics: string[], handlers: SseHandlers): () => void {
  let closed = false;
  let retryMs = 1000;

  const connect = async (): Promise<void> => {
    while (!closed) {
      try {
        const resp = await fetch(`/api/events?topics=${topics.join(",")}`, {
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        if (!resp.ok || !resp.body) throw new Error(`SSE HTTP ${resp.status}`);
        handlers.onStateChange?.(true);
        retryMs = 1000;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let eventName = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, idx).replace(/\r$/, "");
            buf = buf.slice(idx + 1);
            if (line.startsWith("event: ")) {
              eventName = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              try {
                handlers.onEvent?.(
                  eventName,
                  JSON.parse(line.slice(6)) as Record<string, unknown>,
                );
              } catch {
                /* 忽略坏帧 */
              }
              eventName = "";
            }
          }
        }
        throw new Error("SSE closed");
      } catch {
        handlers.onStateChange?.(false);
        if (closed) return;
        await new Promise((r) => setTimeout(r, retryMs));
        retryMs = Math.min(retryMs * 2, 15000);
      }
    }
  };
  void connect();
  return () => {
    closed = true;
    handlers.onStateChange?.(false);
  };
}
