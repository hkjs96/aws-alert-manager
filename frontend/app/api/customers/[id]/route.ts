import { type NextRequest, NextResponse } from "next/server";
import { getCustomers, removeCustomer } from "@/lib/mock-store";
import { mockDelay } from "@/lib/mock-delay";

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await mockDelay();
  const { id } = await params;
  const exists = getCustomers().some((c) => c.customer_id === id);
  if (!exists) {
    return NextResponse.json(
      { code: "NOT_FOUND", message: "Customer not found" },
      { status: 404 },
    );
  }
  removeCustomer(id);
  return new NextResponse(null, { status: 204 });
}
