import { type NextRequest, NextResponse } from "next/server";

const API_BASE_URL =
  process.env.API_GATEWAY_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.API_BASE_URL ??
  "";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, { params }: RouteContext) {
  if (!API_BASE_URL) {
    return NextResponse.json(
      { code: "NO_API", message: "API Gateway URL is not configured" },
      { status: 503 },
    );
  }

  const { path } = await params;
  const upstream = new URL(`${API_BASE_URL.replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}`);
  upstream.search = request.nextUrl.search;

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.text();
  const response = await fetch(upstream, {
    method: request.method,
    headers: {
      "Content-Type": request.headers.get("Content-Type") ?? "application/json",
    },
    body,
    cache: "no-store",
  });

  const contentType = response.headers.get("Content-Type") ?? "application/json";
  return new NextResponse(response.body, {
    status: response.status,
    headers: { "Content-Type": contentType },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
