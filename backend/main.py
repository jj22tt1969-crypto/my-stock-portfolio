import os
import sys

# 프로젝트 루트 경로를 파이썬 모듈 검색 경로(sys.path)에 최우선 추가
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
from functools import partial

from backend.data.collector import get_stock_flow_data, resolve_ticker, fetch_stock_chart_analysis
from backend.data.market_collector import fetch_market_indices, fetch_stock_news, fetch_market_index_history
from backend.engine.flow_engine import analyze_stock_flow
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.smart_flow_engine import analyze_smart_money_flow
from backend.engine.cross_validation_engine import analyze_cross_indicators
from backend.engine.stock_identifier import search_stock_or_etf, search_all_stock_or_etf
from backend.engine.news_engine import fetch_qna_stock_news
from backend.engine.official_engine import fetch_official_documents
from backend.engine.citation_engine import generate_citations
from backend.engine.qna_llm_engine import generate_grounded_qna_answer
from backend.engine.calendar_engine import fetch_upcoming_events
from backend.engine import portfolio_engine as pe
from backend.db import database as db
import uvicorn

app = FastAPI(
    title="AI Stock Decision Support & Live Dashboard API",
    description="외국인/기관 수급 사이클, 기술적 지표, Buy/Sell/Watering Score 및 종합 판단 대시보드 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_warmup_cache():
    """
    서버 가동 시 KRX 전종목 캐시를 미리 사전 워밍업(Warm-up)하여
    사용자가 최초 접속했을 때 화면 출력이 0.001초 만에 즉시 이뤄지도록 보장합니다.
    """
    loop = asyncio.get_event_loop()
    try:
        from backend.engine.krx_loader import load_krx_all_stocks
        loop.run_in_executor(None, load_krx_all_stocks)
    except Exception:
        pass


class AddStockRequest(BaseModel):
    ticker_or_name: str = Field(..., description="종목명 또는 종목코드")
    avg_price: float = Field(..., gt=0, description="평균매수가")
    quantity: int = Field(..., gt=0, description="보유수량")
    buy_date: Optional[str] = Field("", description="매수일")
    investment_purpose: Optional[str] = Field("장기투자", description="투자목적")
    sector: Optional[str] = Field("기타", description="업종")
    asset_type: Optional[str] = Field("STOCK", description="자산분류 ('STOCK': 개별주식, 'ETF': ETF)")
    market: Optional[str] = Field("KOSPI", description="시장구분 ('KOSPI', 'KOSDAQ', 'ETF')")

class UpdateStockRequest(BaseModel):
    avg_price: float = Field(..., gt=0, description="평균매수가")
    quantity: int = Field(..., gt=0, description="보유수량")
    buy_date: Optional[str] = Field("", description="매수일")
    investment_purpose: Optional[str] = Field("장기투자", description="투자목적")
    sector: Optional[str] = Field("기타", description="업종")
    market: Optional[str] = Field("KOSPI", description="시장구분 ('KOSPI', 'KOSDAQ', 'ETF')")

class SimulateAddBuyRequest(BaseModel):
    item_id: Optional[int] = Field(None, description="등록된 포트폴리오 종목 ID")
    ticker_or_name: Optional[str] = Field(None, description="종목명 또는 종목코드")
    add_price: float = Field(..., gt=0, description="추가매수가")
    add_quantity: Optional[int] = Field(0, description="추가수량")
    add_amount: Optional[float] = Field(0.0, description="추가투자금액")

# API Endpoints

# 1. 시장 지수 및 환율
@app.get("/api/market/overview")
def get_market_overview():
    return fetch_market_indices()

# 1-2. 최근 6개월 지수/환율 이력 차트 API
@app.get("/api/market/index-history")
def get_market_index_history(symbol: str = Query("KOSPI", description="지수/환율 기호 (KOSPI, KOSDAQ, USDKRW, SP500, NASDAQ)")):
    res = fetch_market_index_history(symbol, count=180)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return {
        "status": "success",
        "symbol": symbol,
        "data": res
    }


# 1-2b. 향후 7일간 주요 경제 이벤트 캘린더 (물가, 금리, 고용, 빅테크 실적)
@app.get("/api/calendar/upcoming")
async def get_upcoming_calendar(days: int = Query(7, description="조회할 앞으로의 일수 (기본 7일)")):
    """
    향후 N일간 주요 경제 지표 발표 및 빅테크 실적 일정을 반환합니다.
    - 미국 CPI, FOMC, 고용, 실업률
    - 한국 기준금리, 소비자물가
    - 빅테크(NVIDIA/Apple/MS 등) 및 국내 대형주 실적발표
    """
    import asyncio
    from functools import partial
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(fetch_upcoming_events, days))
    return result

