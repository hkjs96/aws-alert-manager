/**
 * CSV 내보내기 유틸리티
 * 브라우저 다운로드를 트리거하여 CSV 파일을 저장한다.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function buildExportFilename(
  type: "resources" | "alarms",
  date: Date = new Date(),
): string {
  return `${type}_${formatDate(date)}.csv`;
}

export function buildExportUrl(
  path: string,
  filters: Record<string, string | undefined>,
): string {
  const apiPath = path.endsWith("/export") ? path.slice(0, -"/export".length) : path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }
  const qs = params.toString();
  return `${API_BASE_URL}${apiPath}${qs ? `?${qs}` : ""}`;
}

function escapeCsv(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(data: unknown): string {
  const rows = Array.isArray(data)
    ? data
    : Array.isArray((data as { items?: unknown[] }).items)
      ? (data as { items: unknown[] }).items
      : [];
  const objects = rows.filter((row): row is Record<string, unknown> => (
    Boolean(row) && typeof row === "object" && !Array.isArray(row)
  ));
  if (objects.length === 0) return "";
  const headers = Array.from(new Set(objects.flatMap((row) => Object.keys(row))));
  return [
    headers.map(escapeCsv).join(","),
    ...objects.map((row) => headers.map((header) => escapeCsv(row[header])).join(",")),
  ].join("\n");
}

export async function downloadCsv(
  path: string,
  filters: Record<string, string | undefined>,
  type: "resources" | "alarms",
): Promise<void> {
  const url = buildExportUrl(path, filters);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  const contentType = res.headers.get("Content-Type") ?? "";
  const blob = contentType.includes("application/json")
    ? new Blob([toCsv(await res.json())], { type: "text/csv;charset=utf-8" })
    : await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = buildExportFilename(type);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(blobUrl);
}
