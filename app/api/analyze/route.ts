import { NextResponse } from "next/server";
import { routeInput } from "@/lib/router";

export const runtime = "nodejs";

type AnalyzePayload = {
  input?: string;
  extractionJson?: unknown;
  extractionText?: string;
  userPreference?: string;
};

function buildExtractionText(payload: AnalyzePayload) {
  const chunks: string[] = [];
  const routes = routeInput(payload.input ?? "");

  chunks.push("Detected source URLs:");
  if (routes.length === 0) {
    chunks.push("No URLs detected.");
  } else {
    for (const route of routes) {
      chunks.push(`- ${route.label}: ${route.originalUrl}`);
    }
  }

  if (payload.extractionJson) {
    chunks.push("\nStructured extraction JSON:");
    chunks.push(JSON.stringify(payload.extractionJson, null, 2));
  }

  if (payload.extractionText?.trim()) {
    chunks.push("\nTranscript/caption/source text:");
    chunks.push(payload.extractionText.trim());
  }

  return chunks.join("\n").slice(0, 45000);
}

export async function POST(request: Request) {
  const payload = (await request.json().catch(() => null)) as AnalyzePayload | null;
  if (!payload) {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const apiKey = process.env.OPENAI_API_KEY;
  const baseUrl = (process.env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/$/, "");
  const model = process.env.OPENAI_MODEL || "gpt-4o-mini";

  if (!apiKey) {
    return NextResponse.json({ error: "OPENAI_API_KEY is not configured in Vercel environment variables." }, { status: 500 });
  }

  const extractionText = buildExtractionText(payload);
  const userPreference = payload.userPreference?.trim() || "No extra preference provided.";

  const response = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model,
      temperature: 0.1,
      messages: [
        {
          role: "system",
          content:
            "You analyze public social media extraction results. Follow the user's request exactly, using transcripts and captions as the source of truth. Use metadata only as supporting context. Do not invent facts that are not present. If the user asks for a specific format, structure, language, level of detail, or focus, honor that instead of applying a fixed summary template."
        },
        {
          role: "user",
          content: `User request:\n${userPreference}\n\nExtracted data to use. Prioritize fields named caption and transcript.\n\n${extractionText}`
        }
      ]
    })
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    return NextResponse.json(
      { error: "LLM request failed.", details: data },
      { status: response.status }
    );
  }

  const summary = data?.choices?.[0]?.message?.content;
  return NextResponse.json({
    summary,
    routes: routeInput(payload.input ?? "")
  });
}