# 1-3. 개별 종목 6개월 시세, 추세선(이동평균), 거래량, MFI 지표 분석 API
@app.get("/api/stock/history-analysis")
def get_stock_history_analysis(
    ticker: str = Query(..., description="종목명 또는 종목코드"),
    timeframe: str = Query("day", description="주기 ('day': 일간, 'month': 월간, 'year': 연간)")
):
    res = fetch_stock_chart_analysis(ticker, timeframe=timeframe)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res

# 2. 종목 뉴스
@app.get("/api/market/news")
def get_stock_news(ticker: str = Query(..., description="종목명 또는 종목코드")):
    ticker_code, name = resolve_ticker(ticker)
    if not ticker_code:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")
    return fetch_stock_news(ticker_code, name, count=5)

# 3. 파이프라인 자동 테스트
@app.get("/api/market/pipeline-test")
def test_market_pipeline(ticker: str = Query("005930", description="종목코드 또는 종목명")):
    ticker_code, name = resolve_ticker(ticker)
    if not ticker_code:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")

    flow_data = get_stock_flow_data(ticker_code, min_days=30)
    if not flow_data.get("data_available", False):
        return {
            "status": "error",
            "status_code": flow_data.get("status_code", "DATA_NOT_FOUND"),
            "status_message": flow_data.get("status_message", "데이터 없음"),
            "message": flow_data.get("error")
        }

    df = flow_data["df"]
    decision_data = analyze_stock_decision(df)
    news_data = fetch_stock_news(ticker_code, name, count=3)

    return {
        "status": "success",
        "ticker": ticker_code,
        "name": name,
        "metadata": {
            "updated_at": flow_data["updated_at"],
            "source": flow_data["source"],
            "is_delayed": flow_data["is_delayed"]
        },
        "pipeline_result": decision_data,
        "news": news_data.get("news", [])
    }

# 4. 수급 사이클 분석 API
@app.get("/api/flow/analyze")
def analyze_flow(ticker: str = Query(..., description="종목명 또는 6자리 종목코드")):
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="종목명 또는 종목코드를 입력해주세요.")

    flow_data = get_stock_flow_data(ticker.strip(), min_days=30)
    if not flow_data.get("data_available", False):
        return {
            "status": "error",
            "status_code": flow_data.get("status_code", "DATA_NOT_FOUND"),
            "status_message": flow_data.get("status_message", "데이터 없음"),
            "message": flow_data.get("error", "데이터 없음")
        }

    df = flow_data["df"]
    analysis_result = analyze_stock_flow(df)
    
    m_info = search_stock_or_etf(flow_data["ticker"])
    asset_type = m_info[0].get("asset_type", "STOCK") if m_info else "STOCK"
    smart_flow = analyze_smart_money_flow(flow_data.get("investor_breakdown"), df, asset_type=asset_type)

    return {
        "status": "success",
        "data_available": True,
        "ticker": flow_data["ticker"],
        "name": flow_data["name"],
        "metadata": {
            "updated_at": flow_data["updated_at"],
            "source": flow_data["source"],
            "is_delayed": flow_data["is_delayed"]
        },
        "analysis": analysis_result,
        "investor_breakdown": flow_data.get("investor_breakdown"),
        "smart_flow_analysis": smart_flow
    }

