import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from backend.engine.recommend_intent_parser import parse_recommendation_intent
from backend.engine.recommendation_analysis_engine import (
    run_quant_recommendation,
    analyze_candidates_quant_parallel,
    rank_quant_candidates
)
from backend.engine.recommendation_flow_screener import analyze_candidate_flow
from backend.db import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommend", tags=["Quant AI Recommendation"])


class RecommendRequest(BaseModel):
    question: str = Field(..., description="추천 요청 질문 문장 (예: '단기 매매 후보 5개 찾아줘')")
    limit: Optional[int] = Field(None, description="선택적 결과 수 제한 (질문 내 숫자가 우선 적용됨)")


@router.post("/ask")
def ask_quant_recommendation(req: RecommendRequest = Body(...)) -> Dict[str, Any]:
    """
    3-B / 3-C / 4단계 Quant 추천 엔진을 백엔드 전용 API로 연결하는 독립 라우트
    """
    t_start = time.time()
    
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="질문 내용(question)을 입력해주세요.")

    # 1. Intent & 파라미터 파싱
    parsed = parse_recommendation_intent(req.question, req_limit=req.limit)
    intent = parsed["intent"]
    market_scope = parsed["market_scope"]
    horizon = parsed["horizon"]
    req_count = parsed["requested_count"]

    results: List[Dict[str, Any]] = []
    message = ""

    try:
        if intent == "PORTFOLIO_SHORT_RANK":
            # 보유 종목 전용 단기 분석 (portfolio.db READ-ONLY)
            holdings = db.get_all_stocks(asset_type="ALL")
            if not holdings:
                message = "현재 등록된 포트폴리오 보유 종목이 없습니다."
            else:
                # 보유 종목 수급 분석 준비
                cands_to_analyze = []
                for h in holdings:
                    cand_flow = analyze_candidate_flow({
                        "ticker": h.get("ticker"),
                        "name": h.get("name"),
                        "price": h.get("avg_price", 0.0),
                        "market": h.get("market", "KOSPI"),
                        "asset_type": h.get("asset_type", "STOCK"),
                        "amount": h.get("avg_price", 0.0) * h.get("quantity", 1)
                    })
                    cands_to_analyze.append(cand_flow)

                analyzed_holdings = analyze_candidates_quant_parallel(cands_to_analyze, max_workers=5)
                ranked_holdings = rank_quant_candidates(analyzed_holdings, recommend_target="SHORT", max_count=req_count, is_etf=False)
                results = ranked_holdings
                message = f"현재 보유 종목({len(holdings)}개) 중 단기 유망 조건에 부합하는 종목 {len(results)}개를 순위별로 정렬했습니다."

        else:
            # 전체 시장 Quant 추천 파이프라인 (Stage 1 -> Stage 2 -> Stage 3)
            quant_res = run_quant_recommendation(stock_stage1_count=100, etf_stage1_count=50, max_workers=5)
            
            stock_all = quant_res["stock_results"]["all_quant_analyzed"]
            etf_all = quant_res["etf_results"]["all_quant_analyzed"]
            all_quant_analyzed = stock_all + etf_all

            if intent == "STOCK_SHORT_RECOMMEND":
                results = quant_res["stock_results"]["short_top"][:req_count]
                message = f"단기 매매 조건(수급 1순위 + TODAY ACTION + 비과열)을 충족한 주식 종목 {len(results)}개를 추천합니다."

            elif intent == "STOCK_MID_RECOMMEND":
                results = quant_res["stock_results"]["mid_top"][:req_count]
                message = f"중기 투자 조건(60/120일선 지지 및 수급 유입)을 충족한 주식 종목 {len(results)}개를 추천합니다."

            elif intent == "ETF_SHORT_RECOMMEND":
                results = quant_res["etf_results"]["short_top"][:req_count]
                message = f"단기 수급 모멘텀이 우수한 ETF 종목 {len(results)}개를 추천합니다."

            elif intent == "ETF_MID_RECOMMEND":
                results = quant_res["etf_results"]["mid_top"][:req_count]
                message = f"중기 추천 가능 ETF pool(인버스/레버리지/단일종목 제외) 중 우수 ETF {len(results)}개를 추천합니다."

            elif intent == "FLOW_JOINT_BUY":
                # Strict JOINT_BUY 필터 (3-C)
                joint_buy_items = [c for c in all_quant_analyzed if c.get("flow_pattern") == "JOINT_BUY"]
                joint_buy_items.sort(key=lambda x: x.get("ffcs", 50.0), reverse=True)
                results = joint_buy_items[:req_count]
                if not results:
                    message = "현재 엄격한 외국인·기관 쌍끌이(1D/3D/5D 동시 순매수) 기준을 충족하는 종목이 없습니다."
                else:
                    message = f"외국인과 기관이 동시 순매수 중인 쌍끌이 종목 {len(results)}개를 찾았습니다."

            elif intent == "FLOW_IMPROVING":
                improving_items = [c for c in stock_all if c.get("flow_pattern") == "FLOW_IMPROVING"]
                improving_items.sort(key=lambda x: x.get("ffcs", 50.0), reverse=True)
                results = improving_items[:req_count]
                message = f"최근 수급이 의미 있게 개선 중인 주식 종목 {len(results)}개를 찾았습니다."

            elif intent == "TREND_NOT_OVERHEATED":
                uptrend_items = [c for c in stock_all if c.get("non_overheated_uptrend") is True]
                uptrend_items.sort(key=lambda x: x.get("ffcs", 50.0), reverse=True)
                results = uptrend_items[:req_count]
                message = f"기술적 과열 없이 안정적인 상승 추세를 유지 중인 종목 {len(results)}개를 찾았습니다."

            elif intent == "PULLBACK_CANDIDATE":
                pullback_items = [c for c in stock_all if c.get("pullback_candidate") is True]
                pullback_items.sort(key=lambda x: x.get("ffcs", 50.0), reverse=True)
                results = pullback_items[:req_count]
                message = f"상승 추세 중 조정을 받아 단기 눌림목 매수 구간에 위치한 종목 {len(results)}개를 찾았습니다."

            else:
                # NORMAL_RECOMMENDATION_UNKNOWN
                results = quant_res["stock_results"]["short_top"][:req_count]
                message = f"추천 조건에 맞는 우수 종목 {len(results)}개를 선별했습니다."

    except Exception as e:
        logger.error(f"[RecommendAPI] Error processing question '{req.question}': {e}", exc_info=True)
        return {
            "status": "unavailable",
            "intent": intent,
            "query": req.question,
            "requested_count": req_count,
            "returned_count": 0,
            "market_scope": market_scope,
            "horizon": horizon,
            "elapsed_ms": int((time.time() - t_start) * 1000),
            "results": [],
            "message": f"추천 엔진 실행 중 오류가 발생했습니다: {str(e)}"
        }

    # 결과 스키마 포맷팅
    formatted_results = []
    for item in results:
        grade_key = "short_grade" if horizon == "SHORT" else "mid_grade"
        reason_key = "short_reasons" if horizon == "SHORT" else "mid_reasons"
        
        grade = item.get(grade_key, item.get("short_grade", "CANDIDATE"))
        reasons = item.get(reason_key, item.get("short_reasons", []))

        formatted_results.append({
            "ticker": item.get("ticker", ""),
            "name": item.get("name", ""),
            "market": item.get("market", "KOSPI"),
            "asset_type": item.get("asset_type", "STOCK"),
            "price": item.get("price", item.get("close_price")),
            "grade": grade,
            "confidence": item.get("confidence", "MEDIUM"),
            "flow_pattern": item.get("flow_pattern", "MIXED"),
            "flow_tier": item.get("flow_tier", "TIER_C"),
            "ffcs": item.get("ffcs", 50.0),
            "fcs": item.get("fcs", "관망"),
            "today_action": item.get("today_action", "HOLD"),
            "today_action_desc": item.get("today_action_desc", "관망"),
            "rsi": item.get("rsi"),
            "rmi": item.get("rmi"),
            "mfi": item.get("mfi"),
            "bollinger_status": item.get("bollinger_status"),
            "ma60": item.get("ma60"),
            "ma120": item.get("ma120"),
            "trend_6m": item.get("trend_6m", 0.0),
            "reasons": reasons
        })

    elapsed_ms = int((time.time() - t_start) * 1000)

    return {
        "status": "ok",
        "intent": intent,
        "query": req.question,
        "requested_count": req_count,
        "returned_count": len(formatted_results),
        "market_scope": market_scope,
        "horizon": horizon,
        "elapsed_ms": elapsed_ms,
        "cache": {
            "stage1": True,
            "stage2": True,
            "stage3": True
        },
        "results": formatted_results,
        "message": message
    }
