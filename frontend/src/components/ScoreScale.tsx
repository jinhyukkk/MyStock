import type { ScoreCuts } from '../types'

/** 점수가 등급 컷 어디쯤인지 보여주는 눈금.
 *
 *  숫자만 던지면 "-21이 얼마나 안 좋은 건지"가 화면에 없다. 더 나쁜 건
 *  스윙과 중장기의 컷이 서로 다르다는 사실(매수컷 +11 vs +36)이 어디에도
 *  안 보인다는 점이다 — 같은 자로 읽으면 +39는 대단해 보이고 -21은 사소해
 *  보이지만, 실제로는 둘 다 자기 척도에서 극단에 가깝다.
 */
const DOMAIN = 100  // 지표 점수 가중평균의 이론적 범위

export default function ScoreScale({ score, cuts, kind }: {
  score: number; cuts: ScoreCuts; kind: 'swing' | 'longterm'
}) {
  const pos = (v: number) =>
    (Math.max(-DOMAIN, Math.min(DOMAIN, v)) + DOMAIN) / (2 * DOMAIN) * 100
  const label = kind === 'swing' ? '스윙' : '중장기'
  const title = `${label} ${score.toFixed(0)}점 — 이 척도의 컷: `
    + `강력매수 ${cuts.strong_buy} / 매수 ${cuts.buy} / 매도 ${cuts.sell} / 강력매도 ${cuts.strong_sell}. `
    + '스윙과 중장기는 컷이 달라 두 점수를 같은 자로 비교할 수 없습니다.'
  const color = score > 0 ? 'var(--buy)' : score < 0 ? 'var(--sell)' : 'var(--text-dim)'
  return (
    <div className="score-scale" title={title}
         role="meter" aria-valuenow={Math.round(score)}
         aria-valuemin={-DOMAIN} aria-valuemax={DOMAIN} aria-label={title}>
      {/* 중립 구간(매도컷~매수컷)을 바탕으로 깔면 컷 밖으로 나갔는지가 한눈에 보인다 */}
      <span className="score-scale-neutral"
            style={{ left: `${pos(cuts.sell)}%`, width: `${pos(cuts.buy) - pos(cuts.sell)}%` }} />
      {[cuts.strong_sell, cuts.sell, cuts.buy, cuts.strong_buy].map((c, i) => (
        <span key={i} className={`score-scale-cut${i === 0 || i === 3 ? ' strong' : ''}`}
              style={{ left: `${pos(c)}%` }} />
      ))}
      <span className="score-scale-dot" style={{ left: `${pos(score)}%`, background: color }} />
    </div>
  )
}