# 5. 기술적 지표 + 수급 + 의사결정 API
@app.get("/api/decision/analyze")
def analyze_decision(
    ticker: str = Query(..., description="종목명 또는 종목코드"),
    return_rate: float = Query(0.0, description="현재 수익률 (%)")
):
    ticker_code, name = resolve_ticker(ticker)
    if not ticker_code:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")

    flow_data = get_stock_flow_data(ticker_code, min_days=30)
    if not flow_data.get("data_available", False):
        return {
            "status": "error",
            "status_code": flow_data.get("status_code", "DATA_NOT_FOUND"),
            "status_message": flow_data.get("status_message", "데이터 없음"),
            "message": flow_data.get("error", "데이터 없음")
        }

    df = flow_data["df"]
    res = analyze_stock_decision(df, return_rate=return_rate)

    m_info = search_stock_or_etf(ticker_code)
    asset_type = m_info[0].get("asset_type", "STOCK") if m_info else "STOCK"
    smart_flow = analyze_smart_money_flow(flow_data.get("investor_breakdown"), df, asset_type=asset_type)

    cross_res = analyze_cross_indicators(
        flow_analysis=res.get("flow_analysis"),
        technical_analysis=res.get("technical_analysis"),
        smart_flow_analysis=smart_flow,
        decision_analysis=res.get("decision")
    )

    full_analysis_data = {
        "decision": res.get("decision"),
        "flow_analysis": res.get("flow_analysis"),
        "technical_analysis": res.get("technical_analysis"),
        "timing_analysis": res.get("timing_analysis"),
        "smart_flow_analysis": smart_flow,
        "cross_analysis": cross_res
    }

    try:
        from backend.engine.forward_test_engine import record_signal_snapshot
        latest_c = res.get("technical_analysis", {}).get("latest_close", 0.0)
        record_signal_snapshot(
            ticker=ticker_code,
            name=name,
            asset_type=asset_type,
            price=latest_c,
            analysis_data=full_analysis_data
        )
    except Exception as e:
        pass

    return {
        "status": "success",
        "ticker": ticker_code,
        "name": name,
        "metadata": {
            "updated_at": flow_data["updated_at"],
            "source": flow_data["source"],
            "is_delayed": flow_data["is_delayed"]
        },
        "data": res,
        "investor_breakdown": flow_data.get("investor_breakdown"),
        "smart_flow_analysis": smart_flow,
        "cross_analysis": cross_res
    }

# 6. 포트폴리오 조회 API (asset_type: 'STOCK' 또는 'ETF')
@app.get("/api/portfolio")
def get_portfolio(asset_type: str = Query("STOCK", description="자산분류 ('STOCK': 개별주식, 'ETF': ETF)")):
    try:
        data = pe.analyze_portfolio(asset_type=asset_type)
        return {
            "status": "success",
            "asset_type": asset_type.upper(),
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 6-1. 15초 자동 타이머 전용 초경량 시세 조회 API
@app.get("/api/portfolio/live-prices")
def get_portfolio_live_prices(asset_type: str = Query("STOCK", description="자산분류 ('STOCK': 개별주식, 'ETF': ETF)")):
    try:
        data = pe.get_portfolio_live_prices(asset_type=asset_type)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 6-2. 실시간 종목/ETF 자동완성 연관검색 API
@app.get("/api/stock/search")
def search_stock_or_etf_api(
    query: str = Query(..., description="검색어 (한글 종목명/코드/ETF 브랜드명/초성)"),
    asset_type: Optional[str] = Query("ALL", description="자산 유형 ('STOCK': 주식, 'ETF': ETF, 'ALL': 전체)")
):
    candidates = search_all_stock_or_etf(query, asset_type=asset_type or "ALL")
    return {
        "status": "success",
        "query": query,
        "asset_type": asset_type,
        "count": len(candidates),
        "candidates": candidates[:10]  # 상위 10개 연관종목 추천
    }

# 7. 포트폴리오 종목 추가 API
@app.post("/api/portfolio")
def add_portfolio_stock(req: AddStockRequest):
    ticker, name = resolve_ticker(req.ticker_or_name, asset_type_hint=req.asset_type)
    if not ticker:
        raise HTTPException(status_code=404, detail=f"'{req.ticker_or_name}' 종목을 찾을 수 없습니다. 종목명 또는 6자리 코드를 확인 후 다시 시도해 주세요.")

    res = db.add_stock(
        name=name,
        ticker=ticker,
        avg_price=req.avg_price,
        quantity=req.quantity,
        buy_date=req.buy_date or "",
        investment_purpose=req.investment_purpose or "장기투자",
        sector=req.sector or "기타",
        asset_type=req.asset_type or "STOCK",
        market=req.market or "KOSPI"
    )
    if not res.get("success", False):
        raise HTTPException(status_code=500, detail=res.get("error", "종목 추가 실패"))

    # 종목 추가 성공 시 백엔드 포트폴리오 분석 캐시 즉시 무효화
    pe.invalidate_portfolio_cache(req.asset_type)

    return {
        "status": "success",
        "message": res["message"],
        "id": res.get("id")
    }


# 8. 포트폴리오 종목 삭제 API
@app.delete("/api/portfolio/{item_id}")
def delete_portfolio_stock(item_id: int):
    success = db.delete_stock(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="해당 종목을 찾을 수 없거나 이미 삭제되었습니다.")
    
    # 종목 삭제 성공 시 포트폴리오 분석 캐시 전체 무효화
    pe.invalidate_portfolio_cache()
    
    return {
        "status": "success",
        "message": f"포트폴리오 종목(ID: {item_id})이 삭제되었습니다."
    }

# 8-2. 포트폴리오 종목 수정 API (매입단가, 보유수량, 업종)
@app.put("/api/portfolio/{item_id}")
def update_portfolio_stock(item_id: int, req: UpdateStockRequest):
    res = db.update_stock(
        item_id=item_id,
        avg_price=req.avg_price,
        quantity=req.quantity,
        buy_date=req.buy_date or "",
        investment_purpose=req.investment_purpose or "장기투자",
        sector=req.sector or "기타",
        market=req.market or "KOSPI"
    )
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "종목 수정 실패"))
    return {
        "status": "success",
        "message": res["message"]
    }

