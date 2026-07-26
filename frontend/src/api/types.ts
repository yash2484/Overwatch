export type ChangeType = "construction" | "vegetation_loss" | "flooding";
export type BriefStatus =
  | "generating"
  | "validated"
  | "rejected"
  | "failed"
  | "stale";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface DetectionProperties {
  id: number;
  job_id: string;
  before_scene_id: number;
  after_scene_id: number;
  change_type: string;
  area_m2: number;
  magnitude: number;
  confidence: number;
  contributing_indices: Record<string, unknown>;
  src_epsg: number;
  created_at: string;
}

export interface DetectionFeature {
  type: "Feature";
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: DetectionProperties;
}

export interface Claim {
  seq: number;
  text: string;
  claim_type: "observed" | "context" | "reported" | "mixed";
  detection_ids: number[];
}

export interface Brief {
  id: number;
  aoi_slug: string;
  status: BriefStatus;
  attempts: number;
  headline: string | null;
  model: string | null;
  usage: Record<string, unknown>;
  violations: unknown[] | null;
  error: Record<string, unknown> | null;
  before_scene_id: number;
  after_scene_id: number;
  claims: Claim[];
  created_at: string;
  updated_at: string;
}

export interface SceneSummary {
  id: number;
  stac_id: string;
  captured_at: string;
  cloud_pct: number;
  usable_fraction: number | null;
  bounds: [number, number, number, number];
}

export interface Job {
  id: string;
  aoi_slug: string;
  status: JobStatus;
  stage: string | null;
  attempts: number;
  params: Record<string, unknown>;
  before_scene_id: number | null;
  after_scene_id: number | null;
  detection_count: number | null;
  error: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Aoi {
  slug: string;
  name: string;
  vertical: string;
  geometry: { type: "Polygon"; coordinates: number[][][] };
  cadence_days: number | null;
  area_km2: number;
  created_at: string;
}

export interface DateRange {
  start: string; // YYYY-MM-DD
  end: string;
}

/** Body for POST /aois/{slug}/jobs — a before + after date window (Phase 3 contract). */
export interface JobSubmit {
  before: DateRange;
  after: DateRange;
}
