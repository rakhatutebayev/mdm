import { NextRequest, NextResponse } from "next/server";

// Returns the raw JWT so the browser can call the backend directly for file downloads.
export async function GET(req: NextRequest) {
  const token = req.cookies.get("nocko_token")?.value;
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  return NextResponse.json({ token });
}
