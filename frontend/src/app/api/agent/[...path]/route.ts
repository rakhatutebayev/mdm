import { NextRequest, NextResponse } from 'next/server';

const API = process.env.API_URL || 'http://localhost:8000';
const TENANT_ID = process.env.DEFAULT_TENANT_ID || '1';

/**
 * Proxy all /api/agent/* requests to the FastAPI backend portal endpoints.
 * Automatically injects X-Tenant-Id header.
 *
 * Handles:
 *   GET  /api/agent/devices           → GET /api/v1/portal/devices
 *   GET  /api/agent/devices/[id]      → GET /api/v1/portal/devices/[id]
 *   GET  /api/agent/alerts            → GET /api/v1/portal/alerts
 *   POST /api/agent/alerts/[id]/close → POST /api/v1/portal/alerts/[id]/close
 *   GET  /api/agent/agents            → GET /api/v1/portal/agents
 *   ... etc
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, await params, 'GET');
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, await params, 'POST');
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, await params, 'PATCH');
}

async function proxy(
  request: NextRequest,
  params: { path: string[] },
  method: string
) {
  const path = (params.path || []).join('/');
  const search = request.nextUrl.search;
  const url = `${API}/api/v1/portal/${path}${search}`;

  const contentType = request.headers.get('content-type') || '';
  const isMultipart = contentType.includes('multipart/form-data');

  // For multipart uploads: forward as-is (let the browser-set boundary pass through)
  // For JSON: inject Content-Type if missing
  const headers: Record<string, string> = { 'X-Tenant-Id': TENANT_ID };
  if (!isMultipart && method !== 'GET') {
    headers['Content-Type'] = 'application/json';
  }
  // Forward content-type for multipart (includes boundary)
  if (isMultipart) {
    headers['Content-Type'] = contentType;
  }

  let body: BodyInit | undefined;
  if (method !== 'GET') {
    if (isMultipart) {
      // Forward as ArrayBuffer to preserve binary data
      body = await request.arrayBuffer();
    } else {
      body = await request.text();
    }
  }

  try {
    const r = await fetch(url, { method, headers, body });
    const data = await r.text();
    return new NextResponse(data, {
      status: r.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return NextResponse.json({ error: 'Backend unavailable' }, { status: 503 });
  }
}
