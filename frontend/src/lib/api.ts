// Same-origin API client. The session lives in an HttpOnly cookie; the CSRF token returned by
// /api/auth/login and /api/auth/me is kept in memory and sent on every state-changing request.

let csrfToken = "";

export function setCsrf(token: string | undefined) {
  csrfToken = token ?? "";
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
      .join("; ");
  }
  if (detail && typeof detail === "object" && "errors" in detail) {
    return (detail as { errors: string[] }).errors.join("\n");
  }
  return `Request failed (${status})`;
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "attendx" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson ? (data as { detail?: unknown }).detail : data;
    if (res.status === 401 && !url.endsWith("/login")) window.dispatchEvent(new Event("attendx:unauthorized"));
    throw new ApiError(res.status, messageFrom(detail, res.status), detail);
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
