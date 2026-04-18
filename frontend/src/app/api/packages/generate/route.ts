import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  console.log("[packages/generate] START");

  const token = req.cookies.get("nocko_token")?.value;
  if (!token) {
    console.log("[packages/generate] No token cookie");
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let body: string;
  try {
    body = await req.text();
    console.log("[packages/generate] body:", body);
  } catch (e) {
    console.error("[packages/generate] body read error:", e);
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  console.log(`[packages/generate] Calling backend: ${BACKEND}/api/v1/packages/generate`);

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/api/v1/packages/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[packages/generate] fetch to backend failed:", msg);
    return NextResponse.json({ detail: `Backend unreachable: ${msg}` }, { status: 502 });
  }

  console.log(`[packages/generate] Backend responded: ${upstream.status}`);

  if (!upstream.ok) {
    const err = await upstream.json().catch(() => ({ detail: upstream.statusText }));
    console.error("[packages/generate] Backend error:", err);
    return NextResponse.json(err, { status: upstream.status });
  }

  const cd = upstream.headers.get("Content-Disposition") ?? 'attachment; filename="nocko-mdm-agent.exe"';
  const ct = upstream.headers.get("Content-Type") ?? "application/octet-stream";
  console.log(`[packages/generate] Streaming response cd=${cd} ct=${ct}`);

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": ct,
      "Content-Disposition": cd,
    },
  });
}
