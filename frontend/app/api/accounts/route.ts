import { type NextRequest, NextResponse } from "next/server";
import { getAccounts, addAccount } from "@/lib/mock-store";
import type { CreateAccountRequest } from "@/types/api";
import type { Account } from "@/types";
import { mockDelay } from "@/lib/mock-delay";

export async function GET() {
  await mockDelay();
  return NextResponse.json(getAccounts());
}

export async function POST(request: NextRequest) {
  await mockDelay();
  const body = (await request.json()) as CreateAccountRequest;

  if (!body.account_id || !body.role_arn || !body.name || !body.customer_id) {
    return NextResponse.json(
      { code: "VALIDATION_ERROR", message: "All fields are required" },
      { status: 400 },
    );
  }

  if (getAccounts().some((a) => a.account_id === body.account_id)) {
    return NextResponse.json(
      { code: "DUPLICATE", message: "Account ID already exists" },
      { status: 409 },
    );
  }

  const newAccount: Account = {
    account_id: body.account_id,
    customer_id: body.customer_id,
    name: body.name,
    role_arn: body.role_arn,
    regions: ["us-east-1"],
    connection_status: "untested",
  };
  addAccount(newAccount);
  return NextResponse.json(newAccount, { status: 201 });
}
