import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Backend URL is not configured. Set BACKEND_URL or NEXT_PUBLIC_BACKEND_URL in Vercel." },
      { status: 500 }
    );
  }

  const payload = await request.text();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload
    });
  } catch {
    return NextResponse.json(
      { error: "Could not reach the EC2 backend from Vercel. Check that Uvicorn is running and port 8000 is open." },
      { status: 502 }
    );
  }

  const data = await response.json().catch(() => null);
  return NextResponse.json(data ?? { error: "Backend returned a non-JSON response." }, { status: response.status });
}
