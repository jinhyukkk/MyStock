/** finviz 스냅샷 84칸(6쌍 × 14행) 조립. 20_spec.md §4.3 표 그대로다.
 *
 *  칸의 순서·라벨을 화면 컴포넌트가 아니라 여기서 고정하는 이유: 표는 행 단위
 *  마크업 없이 평면으로 깔리기 때문에(SnapshotTable) 배열 순서가 곧 레이아웃이다.
 *  열별로 14칸씩 만든 뒤 행 우선으로 엮는다 — finviz DOM이 열 단위라 옮겨 적기 쉽고,
 *  한 열의 주제(규모·밸류·EPS·수익성·주식수·성과)가 세로로 유지된다.
 *
 *  값의 출처는 두 갈래다. `snapshot.*`은 백엔드가 외부 소스에서 채우고,
 *  나머지는 candles/risk에서 프론트가 계산한다(백엔드에 새 필드를 요구하지 않는다). */
import type { SnapCell } from '../components/quote/SnapshotTable'
import type { Snapshot, TickerDetail as Detail } from '../types'
import { pctCell } from './cells'
import { abbrNum, dateText, intText, levelPct, moneyCell, pctText, ratioText } from './fmt'
import { avgTurnover, avgVolume, changeFromPrev, perfPct, perfYtdPct, range52w, relVolume,
         smaGapPct, volatility } from './stats'

/** 값 없는 칸의 표기 — null·undefined·NaN이 화면에 그대로 나오면 미완성이다. */
const DASH = '—'

/** eps/sales_yoy_ttm_pct의 실제 정의. 필드명(ttm)과 어긋나 있어 칸에 툴팁으로 남긴다. */
const YOY_NOTE = '최근 분기와 전년 동기 분기의 비교입니다 (TTM 합산이 아님)'

