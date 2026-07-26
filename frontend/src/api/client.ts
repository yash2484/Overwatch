const BASE = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // The backend's structured envelope: { error: { code, message, detail } }.
    const body = await response.json().catch(() => null);
    const err = body?.error;
    throw new ApiError(
      response.status,
      err?.code ?? "unknown",
      err?.message ?? response.statusText,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const sceneImageUrl = (sceneId: number) => `${BASE}/scenes/${sceneId}/image`;
