import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";
// Allow up to 120s — backend downloads ~14 MB EXE from GitHub on first request
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  const token = req.cookies.get("nocko_token")?.value;
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let body: string;
  try {
    body = await req.text();
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND}/api/v1/packages/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body,
  });

  if (!upstream.ok) {
    const err = await upstream.json().catch(() => ({ detail: upstream.statusText }));
    return NextResponse.json(err, { status: upstream.status });
  }

  // Stream the binary response directly to the browser without buffering
  const cd = upstream.headers.get("Content-Disposition") ?? 'attachment; filename="nocko-mdm-agent.exe"';
  const ct = upstream.headers.get("Content-Type") ?? "application/octet-stream";

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": ct,
      "Content-Disposition": cd,
      "Transfer-Encoding": "chunked",
    },
  });
}
