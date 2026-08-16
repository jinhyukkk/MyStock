import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Risk() {
  const { pf } = usePortfolio()
  return (
    <>
      {pf.risk && <div className="card">
        <strong>계좌 리스크</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}현재 보유 수량 기준 근사 (환율 고정) · {pf.risk.calendar_note}</span>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>연환산 변동성</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.volatility_pct}%</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              연 {Math.round(pf.risk.periods_per_year)}회 관측 기준</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>계좌 최대 낙폭 (MDD)</div>
            <div className="neg" style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.mdd_pct}%</div>
            {/* 실제 계좌가 겪은 낙폭이 아니다 — 라벨이 없으면 실적으로 읽힌다 */}
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{pf.risk.mdd_note}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>최대 종목 비중</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}
                 className={(pf.risk.max_weight_pct ?? 0) >= 30 ? 'neg' : ''}>
              {pf.risk.max_weight_pct}%
              {(pf.risk.max_weight_pct ?? 0) >= 30 && <span style={{ fontSize: 12 }}> ⚠ 집중</span>}</div>
          </div>
        </div>
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>종목</th><th>총자산 대비 비중</th></tr></thead>
          <tbody>
            {pf.risk.weights.map(w => (
              <tr key={w.symbol}>
                <td style={{ textAlign: 'left' }}>{w.name}</td>
                <td className={w.weight_pct >= 30 ? 'neg' : ''}>{w.weight_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {/* 최대 종목 비중 9.3%는 안전해 보이지만 상관 0.7+ 로 묶인 종목들이
            동반 하락하면 계좌가 맞는 타격은 그 합에 가깝다. */}
        {pf.risk.clusters.length > 0 && <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            상관 {pf.risk.cluster_threshold} 이상으로 묶인 그룹 — 사실상 하나의 포지션</div>
          <table style={{ marginTop: 6 }}>
            <thead><tr><th>그룹</th><th>합산 비중</th></tr></thead>
            <tbody>
              {pf.risk.clusters.map(c => (
                <tr key={c.symbols.join()}>
                  <td style={{ textAlign: 'left' }}>{c.names.join(' · ')}</td>
                  <td className={c.weight_pct >= 30 ? 'neg' : ''}>{c.weight_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(pf.risk.max_cluster_pct ?? 0) >= 30 && <div className="warn-box" style={{ marginTop: 8 }}>
            ⚠ 가장 큰 그룹이 총자산의 {pf.risk.max_cluster_pct}%입니다 — 종목별 비중은
            분산돼 보여도 동반 하락 시에는 한 종목에 그만큼 걸어둔 것과 같습니다.</div>}
        </div>}
        {pf.risk.corr && <>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 12 }}>
            보유 종목 간 일간수익률 상관계수 — 0.7 이상이면 사실상 같은 포지션</div>
          <div className="table-scroll" style={{ marginTop: 6 }}>
          <table>
            <thead><tr><th></th>
              {pf.risk.corr.symbols.map(s => <th key={s}>{s}</th>)}</tr></thead>
            <tbody>
              {pf.risk.corr.symbols.map((s, i) => (
                <tr key={s}>
                  <td style={{ textAlign: 'left' }}><strong>{s}</strong></td>
                  {pf.risk!.corr!.matrix[i].map((v, j) => (
                    <td key={j} className={i !== j && v >= 0.7 ? 'neg' : ''}>
                      {v.toFixed(2)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>}
      </div>}

      {/* 종목마다 1% 룰을 지켜도 합산하면 몇 %인지는 어디에도 안 나온다.
          사이즈 오류는 한 번에 계좌를 날리므로 총합을 상시 노출한다. */}
      {pf.open_risk && <div className="card">
        <strong>계좌 총 미결 리스크</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}모든 보유가 각자 손절선에 닿았을 때의 손실 합계 — 등록한 손절 룰이 있으면 그 값,
          없으면 2×ATR 가정</span>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>총 리스크</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}
                 className={pf.open_risk.over_limit ? 'neg' : ''}>
              {pf.open_risk.total_risk_pct ?? '—'}%
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                {' '}(₩{fmt(pf.open_risk.total_risk_krw)})</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>권장 상한</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.open_risk.limit_pct}%</div>
          </div>
        </div>
        {pf.open_risk.over_limit && <div className="warn-box" style={{ marginTop: 10 }}>
          ⚠ 총 리스크가 상한 {pf.open_risk.limit_pct}%를 넘었습니다. 신규 진입보다 기존 포지션
          축소를 먼저 검토하세요. 보유 종목 상관계수가 높으면 실제 동시 손실은 이 합계에 더 가깝습니다.</div>}
        {/* 룰이 없는 종목의 리스크는 '이런 손절을 지킨다면'이라는 가정이다.
            몇 건이 가정인지 말하지 않으면 합계 전체가 사실로 읽힌다. */}
        {pf.open_risk.unregistered_count > 0 && <div className="warn-box" style={{ marginTop: 10 }}>
          ⚠ {pf.open_risk.unregistered_count}종목은 손절 룰이 등록돼 있지 않아 2×ATR을 가정한
          값입니다. 알림은 등록된 룰에서만 울리므로, 이 종목들은 손절선이 뚫려도 아무 통지가 없습니다.</div>}
        <div className="table-scroll table-cards">
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>종목</th><th>손절 기준</th><th>손실액</th><th>총자산 대비</th></tr></thead>
          <tbody>
            {pf.open_risk.rows.map(r => (
              <tr key={r.symbol}>
                <td data-label="종목" style={{ textAlign: 'left' }}>{r.name}</td>
                <td data-label="손절 기준" style={{ color: r.stop_source === 'rule' ? undefined : 'var(--warn)' }}>
                  {r.stop_source === 'rule' ? '등록 룰' : '2×ATR 가정'}</td>
                <td data-label="손실액">₩{fmt(r.risk_krw)}</td>
                <td data-label="총자산 대비"
                    className={(r.risk_pct ?? 0) >= 2 ? 'neg' : ''}>{r.risk_pct ?? '—'}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
          손절가는 자동 예약주문이 아니며 갭 하락 시 계획보다 더 잃을 수 있습니다.</div>
      </div>}
    </>
  )
}
