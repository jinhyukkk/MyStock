# KR 종목 finviz형 데이터 소스 조사 결과 (2026-08-21 실측, 000660 기준)

## 1. Naver 증권 모바일 JSON (`m.stock.naver.com/api/...`) — 비공식, 키 불필요
- 커버: ①스냅샷 일부, ②재무이력, ④뉴스, ⑤리포트 목록·컨센서스 평균
- 접근: `User-Agent`만 넣으면 200. 로그인·토큰·Referer 없음. 공식 문서 없음(변경 예고 없음). 짧은 캐시·순차 호출이면 차단 사례 거의 없음.
- 실측 엔드포인트
  - `GET /api/stock/{code}/integration` → `totalInfos[]`(per, eps, cnsPer/cnsEps(forward), pbr, bps, dividend, dividendYieldRatio, foreignRate, marketValue, 52주), `consensusInfo{recommMean, priceTargetMean, createDate}`, `researches[]`(최근 리포트 5건: 증권사·제목·일자), `industryCompareInfo[]`, `dealTrendInfos[]`(외인/기관 순매수·외인보유율). `description`/`irScheduleInfo`는 null.
  - `GET /api/stock/{code}/finance/annual` / `finance/quarter` → 매출·영업이익·순이익·영업이익률·ROE·부채비율·당좌비율·EPS·PER·BPS·PBR·DPS. **연간 3개+컨센서스 1개, 분기 5개+컨센서스 1개만**.
  - `GET /api/news/stock/{code}?pageSize=20&page=1` → `officeName, datetime, title, mobileNewsUrl`.
  - `GET /api/research/stock/{code}?pageSize=20&page=1` → `brokerName, title, writeDate, researchId`; `GET /api/research/company/{researchId}` → 본문 HTML + PDF. **투자의견·목표가 필드 없음**(본문 정규식 추출 가능).
  - `GET /api/stock/{code}/trend?pageSize=20` → 일별 외인·기관·개인 순매수, 외인보유율.
- `api.stock.naver.com`은 409, `/consensus|corporation`은 404. PC `finance.naver.com` 뉴스는 iframe이라 curl 불가 → 모바일 JSON 사용.

## 2. Naver PC ↔ WiseReport (`navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}`) — HTML
- 커버: ③한국어 기업개요(`.cmp_comment`), 종업원수·상장일 등. 200 OK, 키 불필요. 컨센서스 탭은 `encparam` ajax라 fragile.

## 3. Daum 금융 (`finance.daum.net/api/quotes/A{code}?summary=false&changeStatistics=true`) — 비공식 JSON
- 커버: ①(eps/bps/dps/per/pbr, marketCap, foreignRatio, foreignOwnShares, 52주), ③**`companySummary`(한국어 개요)**, `wicsSectorName`, `sectorPer`.
- `Referer: https://finance.daum.net/quotes/A{code}` 필수. 뉴스·재무·프로필 하위 API는 전부 500 → 이 엔드포인트만 신뢰.

## 4. OpenDART (`opendart.fss.or.kr/api/*.json`) — 공식, 무료 키
- 커버: ②재무이력(XBRL, 2015~), ⑥임원·주요주주 소유보고(내부자), 직원수·주식총수·배당.
- 키 즉시 발급, 일 20,000건. `corp_code`(8자리)↔종목코드는 `corpCode.xml` 1회 다운로드.
  - `fnlttSinglAcnt.json?corp_code&bsns_year&reprt_code=11011|11012|11013|11014`(연/분기 주요계정) / `fnlttSinglAcntAll.json`
  - `elestock.json?corp_code` → 보고자·직위·보유수·증감·비율·접수일 = 내부자 거래
  - `empSttus.json`(직원수), `stockTotqySttus.json`(발행주식수 이력), `alotMatter.json`(배당)
- 파이썬: `OpenDartReader(api_key).finstate('000660', 2025, reprt_code='11011')`, `.report('000660','임원',2025)`. 정기보고서 기준(실시간 아님). EPS 직접 없음 → 순이익/주식수 계산.

## 5. KRX / pykrx
- **2025-12-27부터 KRX Data Marketplace 로그인 필수**. pykrx 1.2.8이 `KRX_ID`/`KRX_PW`로 대응. 과다 호출 차단 전력.
- 커버: PER/PBR/EPS/BPS/DIV, 상장주식수·시총, 외국인 보유, **공매도 잔고**(T+2), 투자자별 거래.
- FDR `fdr.StockListing('KRX-DESC')` → `Sector, Industry, ListingDate(IPO일), Representative, HomePage` — 로그인 없이 동작 확인.

## 6. FnGuide — 기존 URL 전부 오류 페이지, 신버전은 세션 필요. **제외.**

## 7. yfinance `000660.KS` (v1.5.2)
- `info` 163키: forwardPE, PEG, P/S, ROA/ROE, 마진 3종, D/E, quick/current, sharesOutstanding, floatShares, heldPercentInstitutions/Insiders, beta, dividendYield, payoutRatio, fullTimeEmployees, targetMeanPrice, recommendationKey, numberOfAnalystOpinions, sector/industry(영문), longBusinessSummary(영문).
- **None**: trailingPE, priceToBook, trailingEps, forwardEps, shortRatio, shortPercentOfFloat(종목마다 들쭉날쭉).
- `income_stmt` 4년, `quarterly_income_stmt` 6분기, `balance_sheet` 5년. `calendar` 다음 실적일+추정, `analyst_price_targets`, `recommendations`(집계), `earnings_dates`, `eps_trend`, `growth_estimates`.
- 빈값: `upgrades_downgrades`, `insider_transactions`. `news` 10건(영문).

## 8. 기타
- KIS Open API: 계좌+AppKey 필요. `invest_opbysec`(증권사별 의견·목표가 이력) — 사실상 유일한 무료 구조화 소스.
- 네이버 뉴스 검색 API: 불필요(모바일 JSON이 더 정확).

## 추천 표
| 항목 | 1순위 | 폴백 | 미제공/주의 |
|---|---|---|---|
| ① 스냅샷 지표 | yfinance `info` + Naver integration(PER/EPS/PBR/추정EPS/외인소진율 보정) | Daum quotes, pykrx | 공매도: pykrx만(T+2). ROIC·EPS past 5Y는 DART 계산. IPO일: FDR KRX-DESC |
| ② 연/분기 재무 | OpenDART `fnlttSinglAcnt`(7년) + `stockTotqySttus` | Naver finance(3년/5분기+컨센서스), yfinance(4년/6분기) | DART EPS 없음 → 계산 |
| ③ 기업개요·업종(한국어) | Daum `companySummary` + `wicsSectorName` | WiseReport `.cmp_comment`, FDR KRX-DESC | yfinance 영문만 |
| ④ 뉴스 | Naver `/api/news/stock/{code}` | yfinance news(영문) | |
| ⑤ 애널리스트 | Naver `consensusInfo` + yfinance `analyst_price_targets`/`recommendations` + Naver 리포트 목록 | KIS(계좌) | **브로커별 등급 변경 이력은 무키 소스 없음** |
| ⑥ 내부자 | OpenDART `elestock` | — | yfinance 빈값 |
| 다음 실적일 | yfinance `calendar` | | |

**구현 제안**: 키 없는 1차(Naver 모바일 JSON + Daum + yfinance + FDR KRX-DESC)로 채우고, 무료 키 1개(OpenDART)로 재무 이력·내부자 보강. pykrx/KIS는 보류. FnGuide 폐기.