# 9. 추가매수 시뮬레이션 API
@app.post("/api/portfolio/simulate-add-buy")
def simulate_add_buy(req: SimulateAddBuyRequest):
    current_price = 0.0
    current_avg_price = 0.0
    current_qty = 0

    if req.item_id:
        stock = db.get_stock_by_id(req.item_id)
        if not stock:
            raise HTTPException(status_code=404, detail="포트폴리오 종목을 찾을 수 없습니다.")
        current_avg_price = float(stock["avg_price"])
        current_qty = int(stock["quantity"])
        
        flow_data = get_stock_flow_data(stock["ticker"], min_days=5)
        if flow_data.get("data_available", False):
            current_price = float(flow_data["df"].iloc[-1]['close_price'])
        else:
            current_price = current_avg_price

    elif req.ticker_or_name:
        flow_data = get_stock_flow_data(req.ticker_or_name, min_days=5)
        if flow_data.get("data_available", False):
            current_price = float(flow_data["df"].iloc[-1]['close_price'])
        current_avg_price = current_price
        current_qty = 10
    else:
        raise HTTPException(status_code=400, detail="item_id 또는 ticker_or_name을 입력해주세요.")

    res = pe.calculate_additional_buy(
        current_price=current_price,
        current_avg_price=current_avg_price,
        current_qty=current_qty,
        add_price=req.add_price,
        add_qty=req.add_quantity or 0,
        add_amount=req.add_amount or 0.0
    )

    return {
        "status": "success",
        "simulation": res
    }

# 9. AI Q&A 종목/ETF 식별 검색 API
@app.get("/api/qna/search")
def search_qna_stock_or_etf(q: str = ""):
    candidates = search_stock_or_etf(q)
    return {
        "status": "success",
        "query": q,
        "count": len(candidates),
        "candidates": candidates
    }

# 10. AI Q&A 실시간 뉴스 검색 API (비동기 처리 - 블로킹 방지)
@app.get("/api/qna/news")
async def get_qna_stock_news(ticker: str = "", name: str = "", query: str = ""):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        partial(fetch_qna_stock_news, ticker=ticker, name=name, query=query)
    )
    return res

# 11. AI Q&A 공식자료 검색 API (DART/정부기관/ETF 운용사 - 비동기 처리)
@app.get("/api/qna/official")
async def get_qna_official_docs(
    ticker: str = "",
    name: str = "",
    query: str = "",
    asset_type: str = "STOCK",
    manager: str = ""
):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        partial(
            fetch_official_documents,
            ticker=ticker,
            name=name,
            query=query,
            asset_type=asset_type,
            manager=manager
        )
    )
    return res

