const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
const API_BASE_URL = (apiBaseUrl ?? "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");

if (process.env.NODE_ENV === "development" && !apiBaseUrl) {
  console.error("NEXT_PUBLIC_API_BASE_URL is missing. Falling back to http://127.0.0.1:8000/api/v1.");
}

type RequestOptions = RequestInit & {
  json?: unknown;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const url = `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;

  if (process.env.NODE_ENV === "development") {
    console.info(`Admin API request: ${options.method ?? "GET"} ${url}`);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      body: options.json !== undefined ? JSON.stringify(options.json) : options.body,
      credentials: "include"
    });
  } catch {
    throw new Error("Could not reach backend");
  }

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(errorBody?.error?.message ?? "Request failed");
  }

  return response.json() as Promise<T>;
}

export function getApiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
