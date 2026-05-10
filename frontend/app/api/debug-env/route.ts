import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    API_GATEWAY_URL: process.env.API_GATEWAY_URL ?? "(undefined)",
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "(undefined)",
    API_BASE_URL: process.env.API_BASE_URL ?? "(undefined)",
    NODE_ENV: process.env.NODE_ENV,
  });
}
