import time
import logging
import threading
from datetime import datetime, timezone
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

# ─────────────────────────────────────────────────────────────
# Recommendation Snapshot: Pre-Warm 전역 상태 관리
# 상태: EMPTY → WARMING → READY → (STALE → WARMING → READY ...)
#        EMPTY → WARMING → FAILED → EMPTY
# TTL: 스냅샷 유효 시간 (기본 20분)
# ─────────────────────────────────────────────────────────────
_SNAPSHOT_TTL_SECONDS = 20 * 60  # 20분

_RECOMMEND_SNAPSHOT: Dict[str, Any] = {
    "status": "EMPTY",         # EMPTY | WARMING | READY | STALE | FAILED
    "quant_res": None,         # run_quant_recommendation() 결과
    "warmed_at": None,         # datetime (UTC) 마지막 완료 시각
    "elapsed_sec": None,       # 마지막 Pre-Warm 소요 시간
    "error": None,             # FAILED 시 오류 메시지
}
_SNAPSHOT_LOCK = threading.Lock()


def _snapshot_is_fresh() -> bool:
    """스냅샷이 READY이고 TTL 내인지 확인"""
    with _SNAPSHOT_LOCK:
        if _RECOMMEND_SNAPSHOT["status"] != "READY":
            return False
        warmed_at = _RECOMMEND_SNAPSHOT.get("warmed_at")
        if warmed_at is None:
            return False
        elapsed = (datetime.now(timezone.utc) - warmed_at).total_seconds()
        return elapsed < _SNAPSHOT_TTL_SECONDS


def warm_recommend_snapshot(force: bool = False) -> bool:
    """
    전체시장 Quant 추천 스냅샷을 Pre-Warm한다.
    - 이미 WARMING 중이면 중복 실행 방지 후 False 반환
    - force=True 시 READY 상태도 강제 재수행
    - 완료 시 True, 실패/스킵 시 False 반환
    """
    with _SNAPSHOT_LOCK:
        current_status = _RECOMMEND_SNAPSHOT["status"]
        # 중복 실행 방지
        if current_status == "WARMING":
            logger.info("[Snapshot] 이미 WARMING 중 - 중복 Pre-Warm 스킵")
            return False
        # 신선한 READY 상태이고 강제 아니면 스킵
        if not force and current_status == "READY":
            warmed_at = _RECOMMEND_SNAPSHOT.get("warmed_at")
            if warmed_at:
                elapsed = (datetime.now(timezone.utc) - warmed_at).total_seconds()
                if elapsed < _SNAPSHOT_TTL_SECONDS:
                    logger.info(f"[Snapshot] 신선한 스냅샷 존재 (경과 {elapsed:.0f}s) - Pre-Warm 스킵")
                    return False
        # WARMING 상태로 전환
        _RECOMMEND_SNAPSHOT["status"] = "WARMING"
        _RECOMMEND_SNAPSHOT["error"] = None

    logger.info("[Snapshot] Pre-Warm 시작 (Stage1 → Stage2 → Stage3)")
    t_start = time.time()
    try:
        quant_res = run_quant_recommendation(
            stock_stage1_count=100,
            etf_stage1_count=50,
            max_workers=10
        )
        elapsed = time.time() - t_start
        with _SNAPSHOT_LOCK:
            _RECOMMEND_SNAPSHOT["status"] = "READY"
            _RECOMMEND_SNAPSHOT["quant_res"] = quant_res
            _RECOMMEND_SNAPSHOT["warmed_at"] = datetime.now(timezone.utc)
            _RECOMMEND_SNAPSHOT["elapsed_sec"] = round(elapsed, 2)
            _RECOMMEND_SNAPSHOT["error"] = None
        logger.info(f"[Snapshot] Pre-Warm 완료: {elapsed:.2f}초")
        return True
    except Exception as e:
        elapsed = time.time() - t_start
        with _SNAPSHOT_LOCK:
            _RECOMMEND_SNAPSHOT["status"] = "FAILED"
            _RECOMMEND_SNAPSHOT["quant_res"] = None
            _RECOMMEND_SNAPSHOT["elapsed_sec"] = round(elapsed, 2)
            _RECOMMEND_SNAPSHOT["error"] = str(e)
        logger.error(f"[Snapshot] Pre-Warm 실패 ({elapsed:.2f}초): {e}", exc_info=True)
        return False

router = APIRouter(prefix="/api/recommend", tags=["Quant AI Recommendation"])


