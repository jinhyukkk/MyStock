import { useCallback, useEffect, useRef, useState } from 'react'
import { get } from '../api'
import type { TickerDetailReady, TickerDetailResponse } from '../types'

const POLL_MS = 2000
/** 60초. 상한이 없으면 백엔드가 조용히 죽었을 때 탭이 영원히 2초마다 요청을 쏜다. */
const MAX_POLLS = 30

export type DetailStatus = 'loading' | 'pending' | 'ready' | 'failed'

/** 종목 상세를 받되, 미등록 종목이면 수집이 끝날 때까지 폴링한다.
 *
 *  소비자가 개요(TickerDetail)와 분석(Analysis) 둘이라 훅으로 뽑았다. 페이지마다
 *  폴링을 복붙하면 상한·정리 규칙이 갈라지고 한쪽만 고쳐지는 일이 생긴다. */
export function useTickerDetail(symbol: string | undefined) {
  const [detail, setDetail] = useState<TickerDetailReady | null>(null)
  const [status, setStatus] = useState<DetailStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState(Date.now())
  // 심볼이 바뀌면 세대를 올린다. 없으면 A→B로 이동하는 중에 도착한 A의 응답이
  // B 화면을 덮어쓴다.
  const gen = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const run = useCallback((mine: number, tries: number) => {
    if (!symbol) return
    get<TickerDetailResponse>(`/api/tickers/${symbol}`).then(res => {
      if (gen.current !== mine) return
      // status가 없는 응답은 구버전 백엔드다 — 그때는 200이면 곧 완성본이었다.
      const s: DetailStatus = (res as Partial<{ status: DetailStatus }>).status ?? 'ready'
      if (s === 'pending') {
        if (tries + 1 >= MAX_POLLS) {
          // detail은 status==='ready'일 때만 non-null이어야 한다(훅 계약). ready로
          // 남아있던 옛 값을 여기서 비우지 않으면 status는 failed인데 detail은
          // 이전 조회의 값이 non-null로 남아 화면이 "최신"으로 오해한다.
          setDetail(null)
          setStatus('failed')
          setError('수집이 오래 걸립니다 — 다시 시도하세요.')
          return
        }
        // reload 중 재조회가 pending으로 끝나면 옛 ready 값을 여기서 비운다.
        // reload() 자체에서 비우면(과거 구현) 재조회 요청이 나가는 순간부터
        // 화면 전체가 스켈레톤으로 깜빡인다 — 여기서만 비우면 실제로
        // "더 이상 ready가 아니다"라고 확정된 시점에만 사라진다.
        setDetail(null)
        setStatus('pending')
        timer.current = setTimeout(() => run(mine, tries + 1), POLL_MS)
        return
      }
      if (s === 'failed') {
        setDetail(null)
        setStatus('failed')
        setError((res as { message: string }).message)
        return
      }
      setDetail(res as TickerDetailReady)
      setStatus('ready')
      setError(null)
      setLoadedAt(Date.now())
    }).catch(e => {
      if (gen.current !== mine) return
      setDetail(null)
      setStatus('failed')
      setError(String(e))
    })
  }, [symbol])

  // detail을 여기서 비우거나 status를 loading으로 내리면 새로고침 버튼을 누를 때마다
  // (관심 등록·매매 기록 저장 후 reload도 마찬가지) 화면이 통째로 스켈레톤으로
  // 사라졌다가 다시 그려진다 — 요청이 나가는 그 순간에 이미 detail이 null이 되기
  // 때문이다. 대신 run()의 각 종료 분기에서만 detail을 비워서, 응답이 실제로
  // ready가 아닌 것으로 확정된 시점에만 화면이 바뀌게 한다. 재조회 중에는 이전
  // ready 화면이 그대로 남고, 버튼의 busy 플래그만으로 "갱신 중…"을 표시한다.
  const reload = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    gen.current += 1
    setError(null)
    run(gen.current, 0)
  }, [run])

  useEffect(() => {
    gen.current += 1
    const mine = gen.current
    setDetail(null)
    setStatus('loading')
    setError(null)
    run(mine, 0)
    return () => {
      // 세대를 여기서도 올려야 한다 — in-flight fetch가 언마운트 시점에 타이머를
      // 아직 예약하지 않은 상태(timer.current가 null)라면 clearTimeout으로는
      // 지울 게 없다. 이후 fetch가 resolve되면 .then의 유일한 가드는
      // gen.current !== mine인데, 세대를 안 올리면 그 응답이 가드를 통과해
      // 언마운트된 훅 위에서 setTimeout으로 폴링을 다시 예약해버린다 —
      // 떠난 화면이 상한(30회)까지 계속 요청을 쏘는 원인이 된다.
      gen.current += 1
      if (timer.current) clearTimeout(timer.current)
    }
  }, [symbol, run])

  return { detail, status, error, loadedAt, reload }
}
