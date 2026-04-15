const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

async function handler(
  request: Request,
  { params }: { params: Promise<{ path?: string[] }> },
) {
  const { path } = await params;
  const segments = path ?? [];
  const target = `${BACKEND}/api/v1/${segments.join("/")}`;
  const url = new URL(target);

  // 保留查询参数
  const reqUrl = new URL(request.url);
  reqUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

  const headers = new Headers(request.headers);
  headers.delete("host");

  const init: RequestInit = {
    method: request.method,
    headers,
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  const res = await fetch(url.toString(), init);

  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
