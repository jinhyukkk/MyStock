async function fail(res: Response): Promise<never> {
  // FastAPI 에러는 {"detail": "..."} — 사용자에게는 detail만 보여준다
  const text = await res.text()
  let msg = text
  try {
    const d = JSON.parse(text).detail
    // pydantic 422는 detail이 배열
    msg = Array.isArray(d) ? d.map((e: { msg?: string }) => e.msg ?? '').join(', ') : (d ?? text)
  } catch { /* JSON 아니면 원문 그대로 */ }
  throw new Error(msg || `HTTP ${res.status}`)
}
export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) await fail(res)
  return res.json()
}
export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return res.json()
}
export async function put<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return res.json()
}
export async function patch<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return res.json()
}
export async function del(path: string): Promise<void> {
  const res = await fetch(path, { method: 'DELETE' })
  if (!res.ok) await fail(res)
}
