const BASE_URL = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null && "message" in detail
          ? String((detail as { message: string }).message)
          : `API error (${status})`;
    super(message);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function get<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { signal });
  return handleResponse<T>(response);
}

export async function post<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return handleResponse<T>(response);
}

export async function del(path: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "DELETE",
    signal,
  });
  await handleResponse<void>(response);
}

export function buildDownloadUrl(path: string): string {
  return `${BASE_URL}${path}`;
}
