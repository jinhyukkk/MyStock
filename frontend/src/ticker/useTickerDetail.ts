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
          setStatus('failed')
          setError('수집이 오래 걸립니다 — 다시 시도하세요.')
          return
        }
        setStatus('pending')
        timer.current = setTimeout(() => run(mine, tries + 1), POLL_MS)
        return
      }
      if (s === 'failed') {
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
      setStatus('failed')
      setError(String(e))
    })
  }, [symbol])

  const reload = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    gen.current += 1
    setDetail(null)
    setStatus('loading')
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
