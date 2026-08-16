import { Link } from 'react-router-dom'
import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Realized() {
  const { pf } = usePortfolio()
  return (
    <>
      {/* count > 0 일 때만 렌더하면 매도 기록이 없는 계좌에서 카드가 통째로 사라져
          "이 앱에는 실현손익 기능이 없다"로 읽힌다. 시스템이 돈을 벌고 있는지
          확인할 자리가 있다는 사실 자체가 화면에 남아 있어야 한다. */}
      {pf.realized && <div className="card">
        <strong>실현손익 · 매매 복기</strong>
        {pf.realized.stats.count === 0 ? (
          <div className="empty">
            아직 매도 기록이 없어 확정된 손익이 없습니다.<br />
            매도를 기록하면 <strong>누적 실현손익 · 승률 · 손익비 · 진입 등급별 성과</strong>가
            여기에 집계됩니다 — 위 평가손익은 아직 확정되지 않은 값입니다.
            {pf.realized.stats.excluded_count > 0 &&
              <><br />※ 평단 보정용으로 표시된 {pf.realized.stats.excluded_count}건은
                집계에서 제외됩니다.</>}
          </div>
        ) : <>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>총 실현손익 (비용 차감 후)</div>
            <div className={pf.realized.stats.total_pnl_krw >= 0 ? 'pos' : 'neg'}
                 style={{ fontWeight: 700, fontSize: 18 }}>
              {pf.realized.stats.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(pf.realized.stats.total_pnl_krw)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              수수료·세금 ₩{fmt(pf.realized.stats.cost_krw)} 차감
              {pf.realized.stats.fx_pnl_krw !== 0 &&
                ` · 이 중 환손익 ${pf.realized.stats.fx_pnl_krw >= 0 ? '+' : ''}₩${fmt(pf.realized.stats.fx_pnl_krw)}`}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>승률 (비용 차감 후)</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.realized.stats.win_rate ?? '—'}%
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> ({pf.realized.stats.count}회)</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>평균 수익 / 평균 손실</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>
              <span className="pos">{pf.realized.stats.avg_win_pct !== null ? `+${pf.realized.stats.avg_win_pct}%` : '—'}</span>
              {' / '}
              <span className="neg">{pf.realized.stats.avg_loss_pct !== null ? `${pf.realized.stats.avg_loss_pct}%` : '—'}</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>손익비</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.realized.stats.payoff_ratio ?? '—'}</div>
          </div>
        </div>
        {/* 해외 양도세는 체결 시점에 떼이지 않는다. 위의 '비용 차감 후' 실현손익만
            보면 이듬해 5월에 낼 돈까지 이미 번 돈으로 세고 다시 투입하게 된다. */}
        {pf.realized.overseas_tax.gain_krw !== 0 && <div style={{ marginTop: 12, padding: 12,
              borderRadius: 6, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            {pf.realized.overseas_tax.year}년 해외주식 양도세 (이듬해 5월 신고·납부)</div>
          <div style={{ display: 'flex', gap: 28, marginTop: 8, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>올해 해외 실현이익</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}
                   className={pf.realized.overseas_tax.gain_krw >= 0 ? 'pos' : 'neg'}>
                {pf.realized.overseas_tax.gain_krw >= 0 ? '+' : ''}₩{fmt(pf.realized.overseas_tax.gain_krw)}</div>
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>기본공제 잔여 (연 250만)</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}>
                ₩{fmt(pf.realized.overseas_tax.deduction_left_krw)}</div>
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                예상 세액 ({pf.realized.overseas_tax.rate_pct}%)</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}
                   className={pf.realized.overseas_tax.tax_krw > 0 ? 'neg' : ''}>
                ₩{fmt(pf.realized.overseas_tax.tax_krw)}</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
            위 실현손익은 이 세금을 빼기 전 값입니다 — 연간 통산 후 과세되므로 손실 실현이
            세액을 줄입니다. 환차익도 과세 대상에 포함한 추정이며, 실제 신고는 증권사
            자료를 기준으로 하세요.</div>
        </div>}
        {pf.realized.stats.cost_estimated && <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 8 }}>
          ⓘ 일부 체결의 수수료·세금이 기록돼 있지 않아 <strong>시장 기본 요율로 추정</strong>했습니다.
          정확한 복기를 원하면 <Link to="/portfolio/journal">매매 기록</Link> 탭에서 실제 비용을 넣으세요.</div>}
        {/* 인위적 체결가가 승률에 섞이면 복기 전체가 거짓이 된다. 뺐다는 사실을
            숨기면 이번엔 "왜 건수가 안 맞지"로 신뢰가 깨진다 — 몇 건인지 밝힌다. */}
        {pf.realized.stats.excluded_count > 0 && <div className="warn-box" style={{ marginTop: 8 }}>
          ⚠ 평단 보정용으로 표시된 <strong>{pf.realized.stats.excluded_count}건</strong>은 체결가가
          인위적이라 위 승률·손익비·실현손익 집계에서 제외했습니다. 아래 표에는 「보정」 배지로 남아 있습니다.</div>}
        {pf.realized.stats.by_entry_grade.length > 0 && <>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 12 }}>
            진입 등급별 성과 — 시그널을 따른 매매와 아닌 매매의 성적을 분리해서 보세요</div>
          <table style={{ marginTop: 6 }}>
            <thead><tr><th>진입 시 등급</th><th>횟수</th><th>승률</th><th>평균 수익률</th></tr></thead>
            <tbody>
              {pf.realized.stats.by_entry_grade.map(g => (
                <tr key={g.grade}>
                  <td>{g.grade}</td>
                  <td>{g.count}</td>
                  <td>{g.win_rate}%</td>
                  <td className={g.avg_pnl_pct >= 0 ? 'pos' : 'neg'}>
                    {g.avg_pnl_pct >= 0 ? '+' : ''}{g.avg_pnl_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>}
        <div className="table-scroll table-cards" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>매도일</th><th>심볼</th><th>수량</th><th>평단</th><th>매도가</th>
            <th>비용</th><th>실현손익 (net)</th><th>수익률</th><th>원화 손익</th>
            <th>진입 등급</th><th>메모</th></tr></thead>
          <tbody>
            {pf.realized.entries.map((r, i) => (
              <tr key={i}>
                <td style={{ textAlign: 'left' }}>{r.trade_date}</td>
                <td data-label="심볼">{r.symbol}</td>
                <td data-label="수량">{fmt(r.quantity)}</td>
                <td data-label="평단">{fmt(r.buy_price)}</td>
                <td data-label="매도가">{fmt(r.sell_price)}</td>
                <td data-label="비용" style={{ color: 'var(--text-dim)' }}
                    title={r.cost_estimated ? '시장 기본 요율로 추정한 값' : '입력된 실제 비용'}>
                  {fmt(r.cost)}{r.cost_estimated && '*'}</td>
                <td data-label="실현손익 (net)" className={r.pnl >= 0 ? 'pos' : 'neg'}
                    title={`비용 차감 전 ${fmt(r.pnl_gross)}`}>{fmt(r.pnl)}</td>
                <td data-label="수익률" className={r.pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {r.pnl_pct >= 0 ? '+' : ''}{r.pnl_pct}%</td>
                {/* 매수·매도 환율을 각각 반영한 값. 환손익을 따로 보여야 "달러 자산이 잘 버텼다"는
                    착시 없이 KR/US 배분을 판단할 수 있다. */}
                <td data-label="원화 손익" className={r.pnl_krw >= 0 ? 'pos' : 'neg'}
                    title={`가격 ${fmt(r.price_pnl_krw)} + 환 ${fmt(r.fx_pnl_krw)} `
                           + `(매수 ${fmt(r.buy_fx)} → 매도 ${fmt(r.sell_fx)})`}>
                  ₩{fmt(r.pnl_krw)}
                  {r.fx_pnl_krw !== 0 && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}(환 {r.fx_pnl_krw >= 0 ? '+' : ''}{fmt(r.fx_pnl_krw)})</span>}</td>
                <td data-label="진입 등급">{r.entry_grade ?? '—'}</td>
                <td style={{ textAlign: 'left', maxWidth: 200, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={r.note ?? ''}>
                  {r.basis_adjusted && <span className="warn" style={{ fontSize: 11 }}
                    title="평단 맞춤용 보정 로트가 원가에 섞여 있어 집계에서 제외된 건입니다">
                    [보정] </span>}{r.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        </>}
      </div>}
    </>
  )
}
