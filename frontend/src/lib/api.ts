export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}
export const percent = (value: number) => `${Math.round(value * 100)}%`;
export const complete = (stage: string) =>
  ["COMPLETED", "FAILED"].includes(stage);
export const initials = (name: string) =>
  name
    .split(" ")
    .map((s) => s[0])
    .join("");
