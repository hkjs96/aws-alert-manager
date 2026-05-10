import type { GlobalFilterParams } from "@/types/api";
import { ApiError } from "@/types/api";

export { ApiError };

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "네트워크 연결을 확인해주세요");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      res.status,
      body.code ?? "UNKNOWN",
      body.message ?? `요청 실패 (${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

export function buildFilterParams(filters: GlobalFilterParams): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }
  return params;
}

export function buildQueryString(
  params: Record<string, string | number | boolean | undefined>,
): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      sp.set(key, String(value));
    }
  }
  return sp.toString();
}
