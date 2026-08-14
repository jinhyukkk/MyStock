# MyStock

종목별 매수/매도 시그널을 한눈에 보는 개인용 투자관리 웹앱.

## 실행

```bash
./run.sh
```

브라우저에서 http://mystock.localhost 접속.

`*.localhost` 는 브라우저가 127.0.0.1로 자동 해석하므로 hosts 파일 수정이 필요 없다.
포트 80이 이미 쓰이고 있으면 `PORT=8000 ./run.sh` 처럼 덮어쓴다 (주소는 http://mystock.localhost:8000).
도메인 이름을 바꾸려면 `HOST_NAME=trade.localhost ./run.sh`.

## 기능

- 한국/미국 주식, 암호화폐, ETF 통합 워치리스트
- 스윙/중장기 이중 시그널 (기술적 지표 종합 점수 + 한국어 근거)
- 추세 국면(정배열/역배열) 감지 — 추세에 역행하는 평균회귀 신호는 반감
- 시그널 백테스트 — 현재 스코어링을 과거 400일에 적용한 등급별 수익률·승률 검증
- ATR 기반 리스크 관리 — 제안 손절가(2×ATR), 계좌 1% 리스크 포지션 사이징, 종목 MDD
- 실현손익 원장 — 승률·평균 손익비 등 매매 복기 지표
- VIX·공포탐욕지수 시장 심리 게이지 (참고 표기, 점수 미왜곡)
  - VKOSPI는 [KRX 오픈API](https://openapi.krx.co.kr) 무료 키 발급 후 `.env`에 `KRX_API_KEY` 설정 시 표시 (미설정이면 생략, `.env.example` 참고)
- 보유 종목 수익률·자산 배분 (매매 내역 직접 입력)
- 종목별 목표가/손절가/평단 대비 % 커스텀 룰 알림
- 1시간 주기 자동 갱신 + 수동 새로고침

> 본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다.

## 개발

```bash
cd backend && .venv/bin/pytest          # 백엔드 테스트 (Windows: .venv/Scripts/pytest)
cd backend && .venv/bin/pytest -m smoke # 외부 API 스모크 테스트
cd frontend && npm run dev              # 프론트 개발 서버 (proxy → 백엔드 :80)
```