# 12. AI Q&A 출처 및 인용 (Citations) 생성 API (STEP 5)
@app.get("/api/qna/citations")
async def get_qna_citations(
    ticker: str = "",
    name: str = "",
    query: str = "",
    asset_type: str = "STOCK",
    manager: str = ""
):
    loop = asyncio.get_event_loop()
    news_res = await loop.run_in_executor(
        None,
        partial(fetch_qna_stock_news, ticker=ticker, name=name, query=query)
    )
    official_res = await loop.run_in_executor(
        None,
        partial(
            fetch_official_documents,
            ticker=ticker,
            name=name,
            query=query,
            asset_type=asset_type,
            manager=manager
        )
    )
    
    news_items = news_res.get("items", []) if news_res.get("status") == "success" else []
    official_items = official_res.get("items", []) if official_res.get("status") == "success" else []

    citations = generate_citations(news_items, official_items)

    return {
        "status": "success",
        "count": len(citations),
        "citations": citations,
        "raw_news_count": len(news_items),
        "raw_official_count": len(official_items)
    }

# 13. STEP 6 — 근거 기반 종합 AI Q&A 리포트 생성 API
@app.get("/api/qna/answer")
async def get_qna_grounded_answer(
    ticker: str = "",
    name: str = "",
    query: str = "",
    asset_type: str = "STOCK",
    manager: str = ""
):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        partial(
            generate_grounded_qna_answer,
            ticker=ticker,
            name=name,
            query=query,
            asset_type=asset_type,
            manager=manager
        )
    )
    return res

# AI Q&A KOSPI/KOSDAQ 전체 상장종목 실시간 검색 API
@app.get("/api/qna/search-target")
def qna_search_target(query: str = Query(..., description="검색어 (종목명/코드/ETF)")):
    candidates = search_all_stock_or_etf(query)
    return {
        "status": "success",
        "query": query,
        "count": len(candidates),
        "candidates": candidates
    }

# =========================================================
# 🧪 7차 Forward Test 전진검증 전용 API 엔드포인트
# =========================================================
@app.get("/api/forward-test/dashboard")
def get_forward_test_dashboard():
    """Forward Test 대시보드 종합 통계 및 이력 반환 API"""
    from backend.engine.forward_test_engine import get_forward_test_dashboard_stats
    stats = get_forward_test_dashboard_stats()
    return {
        "status": "success",
        "data": stats
    }

@app.post("/api/forward-test/evaluate")
def trigger_forward_test_evaluate():
    """Forward Test 5D/10D/20D 미래 성과 자동 추적 및 평가 API"""
    from backend.engine.forward_test_engine import evaluate_forward_outcomes
    res = evaluate_forward_outcomes()
    return {
        "status": "success",
        "result": res
    }

@app.post("/api/forward-test/record")
def record_forward_test_snapshot(payload: dict = Body(...)):
    """Forward Test 신호 스냅샷 수동/자동 독립 기록 API"""
    from backend.engine.forward_test_engine import record_signal_snapshot
    ticker = payload.get("ticker", "")
    name = payload.get("name", "")
    asset_type = payload.get("asset_type", "STOCK")
    price = payload.get("price", 0.0)
    analysis_data = payload.get("analysis_data", {})

    if not ticker or not price:
        raise HTTPException(status_code=400, detail="필수 종목정보가 부족합니다.")

    success = record_signal_snapshot(
        ticker=ticker,
        name=name,
        asset_type=asset_type,
        price=price,
        analysis_data=analysis_data
    )
    return {
        "status": "success" if success else "ignored",
        "recorded": success
    }

@app.delete("/api/forward-test/record/{signal_id}")
def delete_forward_test_signal(signal_id: int):
    """Forward Test 신호 스냅샷 삭제 API"""
    from backend.engine.forward_test_engine import delete_signal_snapshot
    success = delete_signal_snapshot(signal_id)
    if not success:
        raise HTTPException(status_code=404, detail="해당 신호를 찾을 수 없거나 이미 삭제되었습니다.")
    return {"status": "success", "message": f"신호(ID: {signal_id})가 삭제되었습니다."}

# 프론트엔드 정적 파일 서빙 (HTML5 Dashboard UI)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
