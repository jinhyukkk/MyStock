/** 갱신 시각 표기 — "2026-08-15T23:04:17" 같은 ISO 원문은
 *  "몇 분 전인가"를 즉시 알려주지 않아 신선도 판단에 인지 비용이 든다. */

/** 백엔드는 타임존 없는 로컬 시각을 보낸다 (datetime.now().isoformat()). */
export const parseLocal = (iso: string | null): Date | null => {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export const relativeTime = (iso: string | null, now: number = Date.now()): string => {
  const d = parseLocal(iso)
  if (!d) return '—'
  const sec = Math.floor((now - d.getTime()) / 1000)
  if (sec < 0) return '방금'
  if (sec < 60) return '방금'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}분 전`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}시간 전`
  return `${Math.floor(hr / 24)}일 전`
}

/** 이 시각을 넘기면 "낡은 데이터"로 본다. 백엔드 자동 갱신이 1시간 주기이므로
 *  2주기(2시간)를 놓쳤다면 갱신 루프가 멈췄거나 탭이 오래 열려 있었다는 뜻이다. */
export const STALE_AFTER_MIN = 120

export const isStale = (iso: string | null, now: number = Date.now()): boolean => {
  const d = parseLocal(iso)
  if (!d) return true
  return (now - d.getTime()) / 60000 > STALE_AFTER_MIN
}
