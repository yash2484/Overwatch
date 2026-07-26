import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import type {
  Aoi,
  Brief,
  DetectionFeature,
  Job,
  JobSubmit,
  SceneSummary,
} from "./types";

const POLL_MS = 2000; // Phase 3 contract: REST polling at 2s.

export const useAois = () =>
  useQuery({ queryKey: ["aois"], queryFn: () => api<Aoi[]>("/aois") });

export const useScenes = (slug: string | null) =>
  useQuery({
    queryKey: ["scenes", slug],
    enabled: slug !== null,
    queryFn: () => api<SceneSummary[]>(`/aois/${slug}/scenes`),
  });

export const useDetections = (slug: string | null) =>
  useQuery({
    queryKey: ["detections", slug],
    enabled: slug !== null,
    queryFn: async () => {
      const fc = await api<{ features: DetectionFeature[] }>(
        `/aois/${slug}/detections`,
      );
      return fc.features;
    },
  });

export const useBrief = (slug: string | null) =>
  useQuery({
    queryKey: ["brief", slug],
    enabled: slug !== null,
    queryFn: () => api<Brief>(`/aois/${slug}/brief`),
    // A missing brief is a legitimate empty state, not an error worth retrying.
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 404) && count < 2,
    // Poll only while the brief is still being generated.
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? POLL_MS : false,
  });

export const useJob = (jobId: string | null) =>
  useQuery({
    queryKey: ["job", jobId],
    enabled: jobId !== null,
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? POLL_MS : false;
    },
  });

export function useSubmitJob(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: JobSubmit) =>
      api<{ job_id: string }>(`/aois/${slug}/jobs`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["detections", slug] });
      qc.invalidateQueries({ queryKey: ["scenes", slug] });
    },
  });
}

export function useSubmitBrief(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<{ brief_id: number }>(`/aois/${slug}/briefs`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brief", slug] }),
  });
}
