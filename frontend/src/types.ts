export type JobType = "llm" | "image";
export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";
export type ModelFamily = "flux" | "sdxl" | "gguf" | "unknown";

export interface Model {
  id: string;
  name: string;
  family: ModelFamily;
  job_type: JobType;
  size_bytes: number;
  loaded: boolean;
}

export interface GpuStatus {
  resident: string | null;
  model_id: string | null;
  model: string | null;
  family: string | null;
}

export interface Job {
  id: string;
  type: JobType;
  status: JobStatus;
  priority: number;
  model_id: string;
  params: Record<string, unknown>;
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImageItem {
  id: string;
  job_id: string;
  seed: number | null;
  width: number | null;
  height: number | null;
  params: Record<string, unknown>;
  created_at: string;
  url: string;
  thumb_url: string | null;
}

export interface JobCreate {
  type: JobType;
  model_id: string;
  params: Record<string, unknown>;
  priority?: number;
}

export interface BusEvent {
  type: string;
  ts: number;
  [k: string]: unknown;
}