export function snapshotCells(detail: Detail, now: number): SnapCell[] {
  const ccy = detail.currency
  const c = detail.candles
  const last = c.at(-1) ?? null
  const risk = detail.risk
  const f = detail.fundamentals
  const p = detail.profile ?? null
  // 스냅샷이 아직 없어도 84칸 격자는 그대로 서 있어야 한다 — 값만 —로 빈다
  const s: Partial<Snapshot> = detail.snapshot ?? {}
  const perf = detail.snapshot?.perf ?? null
  const change = changeFromPrev(c)
  const dy = s.dividend_yield_pct ?? f?.dividend_yield ?? null
  const divYield = dy === null ? null : levelPct(dy)
  const r52 = range52w(c)

  const money = (v: number | null | undefined) => moneyCell(ccy, v)
  /** 배수 칸 — 숫자 뒤에 x를 붙여 퍼센트와 섞이지 않게 한다. */
  const mult = (v: number | null | undefined) => ratioText(v) === '—' ? '—' : `${ratioText(v)}x`
  const abbr = (v: number | null | undefined) => abbrNum(ccy, v)
  /** 성과 칸: 백엔드(price_cache)가 우선이고, 없으면 200봉 안에서 계산해 채운다.
   *  1년 이상은 봉이 모자라 계산 자체가 불가능하므로 백엔드 값만 쓴다. */
  const perfCell = (label: string, be: number | null | undefined, fe: number | null = null) =>
    pctCell(label, be ?? fe)

  const col1: SnapCell[] = [
    { label: '시장·거래소', value: p?.exchange ?? detail.market ?? DASH },
    { label: '시가총액', value: abbr(s.market_cap ?? f?.market_cap ?? null) },
    { label: '기업가치(EV)', value: abbr(s.enterprise_value) },
    { label: '순이익(TTM)', value: abbr(s.income_ttm) },
    { label: '매출(TTM)', value: abbr(s.sales_ttm) },
    { label: 'BPS', value: money(s.book_per_share) },
    { label: '주당 현금', value: money(s.cash_per_share) },
    { label: '예상 배당(주당)', value: money(s.dividend_est) },
    // finviz의 `Dividend TTM 1.02 (0.44%)` — 금액만으로는 비싼지 알 수 없다.
    // 수익률은 계약 v2의 snapshot.dividend_yield_pct가 1순위다. fundamentals 쪽은
    // yfinance 단독이라 §5.1 퍼센트 정규화·스케일 가드를 거치지 않은 값이라 폴백으로만 쓴다.
    { label: '최근 배당(주당)', value: money(s.dividend_ttm), sub: divYield },
    { label: '배당락일', value: dateText(s.dividend_ex_date) },
    // 5년치는 US·KR 모두 소스가 주지 않는다 — 늘 —인 보조값은 라벨만 길게 만든다
    { label: '배당성장 3년', value: pctText(s.dividend_growth_3y_pct) },
    { label: '배당성향', value: levelPct(s.payout_pct) },
    { label: '직원수', value: intText(p?.employees) },
    { label: '상장일', value: dateText(p?.ipo_date) },
  ]

  const col2: SnapCell[] = [
    { label: 'PER', value: ratioText(s.pe ?? f?.per ?? null) },
    { label: '선행 PER', value: ratioText(s.forward_pe) },
    { label: 'PEG', value: ratioText(s.peg) },
    { label: 'PSR', value: ratioText(s.ps) },
    { label: 'PBR', value: ratioText(s.pb ?? f?.pbr ?? null) },
    { label: '주가/주당현금', value: ratioText(s.pc) },
    { label: '주가/FCF', value: ratioText(s.p_fcf) },
    { label: 'EV/EBITDA', value: ratioText(s.ev_ebitda) },
    { label: 'EV/매출', value: ratioText(s.ev_sales) },
    // 배수임을 값에도 남긴다 — 0.46에 단위가 없으면 46%로도 0.46%로도 읽힌다
    { label: '당좌비율', value: mult(s.quick_ratio),
      title: '유동자산(재고 제외) ÷ 유동부채 — 배수. 국내 종목은 국내 공시 기준(네이버)' },
    { label: '유동비율', value: mult(s.current_ratio),
      title: '유동자산 ÷ 유동부채 — 배수. yfinance 기준(국내 종목도 동일)' },
    { label: '부채비율', value: mult(s.debt_eq), title: '총부채 ÷ 자기자본 — 배수(0.46 = 46%)' },
    { label: '장기부채비율', value: mult(s.lt_debt_eq), title: '장기부채 ÷ 자기자본 — 배수' },
    { label: '유통주식 비율', value: levelPct(s.float_pct) },
  ]

  const col3: SnapCell[] = [
    { label: 'EPS(TTM)', value: money(s.eps_ttm) },
    { label: 'EPS 추정(내년)', value: money(s.eps_next_y) },
    { label: 'EPS 추정(다음분기)', value: money(s.eps_next_q) },
    pctCell('EPS 성장(올해)', s.eps_this_y_pct ?? null),
    pctCell('EPS 성장(내년)', s.eps_next_y_pct ?? null),
    pctCell('EPS 성장(5년 추정)', s.eps_next_5y_pct ?? null),
    pctCell('EPS 성장(3년)', s.eps_past_3y_pct ?? null),
    pctCell('매출 성장(3년)', s.sales_past_3y_pct ?? null),
    // 필드명은 ttm이지만 소스가 5~6분기만 줘서 실제로는 분기 대 분기다 — 라벨이 정직해야 한다
    pctCell('EPS 전년동기(분기)', s.eps_yoy_ttm_pct ?? null, YOY_NOTE),
    pctCell('매출 전년동기(분기)', s.sales_yoy_ttm_pct ?? null, YOY_NOTE),
    pctCell('EPS 전분기', s.eps_qoq_pct ?? null),
    pctCell('매출 전분기', s.sales_qoq_pct ?? null),
    { label: '실적발표일', value: dateText(s.earnings_date), sub: s.earnings_timing ?? null },
    // 매출 서프라이즈는 소스가 영구히 주지 않는다 — 절반이 늘 —인 두 값 칸은 형식만 흉내 낸 빈 칸이다
    pctCell('EPS 서프라이즈', s.eps_surprise_pct ?? null),
  ]

  // KR은 기관 변동 대신 외국인 지분이 온다. 라벨이 시장별로 다르므로 값 있는 쪽을 쓴다 —
  // 없는 값을 남의 라벨로 채우면 화면이 다른 지표를 같은 이름으로 부르게 된다.
  const instTrans: SnapCell = s.foreign_own_pct != null
    ? { label: '외국인 지분', value: levelPct(s.foreign_own_pct) }
    : { ...pctCell('기관 거래', s.inst_trans_pct ?? null) }

  const col4: SnapCell[] = [
    { label: '내부자 지분', value: levelPct(s.insider_own_pct) },
    pctCell('내부자 거래(6M)', s.insider_trans_pct ?? null),
    { label: '기관 지분', value: levelPct(s.inst_own_pct) },
    instTrans,
    { label: 'ROA', value: levelPct(s.roa_pct) },
    { label: 'ROE', value: levelPct(s.roe_pct) },
    { label: 'ROIC', value: levelPct(s.roic_pct) },
    { label: '매출총이익률', value: levelPct(s.gross_margin_pct) },
    { label: '영업이익률', value: levelPct(s.oper_margin_pct) },
    { label: '순이익률', value: levelPct(s.profit_margin_pct) },
    pctCell('SMA20 이격', last ? smaGapPct(last.close, last.sma20) : null),
    pctCell('SMA60 이격', last ? smaGapPct(last.close, last.sma60) : null),
    pctCell('SMA120 이격', last ? smaGapPct(last.close, last.sma120) : null),
    { label: '거래대금(20일)', value: abbr(avgTurnover(c, 20)),
      title: '최근 20봉 (종가 × 거래량) 평균' },
  ]

  const col5: SnapCell[] = [
    { label: '발행주식수', value: abbr(s.shares_outstanding) },
    { label: '유통주식수', value: abbr(s.shares_float) },
    { label: '공매도 비율', value: levelPct(s.short_float_pct) },
    { label: '공매도 상환일수', value: ratioText(s.short_ratio) },
    { label: '공매도 잔고', value: abbr(s.short_interest) },
    { label: '52주 고가', value: r52 ? money(r52.high) : DASH,
      sub: r52 ? pctText(r52.highPct) : null },
    { label: '52주 저가', value: r52 ? money(r52.low) : DASH,
      sub: r52 ? pctText(r52.lowPct) : null },
    { label: '변동성(주/월)', value: levelPct(volatility(c, 5)), sub: levelPct(volatility(c, 21)),
      title: '일간 수익률 표준편차 — 5봉 / 21봉' },
    { label: 'ATR (14)', value: risk ? money(risk.atr) : DASH,
      sub: risk ? `${risk.atr_pct}%` : null },
    { label: 'RSI (14)', value: ratioText(last?.rsi, 1),
      tone: last?.rsi != null && (last.rsi >= 70 || last.rsi <= 30) ? 'warn' : null },
    { label: '베타', value: ratioText(s.beta) },
    { label: '상대 거래량', value: ratioText(relVolume(c, 20)),
      tone: (relVolume(c, 20) ?? 0) >= 1.5 ? 'warn' : null, title: '오늘 거래량 ÷ 직전 20일 평균' },
    { label: '평균 거래량(20)', value: abbr(avgVolume(c, 20)) },
    { label: '거래량', value: intText(last?.volume) },
  ]

  const col6: SnapCell[] = [
    perfCell('1주', perf?.w1, perfPct(c, 5)),
    perfCell('1개월', perf?.m1, perfPct(c, 21)),
    perfCell('3개월', perf?.m3, perfPct(c, 63)),
    perfCell('6개월', perf?.m6, perfPct(c, 126)),
    perfCell('연초 대비', perf?.ytd, perfYtdPct(c, new Date(now).getFullYear())),
    perfCell('1년', perf?.y1, perfPct(c, 252)),
    perfCell('3년', perf?.y3),
    perfCell('5년', perf?.y5),
    perfCell('10년', perf?.y10),
    { label: '컨센서스 의견', value: ratioText(s.recommendation_mean),
      title: s.recommendation_scale ?? '1=강력매수 … 5=강력매도' },
    { label: '목표주가', value: money(s.target_price),
      sub: s.target_price != null && last ? pctText((s.target_price / last.close - 1) * 100) : null },
    { label: '전일 종가', value: money(change?.prev) },
    { label: '현재가', value: money(last?.close) },
    { ...pctCell('등락률', change?.pct ?? null) },
  ]

  // 행 우선으로 엮는다 — 표가 6열 격자라 여기서 뒤섞으면 열의 주제가 흩어진다
  const cols = [col1, col2, col3, col4, col5, col6]
  const out: SnapCell[] = []
  for (let row = 0; row < 14; row++) for (const col of cols) out.push(col[row])
  return out
}
