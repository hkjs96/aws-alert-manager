import { type NextRequest, NextResponse } from "next/server";

const API_BASE_URL =
  process.env.API_GATEWAY_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.API_BASE_URL ??
  "";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  if (!API_BASE_URL) {
    return NextResponse.json([]);
  }

  try {
    const res = await fetch(
      `${API_BASE_URL}/api/resources/${encodeURIComponent(id)}/metrics`,
      { cache: "no-store" },
    );
    if (!res.ok) return NextResponse.json([]);
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json([]);
  }
}