@router.get("/status")
def get_recommend_status() -> Dict[str, Any]:
    """
    Recommendation Snapshot 상태 조회 API
    상태: EMPTY | WARMING | READY | STALE | FAILED
    """
    with _SNAPSHOT_LOCK:
        status = _RECOMMEND_SNAPSHOT["status"]
        warmed_at = _RECOMMEND_SNAPSHOT.get("warmed_at")
        elapsed_sec = _RECOMMEND_SNAPSHOT.get("elapsed_sec")
        error = _RECOMMEND_SNAPSHOT.get("error")

    age_sec = None
    if warmed_at is not None:
        age_sec = round((datetime.now(timezone.utc) - warmed_at).total_seconds())

    return {
        "status": status,
        "snapshot_age_sec": age_sec,
        "snapshot_ttl_sec": _SNAPSHOT_TTL_SECONDS,
        "last_elapsed_sec": elapsed_sec,
        "error": error,
    }


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
            # ─── 전체 시장 Quant 추천 파이프라인 ───
            # 스냅샷 READY & 신선 → 즉시 재사용 (0~1초)
            # 스냅샷 WARMING → Pre-Warm 진행 중 메시지 반환
            # 스냅샷 EMPTY/FAILED → Cold Fetch 직접 수행 (fallback)
            with _SNAPSHOT_LOCK:
                snap_status = _RECOMMEND_SNAPSHOT["status"]
                snap_quant_res = _RECOMMEND_SNAPSHOT.get("quant_res")
                snap_warmed_at = _RECOMMEND_SNAPSHOT.get("warmed_at")

            snap_fresh = False
            if snap_status == "READY" and snap_quant_res is not None and snap_warmed_at is not None:
                age = (datetime.now(timezone.utc) - snap_warmed_at).total_seconds()
                snap_fresh = age < _SNAPSHOT_TTL_SECONDS

            if snap_fresh:
                # 캐시 히트: 스냅샷 즉시 재사용
                logger.info(f"[RecommendAPI] 스냅샷 캐시 히트 (경과 {age:.0f}s)")
                quant_res = snap_quant_res
            elif snap_status == "WARMING":
                # Pre-Warm 진행 중 → 사용자에게 안내 후 조기 반환
                return {
                    "status": "warming",
                    "intent": intent,
                    "query": req.question,
                    "requested_count": req_count,
                    "returned_count": 0,
                    "market_scope": market_scope,
                    "horizon": horizon,
                    "elapsed_ms": int((time.time() - t_start) * 1000),
                    "results": [],
                    "message": "추천 데이터를 준비하고 있습니다. 잠시 후 다시 시도해 주세요. (약 30~60초 소요)"
                }
            else:
                # EMPTY / FAILED / STALE → Cold Fetch fallback (직접 실행)
                logger.warning(f"[RecommendAPI] 스냅샷 미준비(snap_status={snap_status}) - Cold Fetch 직접 수행")
                quant_res = run_quant_recommendation(stock_stage1_count=100, etf_stage1_count=50, max_workers=10)
                # Cold Fetch 완료 후 스냅샷에도 저장 (다음 요청 대비)
                with _SNAPSHOT_LOCK:
                    _RECOMMEND_SNAPSHOT["status"] = "READY"
                    _RECOMMEND_SNAPSHOT["quant_res"] = quant_res
                    _RECOMMEND_SNAPSHOT["warmed_at"] = datetime.now(timezone.utc)
                    _RECOMMEND_SNAPSHOT["elapsed_sec"] = round(time.time() - t_start, 2)
                    _RECOMMEND_SNAPSHOT["error"] = None
            
            stock_all = quant_res["stock_results"]["all_quant_analyzed"]
            etf_all = quant_res["etf_results"]["all_quant_analyzed"]
            all_quant_analyzed = stock_all + etf_all

            # 수급 데이터 가용성 통계 확인 (DATA_UNAVAILABLE / PARTIAL_DATA 판정용)
            flow_stats = quant_res.get("flow_screener_stats", {})
            target_stats = flow_stats.get("etf_stats", {}) if market_scope == "ETF" else flow_stats.get("stock_stats", {})
            total_input = target_stats.get("total_input", 100)
            succ_cnt = target_stats.get("success_count", 0)
            fail_cnt = target_stats.get("failed_count", 0)

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

            # 상태(status) 및 메시지 정밀 결정 (OK, NO_MATCH, DATA_UNAVAILABLE, PARTIAL_DATA)
            if not results:
                if succ_cnt == 0 or fail_cnt >= int(total_input * 0.8):
                    res_status = "DATA_UNAVAILABLE"
                    message = "수급 데이터 수집이 원활하지 않아 추천을 보류했습니다. 잠시 후 다시 시도해 주세요."
                else:
                    res_status = "NO_MATCH"
                    message = "현재 조건을 충족하는 종목이 없습니다."
            else:
                if fail_cnt > 0:
                    res_status = "PARTIAL_DATA"
                    message = f"{message} (일부 종목의 수급 데이터가 지연되어 확인 가능한 후보만 분석했습니다.)"
                else:
                    res_status = "OK"

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
        "status": res_status,
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
