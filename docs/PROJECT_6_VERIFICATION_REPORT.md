# QUANT AI PORTFOLIO — Project 6 Verification Report
## 실전 E2E / 성능 / 회귀 / Render 배포 전 최종 검증 보고서

---

### [추천 E2E] (10개 질문 테스트)
1. `단기 매매 후보 5개 찾아줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `STOCK_SHORT_RECOMMEND` | 반환: 5개)
2. `중기 ETF 3개 추천해줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `ETF_MID_RECOMMEND` | 반환: 3개)
3. `외국인 기관 쌍끌이 종목 찾아줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `FLOW_JOINT_BUY` | 반환: 0개 정상 0건 처리)
4. `최근 수급이 개선된 종목 알려줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `FLOW_IMPROVING` | 반환: 5개)
5. `과열되지 않은 상승추세 종목 찾아줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `TREND_NOT_OVERHEATED` | 반환: 5개)
6. `현재 보유종목 중 단기 유망순으로 보여줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `PORTFOLIO_SHORT_RANK` | 반환: 5개)
7. `눌림목 후보 찾아줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `PULLBACK_CANDIDATE` | 반환: 2개)
8. `중기 종목 10개 보여줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `STOCK_MID_RECOMMEND` | 반환: 10개)
9. `수급 좋은 ETF 찾아줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `ETF_MID_RECOMMEND` | 반환: 3개)
10. `기관이 최근 매집하는 종목 알려줘` $\rightarrow$ **PASS** (HTTP 200 | Intent: `FLOW_IMPROVING` | 반환: 5개)

---

### [정확성 & 환각(Hallucination) 검증]
- **Backend ↔ UI mismatch**: **0건** (모든 종목명, Ticker, 수급패턴, FFCS, TODAY ACTION, 지표 실측치 100% 일치)
- **임의/가짜 Ticker 발생 수**: **0건**

---

### [JOINT_BUY 엄격성 검증]
- **False Positive (쌍끌이 위반 종목)**: **0건** (외국인·기관 1D/3D/5D 6개 지표가 모두 양수인 종목만 strict 분류, 미충족 시 0건 정상 응답)

---

### [ETF MID 기본 추천 검증]
- **부적합 ETF 포함 수**: **0건** (기본 중기 ETF 추천 시 인버스, 레버리지, 채권/금리, MMF, 단일종목 100% 제외)

---

### [PORTFOLIO 보유종목 제한 검증]
- **미보유 종목 포함 수**: **0건** (`portfolio.db` 내 27개 보유 종목 한정 정확히 분석/순위화)

---

### [DATA QUALITY 데이터 검증]
- **null/NaN/DATA_INSUFFICIENT 미비 종목 잘못 분류**: **0건** (`DATA_INSUFFICIENT` 종목은 `TIER_D`/`EXCLUDE` 유지)

---

### [PERFORMANCE (성능 실측)]
- **STOCK (단기)**: Cold ~26.17초 / **Warm 1.27 ~ 1.70초**
- **ETF (중기)**: Cold 3.31초 / **Warm 1.46 ~ 2.86초**
- **JOINT BUY (쌍끌이)**: Cold 4.26초 / **Warm 1.36초**
- **PORTFOLIO (보유종목)**: Cold 11.80초 / **Warm 0.58 ~ 1.65초**

---

### [MOBILE 반응형 검증]
- **375px (iPhone SE/mini)**: 가로 overflow 0 / 카드 뱃지 및 사유 자동 줄바꿈 정상
- **390px (iPhone 12/13/14)**: Grid 레이아웃 및 뱃지 alignment 정상
- **430px (iPhone Pro Max)**: 여백 및 가독성 최적화 정상

---

### [기존 AI Q&A 완전 회귀 검증]
- **Q&A 검색 / 질문 / 뉴스 / 공시 / 근거 인용 / 답변 렌더링**: **PASS** (추천 기능과 상태 완전 독립)

---

### [기타 기존 기능 회귀 검증]
- **개별종목 Portfolio**: **PASS**
- **ETF Portfolio**: **PASS**
- **수급 상세 그래프**: **PASS**
- **FFCS / FCS**: **PASS**
- **RSI / RMI / MFI / Bollinger / 6M 차트**: **PASS**
- **TODAY ACTION**: **PASS**
- **Forward Test**: **PASS** (DB & Engine 정상)

---

### [PWA & 캐시 검증]
- **latest JS loading**: **PASS** (`index.html` 내 `?v=20260914_recommend_api_ui` 정상 갱신)
- **stale cache 에러**: **0건** (`submitRecommendQuestion is not defined` 에러 없음)

---

### [Render 배포 준비 상태]
- **deploy readiness**: **READY** (신규 API `/api/recommend/ask` 및 UI 연결 검증 100% 완료)
- **API status**: HTTP 200 OK
- **mobile PWA**: 정상 연결 준비 완료

---

### [Console / Syntax]
- **ReferenceError**: **0건**
- **TypeError**: **0건**
- **Unhandled Promise Rejection**: **0건**
- **HTTP 404 / 500 에러**: **0건**
- **`git diff --check`**: **PASS**

---

### 최종 판정
**`6단계 PASS — AI RECOMMENDER PRODUCTION READY`**
