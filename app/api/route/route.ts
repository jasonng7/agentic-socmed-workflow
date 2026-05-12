import { NextResponse } from "next/server";
import { routeInput } from "@/lib/router";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const input = typeof body?.input === "string" ? body.input : "";

  return NextResponse.json({
    routes: routeInput(input)
  });
}
