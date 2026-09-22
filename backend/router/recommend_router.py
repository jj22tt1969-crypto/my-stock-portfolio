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
    "status": "EMPTY",          # EMPTY | WARMING | READY | STALE | FAILED
    "quant_res": None,          # 현재 유효 quant_res (READY/STALE 시 사용)
    "last_good_quant_res": None, # 마지막 성공 quant_res (FAILED 후 STALE fallback용)
    "warmed_at": None,          # datetime (UTC) 마지막 완료 시각
    "elapsed_sec": None,        # 마지막 Pre-Warm 소요 시간
    "error": None,              # FAILED 시 오류 메시지
}
_SNAPSHOT_LOCK = threading.Lock()


def _get_snapshot_copy() -> Dict[str, Any]:
    """Lock 안에서 스냅샷 현재 상태를 안전하게 복사 반환"""
    with _SNAPSHOT_LOCK:
        return {
            "status": _RECOMMEND_SNAPSHOT["status"],
            "quant_res": _RECOMMEND_SNAPSHOT["quant_res"],
            "last_good_quant_res": _RECOMMEND_SNAPSHOT["last_good_quant_res"],
            "warmed_at": _RECOMMEND_SNAPSHOT["warmed_at"],
            "elapsed_sec": _RECOMMEND_SNAPSHOT["elapsed_sec"],
            "error": _RECOMMEND_SNAPSHOT["error"],
        }


def _trigger_background_warm(import_executor=None) -> bool:
    """
    사용자 요청 흐름에서 비동기적으로 warm_recommend_snapshot을 실행한다.
    - 이미 WARMING 중이면 중복 실행하지 않는다.
    - ThreadPoolExecutor를 직접 사용해 블로킹 없이 백그라운드 실행.
    - 반환값: 새 warm 작업이 시작됐으면 True, 스킵이면 False
    """
    with _SNAPSHOT_LOCK:
        if _RECOMMEND_SNAPSHOT["status"] == "WARMING":
            return False
        _RECOMMEND_SNAPSHOT["status"] = "WARMING"
        _RECOMMEND_SNAPSHOT["error"] = None

    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    executor.submit(_do_warm_job)
    executor.shutdown(wait=False)
    logger.info("[Snapshot] 사용자 요청으로 background warm 시작")
    return True


def _do_warm_job():
    """실제 Pre-Warm 수행 (별도 스레드)"""
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
            _RECOMMEND_SNAPSHOT["last_good_quant_res"] = quant_res
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
            # last_good_quant_res는 보존 (STALE fallback 용)
            _RECOMMEND_SNAPSHOT["elapsed_sec"] = round(elapsed, 2)
            _RECOMMEND_SNAPSHOT["error"] = str(e)
        logger.error(f"[Snapshot] Pre-Warm 실패 ({elapsed:.2f}초): {e}", exc_info=True)
        return False


def warm_recommend_snapshot(force: bool = False) -> bool:
    """
    전체시장 Quant 추천 스냅샷을 Pre-Warm한다 (main.py startup 호출용).
    - 이미 WARMING 중이면 중복 실행 방지 후 False 반환
    - force=True 시 READY 상태도 강제 재수행
    - 완료 시 True, 실패/스킵 시 False 반환 (동기 실행)
    """
    with _SNAPSHOT_LOCK:
        current_status = _RECOMMEND_SNAPSHOT["status"]
        if current_status == "WARMING":
            logger.info("[Snapshot] 이미 WARMING 중 - 중복 Pre-Warm 스킵")
            return False
        if not force and current_status == "READY":
            warmed_at = _RECOMMEND_SNAPSHOT.get("warmed_at")
            if warmed_at:
                elapsed = (datetime.now(timezone.utc) - warmed_at).total_seconds()
                if elapsed < _SNAPSHOT_TTL_SECONDS:
                    logger.info(f"[Snapshot] 신선한 스냅샷 존재 (경과 {elapsed:.0f}s) - Pre-Warm 스킵")
                    return False
        _RECOMMEND_SNAPSHOT["status"] = "WARMING"
        _RECOMMEND_SNAPSHOT["error"] = None

    return _do_warm_job()

router = APIRouter(prefix="/api/recommend", tags=["Quant AI Recommendation"])


