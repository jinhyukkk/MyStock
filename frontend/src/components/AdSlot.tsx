import { useEffect } from 'react'

// Vite 는 VITE_ 접두 변수만 클라이언트 번들에 넣는다. 둘 다 있어야 광고가 뜬다 —
// 로컬 개발처럼 비어 있으면 빈 칸조차 그리지 않아 레이아웃에 구멍이 생기지 않는다.
const CLIENT = import.meta.env.VITE_ADSENSE_CLIENT as string | undefined
const SCRIPT_ID = 'adsbygoogle-js'

declare global {
  interface Window { adsbygoogle?: unknown[] }
}

/** 애드센스 스크립트를 문서에 한 번만 꽂는다. 여러 슬롯이 같은 페이지에 있어도
 *  태그가 중복되면 콘솔에 "Only one AdSense head tag" 경고가 나고 광고가 안 뜬다. */
function ensureScript(client: string) {
  if (document.getElementById(SCRIPT_ID)) return
  const s = document.createElement('script')
  s.id = SCRIPT_ID
  s.async = true
  s.crossOrigin = 'anonymous'
  s.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(client)}`
  document.head.appendChild(s)
}

/**
 * 구글 애드센스 반응형 광고 한 칸. `slot` 은 애드센스 콘솔의 광고 단위 ID(숫자).
 * 마운트마다 push 하므로 SPA 라우팅으로 돌아와도 다시 채워진다 — 같은 <ins> 에
 * 두 번 push 하면 "already have ads in them" 오류가 나니 의존성 배열로 한 번만 돈다.
 */
export default function AdSlot({ slot, className = '' }: { slot?: string; className?: string }) {
  const enabled = Boolean(CLIENT && slot)
  useEffect(() => {
    if (!enabled) return
    ensureScript(CLIENT!)
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({})
    } catch {
      /* 광고 차단기 등으로 스크립트가 막히면 push 가 throw 할 수 있다 — 화면은 그대로 둔다 */
    }
  }, [enabled, slot])
  if (!enabled) return null
  return (
    <div className={`fv-ad ${className}`} aria-label="광고">
      <ins className="adsbygoogle" style={{ display: 'block' }}
           data-ad-client={CLIENT} data-ad-slot={slot}
           data-ad-format="auto" data-full-width-responsive="true" />
    </div>
  )
}
