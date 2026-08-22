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
/** 200인데 JSON이 아니면 대부분 백엔드가 그 경로를 모르는 경우다 — FastAPI의 SPA 폴백
 *  (main.py의 `/{path:path}`)이 index.html을 200으로 돌려주기 때문. 프론트만 새로 빌드하고
 *  백엔드를 재시작하지 않았을 때 생긴다. 여기서 잡지 않으면 화면에는 JSON 파싱 오류
 *  ("Unexpected token '<'")만 뜨고, 진짜 원인인 "서버가 구버전"이라는 사실은 어디에도 안 나온다. */
async function json<T>(res: Response, path: string): Promise<T> {
  const ct = res.headers.get('content-type') ?? ''
  if (!ct.includes('json')) {
    throw new Error(`서버가 ${path} 를 모릅니다 — 백엔드가 구버전일 수 있습니다. `
      + '백엔드를 재시작한 뒤 다시 시도하세요.')
  }
  return res.json() as Promise<T>
}
export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) await fail(res)
  return json<T>(res, path)
}
export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return json<T>(res, path)
}
export async function put<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return json<T>(res, path)
}
export async function patch<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) await fail(res)
  return json<T>(res, path)
}
export async function del<T = void>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE' })
  if (!res.ok) await fail(res)
  // 204나 빈 본문이면 파싱할 게 없다 — 응답을 쓰는 쪽만 타입을 지정한다
  return res.status === 204 ? (undefined as T) : json<T>(res, path)
}
