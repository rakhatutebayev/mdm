/**
 * Catch-all Next.js Route Handler that proxies all /api/mdm/* requests
 * to the FastAPI backend. Works both locally and in Docker.
 * 
 * Next.js 15+ requires params to be awaited.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_URL ?? "http://localhost:8000";

type Context = { params: Promise<{ slug: string[] }> };

async function proxy(req: NextRequest, context: Context) {
  const { slug } = await context.params;
  const path = "/" + slug.join("/");
  const search = req.nextUrl.search;
  const url = `${BACKEND}/api/v1${path}${search}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD" && req.method !== "DELETE") {
    body = await req.text();
  }

  try {
    const res = await fetch(url, {
      method: req.method,
      headers,
      body,
    });

    // Next.js 15+ cannot create NextResponse with status 204 (no body allowed).
    // Return 200 with empty body instead — clients only check ok/!ok anyway.
    if (res.status === 204) {
      return new NextResponse(null, { status: 200 });
    }

    const data = await res.text();
    return new NextResponse(data, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("[MDM proxy error]", err);
    return NextResponse.json({ error: "Backend unavailable" }, { status: 503 });
  }
}

export const GET    = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const POST   = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const PATCH  = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Context) => proxy(req, ctx);
