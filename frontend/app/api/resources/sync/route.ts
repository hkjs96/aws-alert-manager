import { NextResponse } from "next/server";
import type { SyncResult } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function POST() {
  await mockDelay();

  const result: SyncResult = {
    discovered: 3,
    updated: 5,
    removed: 1,
  };
  return NextResponse.json(result);
}
