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
            "You analyze public social media extraction results. Use video transcripts and captions as the primary source of truth. Use metadata only as supporting context. Do not invent places, restaurants, addresses, prices, or facts that are not present. If the content is about travel, identify places, landmarks, cities, countries, routes, hotels, activities, timing, and practical travel notes mentioned. If the content is about food, identify food items, restaurant or stall names, locations, prices, ordering tips, and taste or recommendation signals mentioned. If the topic is something else, summarize the content and extract the most relevant entities, claims, instructions, calls to action, and useful details. When information is missing, say it is not mentioned in the transcript/caption. Return concise markdown with these sections: Content Summary, Category, Places And Locations, Food And Venue Details, Key Details, Useful Notes, Missing Or Unclear."
        },
        {
          role: "user",
          content: `User extraction preference:\n${userPreference}\n\nAnalyze the following data. Prioritize fields named caption and transcript.\n\n${extractionText}`
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
