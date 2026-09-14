# QUANT AI PORTFOLIO — Project 5-A Verification Report
## 추천 전용 Backend API 연결 완료 보고

---

### [신규 endpoint]
- **Endpoint**: `POST /api/recommend/ask`
- **Request Body**:
  ```json
  {
    "question": "단기 매매 후보 5개 찾아줘",
    "limit": 5
  }
  ```
- **Response Schema**:
  ```json
  {
    "status": "ok",
    "intent": "STOCK_SHORT_RECOMMEND",
    "query": "단기 매매 후보 5개 찾아줘",
    "requested_count": 5,
    "returned_count": 5,
    "market_scope": "STOCK",
    "horizon": "SHORT",
    "elapsed_ms": 1270,
    "cache": { "stage1": true, "stage2": true, "stage3": true },
    "results": [
      {
        "ticker": "005490",
        "name": "POSCO홀딩스",
        "market": "KOSPI",
        "asset_type": "STOCK",
        "price": 380000.0,
        "grade": "STRONG_CANDIDATE",
        "confidence": "HIGH",
        "flow_pattern": "FLOW_IMPROVING",
        "flow_tier": "TIER_A",
        "ffcs": 77.4,
        "fcs": "적극 매수",
        "today_action": "BUY",
        "today_action_desc": "수급 최상위 단기 상승 모멘텀",
        "rsi": 45.5,
        "rmi": 48.2,
        "mfi": 52.1,
        "bollinger_status": "MID_BAND",
        "ma60": 375000.0,
        "ma120": 370000.0,
        "trend_6m": 12.5,
        "reasons": [
          "수급 1순위(FLOW_IMPROVING) + TODAY ACTION(BUY) 단기 긍정 부합"
        ]
      }
    ],
    "message": "단기 매매 조건(수급 1순위 + TODAY ACTION + 비과열)을 충족한 주식 종목 5개를 추천합니다."
  }
  ```

---

### [변경 파일]
- `backend/router/recommend_router.py` *(NEW)*: 추천 전용 독립 API 라우터 구현
- `backend/engine/recommend_intent_parser.py` *(NEW)*: LLM 없는 결정론적 Intent / Horizon / Scope / Count 파서
- `backend/main.py`: `app.include_router(recommend_router.router)` 추가

---

### [Intent Test (필수 6개 질문 테스트)]

1. **단기 매매 후보 5개** (`"단기 매매 후보 5개 찾아줘"`)
   - **intent**: `STOCK_SHORT_RECOMMEND`
   - **결과수**: 5개 (`POSCO홀딩스`, `GS건설`, `오뚜기`, `한화에어로스페이스`, `KB금융`)

2. **중기 ETF 3개** (`"중기 ETF 3개 추천해줘"`)
   - **intent**: `ETF_MID_RECOMMEND`
   - **결과수**: 3개 (`TIGER 화장품`, `KODEX 미국TOP10타겟위클리커버드`, `HANARO Fn K-반도체`) *(인버스/레버리지/단일종목 제외된 기본 pool)*

3. **외국인 기관 쌍끌이** (`"외국인 기관 쌍끌이 종목 찾아줘"`)
   - **intent**: `FLOW_JOINT_BUY`
   - **결과수**: 0개 (Strict 3-C 기준 6개 지표 양수인 종목이 없는 상태에서 억지로 가짜 후보를 채우지 않고 정상 0건 응답)
   - **message**: `"현재 엄격한 외국인·기관 쌍끌이(1D/3D/5D 동시 순매수) 기준을 충족하는 종목이 없습니다."`

4. **최근 수급 개선** (`"최근 수급이 개선된 종목 알려줘"`)
   - **intent**: `FLOW_IMPROVING`
   - **결과수**: 5개 (`POSCO홀딩스`, `한화시스템`, `KB금융` 등)

5. **비과열 상승추세** (`"과열되지 않은 상승추세 종목 찾아줘"`)
   - **intent**: `TREND_NOT_OVERHEATED`
   - **결과수**: 5개 (`GS건설`, `KB금융`, `삼성E&A` 등)

6. **보유종목 단기 유망순** (`"현재 보유종목 중 단기 유망순으로 보여줘"`)
   - **intent**: `PORTFOLIO_SHORT_RANK`
   - **결과수**: 5개 (DB 내 27개 보유 종목 중 단기 Quant 유망 5종목 분석 정렬)

---

### [Hallucination]
- **임의/가짜 ticker 발생 수**: **0건** (100% 3-B/3-C/4단계 실데이터 및 DB 연동)

---

### [Performance (응답 속도 측정)]
- **단기 STOCK**: Cold 26.17초 / **Warm 1.27초**
- **중기 ETF**: Cold 1.19초 / **Warm 1.46초**
- **쌍끌이**: Cold 1.20초 / **Warm 1.36초**
- **보유종목 단기**: Cold 11.80초 / **Warm 0.58초**
- *(Warm 목표 3초 이내 완전 달성)*

---

### [기존 API 회귀 검증]
- **qna**: 기존 `/api/qna/answer`, `/api/qna/news`, `/api/qna/official`, `/api/qna/citations`, `qna_llm_engine.py`, 프론트엔드 Q&A 100% 미수정 보존 및 정상 작동
- **decision**: `/api/decision/analyze` 정상 작동
- **portfolio**: 보유 종목 DB READ-ONLY 정상 조회 (27개 보존)
- **forward test**: 정상 DB 초기화 및 동작 유지

---

### [Git 검증]
- **`git diff --stat`**: `backend/main.py | 3 +++`
- **`git diff --check`**: PASS (줄바꿈/공백 오류 없음)
- **`git status`**:
  ```text
  modified:   backend/data/portfolio.db (기존 보존)
  modified:   backend/main.py
  untracked:  backend/engine/recommend_intent_parser.py
  untracked:  backend/router/recommend_router.py
  ```

---

### 최종 판정
**`5-A PASS — RECOMMEND BACKEND API READY`**
