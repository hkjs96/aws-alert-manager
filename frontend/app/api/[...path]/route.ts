import { type NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

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

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("Content-Type") ?? "application/json",
  };

  // Forward the Google ID token as a Bearer token so API Gateway's JWT
  // authorizer can validate it. Read via auth() (same path as the working
  // session endpoint) — robust against getToken cookie/salt/chunking issues.
  // When auth is not configured this is simply absent (staged rollout).
  if (process.env.AUTH_SECRET) {
    const session = await auth();
    const idToken = session?.id_token;
    if (idToken) {
      headers["Authorization"] = `Bearer ${idToken}`;
    }
  }

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.text();
  const response = await fetch(upstream, {
    method: request.method,
    headers,
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
