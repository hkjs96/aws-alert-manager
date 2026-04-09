import { type NextRequest, NextResponse } from "next/server";
import { getCustomers, addCustomer } from "@/lib/mock-store";
import type { CreateCustomerRequest } from "@/types/api";
import type { Customer } from "@/types";
import { mockDelay } from "@/lib/mock-delay";

export async function GET() {
  await mockDelay();
  return NextResponse.json(getCustomers());
}

export async function POST(request: NextRequest) {
  await mockDelay();
  const body = (await request.json()) as CreateCustomerRequest;

  if (!body.name || !body.code) {
    return NextResponse.json(
      { code: "VALIDATION_ERROR", message: "name and code are required" },
      { status: 400 },
    );
  }

  if (getCustomers().some((c) => c.customer_id === body.code)) {
    return NextResponse.json(
      { code: "DUPLICATE", message: "Customer code already exists" },
      { status: 409 },
    );
  }

  const newCustomer: Customer = {
    customer_id: body.code,
    name: body.name,
    provider: "aws",
    account_count: 0,
  };
  addCustomer(newCustomer);
  return NextResponse.json(newCustomer, { status: 201 });
}
