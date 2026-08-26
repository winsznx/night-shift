/**
 * Same-origin proxy to the BFF, resolved per request.
 *
 * This was a `rewrites()` entry in next.config.ts, which reads NIGHTSHIFT_API_URL. That
 * config is evaluated at build time and baked into routes-manifest.json, but the API URL
 * is only known at deploy time — so the container built with no API URL shipped with no
 * proxy at all, and every browser-side /api/* call 404'd on the deployed site while the
 * Server Components kept working. The failure was invisible from the pages themselves.
 *
 * Resolving the destination per request means the same image runs against local, staging,
 * and production without a rebuild, and a missing API URL fails loudly instead of
 * silently removing the route.
 */

import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const base = process.env.NIGHTSHIFT_API_URL;
  if (!base) {
    return Response.json(
      { error: "NIGHTSHIFT_API_URL is not configured for this deployment" },
      { status: 503 },
    );
  }

  const target = new URL(`${base}/api/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });

  const method = request.method;
  const body = method === "GET" || method === "HEAD" ? undefined : await request.text();

  try {
    const upstream = await fetch(target, { method, headers, body, cache: "no-store" });
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    return Response.json(
      { error: `upstream unreachable: ${error instanceof Error ? error.message : error}` },
      { status: 502 },
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}
