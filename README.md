# Global Liquidity Monitor

자동 업데이트되는 글로벌 유동성 스트레스 대시보드.

## 데이터
- US 10Y: FRED DGS10
- TGA: FRED WTREGEN
- ON RRP: FRED RRPONTSYD
- SOFR: FRED SOFR
- Fed Reserve Balances: FRED WRESBAL
- DXY: Yahoo Finance DX-Y.NYB
- BTC: Yahoo Finance BTC-USD
- Stablecoin market cap: DefiLlama stablecoin API

## 자동 업데이트
GitHub Actions가 매시간 20분에 `update_liquidity.py`를 실행합니다.
`data/latest.json`이 자동 갱신되고 GitHub Pages의 `index.html`이 그 값을 읽습니다.
브라우저 페이지 자체도 15분마다 재조회됩니다.

## 설치
1. 이 폴더 전체를 새 GitHub repository에 업로드
2. GitHub > Settings > Pages
3. Deploy from a branch 선택
4. Branch: main / root 선택
5. Actions 탭에서 "Update liquidity monitor"를 한 번 수동 실행
6. 이후에는 매시간 자동 업데이트

## 주의
GitHub Actions의 cron 실행은 정확히 해당 분에 시작되지 않고 몇 분 지연될 수 있습니다.
공식 데이터 자체의 발표주기보다 더 자주 실행해도 원자료가 갱신되지 않은 경우 값은 그대로입니다.

## 점수
0 = 매우 완화적 / Risk-on
100 = 매우 긴축적 / Risk-off

현재 버전은 최근 2년 rolling percentile을 기본으로 사용합니다.
RRP는 `Flow`와 `Buffer`를 분리해서 계산합니다.
