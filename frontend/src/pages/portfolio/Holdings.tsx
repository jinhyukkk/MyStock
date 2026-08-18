import { useState } from 'react'
import { Link } from 'react-router-dom'
import AllocationDonut from '../../components/AllocationDonut'
import { cur, fmt } from '../../format'
import { usePortfolio } from './context'

export default function Holdings() {
  const { pf } = usePortfolio()
  // 종목이 늘면 표 전체를 눈으로 훑게 된다 — 손실·과다비중만 골라볼 수 있게
  const [holdFilter, setHoldFilter] = useState<'all' | 'loss' | 'heavy'>('all')
  // 17종목부터는 "비중 큰 순·손실 큰 순"으로 못 보면 필터만으로는 반쪽이다
  type SortKey = 'value_krw' | 'weight_pct' | 'pnl_krw' | 'pnl_pct'
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean } | null>(null)

  const t = pf.totals
  // 배당이 한 건도 없는 계좌에 열을 하나 더 세우면, 평가손익과 똑같은 숫자가
  // 두 번 나오면서 표만 넓어진다 — 배당이 실제로 있을 때만 총수익을 세운다.
  const hasDiv = t.dividend_krw > 0

  // 필터 → 정렬 → 합계가 전부 같은 행 집합 위에서 계산되어야 한다.
  // 특히 "손실만" 필터의 존재 이유가 손실 파악인데 합계가 없으면 눈으로 더하게 된다.
  const rows = pf.holdings.filter(h => holdFilter === 'all' ? true
    : holdFilter === 'loss' ? (h.pnl ?? 0) < 0
    : (h.weight_pct ?? 0) >= 20)
  // pnl_krw는 매수 환율이 없으면 null이다 — 그대로 쓰면 USD 종목이 정렬에서
  // 바닥으로 가고 합계에서 통째로 빠져서, 상단 스트립의 평가손익과 다른 숫자가
  // 한 화면에 선다. 백엔드와 같은 방식(현재 환율 근사)으로 채워 분모를 맞춘다.
  const pnlKrwOf = (h: typeof rows[number]) =>
    h.pnl_krw ?? (h.pnl !== null && t.usdkrw ? h.pnl * (h.currency === 'USD' ? t.usdkrw : 1) : null)
  const sorted = sort ? [...rows].sort((a, b) => {
    const val = (h: typeof rows[number]) =>
      (sort.key === 'pnl_krw' ? pnlKrwOf(h) : h[sort.key]) ?? -Infinity
    return sort.desc ? val(b) - val(a) : val(a) - val(b)
  }) : rows
  const sumValueKrw = rows.reduce((s, h) => s + (h.value_krw ?? 0), 0)
  const sumPnlKrw = rows.reduce((s, h) => s + (pnlKrwOf(h) ?? 0), 0)
  const pnlPartial = rows.some(h => pnlKrwOf(h) === null)
  // 같은 안내문("환 기여 미상")이 USD 행마다 반복되면 노이즈다 — 표 위 한 줄로 승격
  const fxUnknown = pf.holdings.filter(h => h.currency === 'USD' && h.fx_pnl_krw === null).length

  const thSort = (label: string, key: SortKey) => (
    <th role="button" style={{ cursor: 'pointer' }} title="클릭해서 정렬"
        aria-sort={sort?.key === key ? (sort.desc ? 'descending' : 'ascending') : undefined}
        onClick={() => setSort(s => s?.key === key ? { key, desc: !s.desc } : { key, desc: true })}>
      {label}{sort?.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}</th>
  )
  return (
    <>
      <div className="grid-2">
        <div className="card">
          {/* 같은 손익을 두 분모로 나눠 함께 보여준다 — 하나만 두면 현금 비중이 큰 계좌에서
              체감 손실이 부풀려 읽히고 포지션 사이즈 판단이 통째로 틀어진다. */}
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            총자산 대비 {t.total_pnl_pct_of_asset >= 0 ? '+' : ''}{t.total_pnl_pct_of_asset}%
            {' · '}보유 종목 평가손익이며 실현손익은{' '}
            <Link to="/portfolio/realized">복기</Link> 탭에 따로 있습니다</div>
          {/* 주가 손익만 총자산 카드에 두면 배당으로 받은 현금은 예수금에 섞여
              사라진다 — 커버드콜·고배당 계좌의 성과가 계속 낮게만 보인다. */}
          {hasDiv && <div style={{ fontSize: 12, marginTop: 4 }}>
            <span style={{ color: 'var(--text-dim)' }}>배당 포함 총수익 </span>
            <strong className={(t.total_return_krw ?? 0) >= 0 ? 'pos' : 'neg'}>
              {(t.total_return_krw ?? 0) >= 0 ? '+' : ''}₩{fmt(t.total_return_krw)}
              {t.total_return_pct !== null && ` (원금 대비 ${t.total_return_pct}%)`}</strong>
            <span style={{ color: 'var(--text-dim)' }}>
              {' '}— 평가손익 + 누적 배당 ₩{fmt(t.dividend_krw)} (세후)</span></div>}
          {/* 평가액·현금 합계는 위 pf-strip이 모든 탭에서 이미 보여준다 — 같은 화면에
              두 번 쓰지 않는다. 여기엔 통화 분해(₩+$)처럼 스트립에 없는 것만 남긴다. */}
          {(t.cash_usd ?? 0) > 0 && <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
            현금 구성 ₩{fmt(t.cash_krw)} + ${fmt(t.cash_usd)}</div>}
          {/* 예수금·목표 종목 수·증권사 연동은 설정 탭으로 옮겼다. 다만 예수금이
              0이면 1% 리스크 수량이 계산되지 않으므로 그 사실만 여기서 알린다. */}
          {t.cash_krw === 0 && (t.cash_usd ?? 0) === 0 &&
            <div className="warn-box" style={{ marginTop: 8 }}>
              예수금이 0입니다 — 총자산과 1% 리스크 수량이 계산되지 않습니다.{' '}
              <Link to="/portfolio/settings"><strong>설정</strong></Link> 탭에서 입력하세요.</div>}
        </div>
        <div className="card">
          {pf.allocation.length > 0 ? (
            <AllocationDonut allocation={pf.allocation} />
          ) : <div style={{ color: 'var(--text-dim)' }}>보유 종목 없음</div>}
        </div>
      </div>

      <div className="card">
        <strong>보유 종목</strong>
        {/* 이 수량·평단이 증권사 실데이터인지 손으로 적은 원장인지 — 근거가 다르면
            같은 숫자라도 신뢰도가 다르다 */}
        {pf.broker.synced_at && <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
          {' '}증권사 잔고 기준 · {pf.broker.synced_at.replace('T', ' ')}</span>}
        {pf.holdings.length === 0 && <div className="empty">
          보유 종목이 없습니다.<br />
          {pf.broker.synced_at
            ? <>증권사 잔고에도 보유 종목이 없습니다. 계좌를 잘못 골랐다면{' '}
                <Link to="/portfolio/settings"><strong>설정</strong></Link> 탭에서 다시 선택하세요.</>
            : <><Link to="/portfolio/journal"><strong>매매 기록</strong></Link> 탭에 체결 내역을
                기록하면 평단·수익률·실현손익이 계산됩니다.</>}
        </div>}
        {pf.holdings.length > 0 && <div className="filter-chips">
          {([
            { key: 'all', label: '전체' },
            { key: 'loss', label: '손실만' },
            { key: 'heavy', label: '비중 20%↑' },
          ] as const).map(f => {
            const n = f.key === 'all' ? pf.holdings.length
              : f.key === 'loss' ? pf.holdings.filter(h => (h.pnl ?? 0) < 0).length
              : pf.holdings.filter(h => (h.weight_pct ?? 0) >= 20).length
            return (
              <button key={f.key} className={`chip${holdFilter === f.key ? ' on' : ''}`}
                      aria-pressed={holdFilter === f.key}
                      onClick={() => setHoldFilter(f.key)}>
                {f.label} <span className="chip-n">{n}</span>
              </button>
            )
          })}
        </div>}
        <details className="premises">
          <summary>열 설명 보기</summary>
          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.7 }}>
            손익 (비용 전) — 매도 수수료·세금 차감 전. 셀에 마우스를 올리면
            전량 청산 시 확정 손익과 회수 금액이 보입니다
            {hasDiv && <><br />배당 포함 — 누적 배당(세후) 포함, 매도한 수량에 대해 받은
              배당도 이 종목이 준 현금이므로 합산합니다</>}
          </div>
        </details>
        {fxUnknown > 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 6 }}>
          미국 주식 {fxUnknown}종목은 매수 시점 환율이 원장에 없어 원화 손익의
          주가/환 기여를 분리하지 못합니다 — 환 영향이 없다는 뜻이 아닙니다.</div>}
        <div className="table-scroll table-cards">
        <table>
          {/* "전량 청산 시"는 전 행에서 손익과 1% 미만 차이 — 거의 같은 숫자를
              두 열로 세우면 표만 넓어진다(1280px에서도 가로 넘침). 손익 툴팁으로 강등. */}
          <thead><tr><th>종목</th><th>수량</th><th>평단가</th><th>현재가</th>
            <th>평가액</th>{thSort('KRW 환산', 'value_krw')}{thSort('비중', 'weight_pct')}
            {thSort('손익 (비용 전)', 'pnl_krw')}
            {thSort('수익률', 'pnl_pct')}
            {hasDiv && <th>배당 포함</th>}</tr></thead>
          <tbody>
            {sorted.map(h => (
              <tr key={h.symbol}>
                {/* 긴 종목명은 잘린다("Taiwan Semiconductor Manufactur…") — 심볼이
                    더 짧고 정확한 식별자라 함께 보여준다 */}
                <td><Link to={`/ticker/${h.symbol}`}><strong>{h.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {h.symbol} · {h.currency}</span></Link>
                  {/* 평단이 실거래 산물이 아니면 이 행의 손익·수익률이 전부 그 위에 선다 */}
                  {h.basis_adjusted && <span className="warn" style={{ fontSize: 11 }}
                    title="원가에 평단 맞춤용 보정 로트가 섞여 있습니다. 평단·손익·수익률은 실제 체결가만으로 만든 값이 아닙니다.">
                    {' '}보정 평단</span>}
                  {/* 평단을 모르는 채 현재가로 채운 행은 손익 0이 '본전'으로 읽힌다 */}
                  {h.basis_missing && <span className="warn" style={{ fontSize: 11 }}
                    title="증권사가 평균매입가를 제공하지 않아 현재가로 채웠습니다. 이 행의 손익·수익률은 본전이 아니라 '평단 모름'입니다.">
                    {' '}평단 미제공</span>}</td>
                {/* sec: 좁은 화면 카드 모드에서 숨기는 보조 필드 — 종목당 10칸을 다
                    세로로 쌓으면 17종목이 끝없는 스크롤이 된다. 상세는 종목 페이지에. */}
                <td data-label="수량" className="sec">{fmt(h.quantity)}</td>
                <td data-label="평단가" className="sec">{cur(h.currency, h.avg_price)}</td>
                <td data-label="현재가" className="sec">{cur(h.currency, h.close)}</td>
                <td data-label="평가액" className="sec">{cur(h.currency, h.value)}</td>
                {/* 통화가 섞이면 종목 통화만으로는 포지션 크기를 나란히 볼 수 없다 */}
                <td data-label="KRW 환산">₩{fmt(h.value_krw)}</td>
                <td data-label="비중" className={(h.weight_pct ?? 0) >= 20 ? 'warn' : ''}>
                  {h.weight_pct === null ? '—' : `${h.weight_pct}%`}</td>
                <td data-label="손익 (비용 전)" className={(h.pnl ?? 0) >= 0 ? 'pos' : 'neg'}
                    title={[
                      h.currency === 'USD' && h.fx_pnl_krw !== null
                        ? `원화 손익 ₩${fmt(h.pnl_krw)} = 주가 ₩${fmt(h.price_pnl_krw)} + 환 ₩${fmt(h.fx_pnl_krw)}` : '',
                      h.net_pnl !== null
                        ? `전량 청산 시 ${cur(h.currency, h.net_pnl)} · 회수 ${cur(h.currency, h.net_proceeds)}` : '',
                    ].filter(Boolean).join('\n')}>
                  {cur(h.currency, h.pnl)}
                  {/* 미국주식 비중이 큰 계좌는 원화 손익의 상당 부분이 환이다 —
                      나눠 보지 않으면 '달러 자산이 잘 버텼다'는 착시가 생긴다.
                      환율 미상 안내는 행마다 반복하지 않고 표 위 공지 한 줄로 승격했다. */}
                  {h.currency === 'USD' && h.fx_pnl_krw !== null && h.fx_pnl_krw !== 0 &&
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      환 {h.fx_pnl_krw >= 0 ? '+' : ''}₩{fmt(h.fx_pnl_krw)}</div>}</td>
                <td data-label="수익률" className={(h.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.pnl_pct === null ? '—' : `${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%`}</td>
                {/* 주가로는 마이너스여도 분배금까지 더하면 플러스인 포지션이 있다.
                    배당을 세지 않는 화면은 그 포지션을 팔라고 말하는 것과 같다. */}
                {hasDiv && <td data-label="배당 포함"
                    className={(h.total_return_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.dividend_krw === 0
                    ? <span style={{ color: 'var(--text-dim)' }}>배당 없음</span>
                    : <>{h.total_return_pct === null
                        ? <span style={{ color: 'var(--text-dim)' }}
                                title="매수 시점 환율이 원장에 없어 원화 평가손익을 확정할 수 없습니다 — 배당을 더할 기준 자체가 없는 것이지, 배당이 없다는 뜻이 아닙니다">—</span>
                        : `${h.total_return_pct >= 0 ? '+' : ''}${h.total_return_pct}%`}
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        배당 ₩{fmt(h.dividend_krw)}</div></>}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {/* 필터를 건 상태의 합계 — "손실만"의 존재 이유가 손실 파악인데
            합계가 없으면 눈으로 더해야 한다. tfoot 대신 줄 하나: 모바일 카드
            모드에서 tfoot은 깨진다. */}
        {rows.length > 0 && <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 6 }}>
          {holdFilter === 'all' ? '합계' : '필터 합계'} {rows.length}종목 ·
          평가 ₩{fmt(Math.round(sumValueKrw))} · 손익{' '}
          <span className={sumPnlKrw >= 0 ? 'pos' : 'neg'}>
            {sumPnlKrw >= 0 ? '+' : ''}₩{fmt(Math.round(sumPnlKrw))}</span>
          {pnlPartial && ' (원화 환산 불가 종목 제외)'}</div>}
      </div>
    </>
  )
}