@router.get("/status")
def get_recommend_status() -> Dict[str, Any]:
    """
    Recommendation Snapshot 상태 조회 API
    상태: EMPTY | WARMING | READY | STALE | FAILED
    """
    snap = _get_snapshot_copy()
    status = snap["status"]
    warmed_at = snap["warmed_at"]
    elapsed_sec = snap["elapsed_sec"]
    error = snap["error"]
    has_last_good = snap["last_good_quant_res"] is not None

    age_sec = None
    data_as_of = None
    if warmed_at is not None:
        age_sec = round((datetime.now(timezone.utc) - warmed_at).total_seconds())
        data_as_of = warmed_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "status": status,
        "snapshot_age_sec": age_sec,
        "snapshot_ttl_sec": _SNAPSHOT_TTL_SECONDS,
        "last_elapsed_sec": elapsed_sec,
        "data_as_of": data_as_of,
        "has_last_good": has_last_good,
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
    is_stale_data = False
    data_as_of = None

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
            # READY & 신선  → 스냅샷 즉시 재사용 (0ms)
            # WARMING        → PREPARING 즉시 반환 (polling 유도)
            # STALE          → last_good 재사용 + stale=True + background refresh
            # EMPTY          → background warm 시작 + PREPARING 즉시 반환
            # FAILED + last_good → last_good STALE 재사용 + background refresh
            # FAILED + 없음  → DATA_UNAVAILABLE 즉시 반환
            # ★ 어떤 경우에도 HTTP 요청 안에서 Cold Fetch 동기 수행 금지 ★
            snap = _get_snapshot_copy()
            snap_status = snap["status"]
            snap_quant_res = snap["quant_res"]
            snap_warmed_at = snap["warmed_at"]
            snap_last_good = snap["last_good_quant_res"]

            # READY & 신선도 판단
            snap_age = None
            snap_fresh = False
            if snap_quant_res is not None and snap_warmed_at is not None:
                snap_age = (datetime.now(timezone.utc) - snap_warmed_at).total_seconds()
                snap_fresh = (snap_status == "READY") and (snap_age < _SNAPSHOT_TTL_SECONDS)

            data_as_of = snap_warmed_at.strftime("%Y-%m-%d %H:%M") if snap_warmed_at else None
            is_stale_data = False

            if snap_fresh:
                # ① 캐시 히트: READY 스냅샷 즉시 재사용
                logger.info(f"[RecommendAPI] 스냅샷 캐시 히트 (경과 {snap_age:.0f}s)")
                quant_res = snap_quant_res

            elif snap_status == "WARMING":
                # ② Pre-Warm 진행 중 → PREPARING 즉시 반환
                return {
                    "status": "preparing",
                    "intent": intent,
                    "query": req.question,
                    "requested_count": req_count,
                    "returned_count": 0,
                    "market_scope": market_scope,
                    "horizon": horizon,
                    "elapsed_ms": int((time.time() - t_start) * 1000),
                    "results": [],
                    "message": "전체시장 추천 데이터를 준비하고 있습니다. 잠시만 기다려 주세요."
                }

            elif snap_status in ("STALE",) and snap_quant_res is not None:
                # ③ STALE: 기존 데이터 재사용 + background refresh
                logger.info(f"[RecommendAPI] STALE 스냅샷 재사용 (data_as_of={data_as_of})")
                quant_res = snap_quant_res
                is_stale_data = True
                _trigger_background_warm()

            elif snap_status == "FAILED" and snap_last_good is not None:
                # ④ FAILED + last_good 있음: STALE 재사용 + background refresh
                logger.warning(f"[RecommendAPI] FAILED 상태이나 last_good 재사용 (STALE fallback)")
                quant_res = snap_last_good
                is_stale_data = True
                _trigger_background_warm()

            elif snap_status == "FAILED" and snap_last_good is None:
                # ⑤ FAILED + last_good 없음: 즉시 DATA_UNAVAILABLE
                _trigger_background_warm()  # 1회만 재시도 트리거
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
                    "message": "수급 데이터 수집에 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."
                }

            else:
                # ⑥ EMPTY (또는 기타 미준비): background warm 시작 + PREPARING 즉시 반환
                logger.info(f"[RecommendAPI] 스냅샷 미준비(status={snap_status}) - background warm 트리거")
                _trigger_background_warm()
                return {
                    "status": "preparing",
                    "intent": intent,
                    "query": req.question,
                    "requested_count": req_count,
                    "returned_count": 0,
                    "market_scope": market_scope,
                    "horizon": horizon,
                    "elapsed_ms": int((time.time() - t_start) * 1000),
                    "results": [],
                    "message": "전체시장 추천 데이터를 준비하고 있습니다. 잠시만 기다려 주세요."
                }
            
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
        "stale": is_stale_data,
        "data_as_of": data_as_of,
        "cache": {
            "stage1": True,
            "stage2": True,
            "stage3": True
        },
        "results": formatted_results,
        "message": message
    }

