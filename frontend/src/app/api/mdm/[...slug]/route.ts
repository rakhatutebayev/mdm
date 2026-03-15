/**
 * Catch-all Next.js Route Handler that proxies all /api/mdm/* requests
 * to the FastAPI backend. Works both locally and in Docker.
 *
 * Correctly forwards Content-Type and Content-Disposition so binary
 * downloads (MSI, EXE, ZIP) arrive with the right filename and MIME type.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_URL ?? "http://localhost:8000";

type Context = { params: Promise<{ slug: string[] }> };

async function proxy(req: NextRequest, context: Context) {
  const { slug } = await context.params;
  const path   = "/" + slug.join("/");
  const search = req.nextUrl.search;
  const url    = `${BACKEND}/api/v1${path}${search}`;

  // Forward the original Content-Type from the client request
  const reqContentType = req.headers.get("Content-Type") ?? "application/json";
  const headers: Record<string, string> = {
    "Content-Type": reqContentType,
  };

  let body: Buffer | string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD" && req.method !== "DELETE") {
    body = await req.arrayBuffer().then((b) => Buffer.from(b));
  }

  try {
    const res = await fetch(url, {
      method: req.method,
      headers,
      body: body as BodyInit | undefined,
    });

    // Next.js 15+ cannot create NextResponse with status 204 (no body allowed).
    if (res.status === 204) {
      return new NextResponse(null, { status: 200 });
    }

    // Read raw bytes so binary files (MSI, EXE, ZIP) are not corrupted
    const bytes = await res.arrayBuffer();

    // Build response headers — pass through Content-Type and Content-Disposition
    const resHeaders: Record<string, string> = {};

    const ct = res.headers.get("Content-Type");
    if (ct) resHeaders["Content-Type"] = ct;

    const cd = res.headers.get("Content-Disposition");
    if (cd) resHeaders["Content-Disposition"] = cd;

    return new NextResponse(bytes, {
      status: res.status,
      headers: resHeaders,
    });
  } catch (err) {
    console.error("[MDM proxy error]", err);
    return NextResponse.json({ error: "Backend unavailable" }, { status: 503 });
  }
}

export const GET    = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const POST   = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const PUT    = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const PATCH  = (req: NextRequest, ctx: Context) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Context) => proxy(req, ctx);

