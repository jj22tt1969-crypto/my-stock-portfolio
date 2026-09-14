import os
import time
import logging
import concurrent.futures
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

from backend.engine.recommendation_screener import screen_stock_universe, screen_etf_universe
from backend.data.collector import get_stock_flow_data

logger = logging.getLogger(__name__)


def _extract_period_flow(df: pd.DataFrame, col: str, period: int) -> Dict[str, Any]:
    """
    DataFrame에서 최근 N일간의 지정 수급 컬럼(foreign_net_buy / institution_net_buy) 합계 및 방향 추출
    """
    if df is None or df.empty or len(df) < period or col not in df.columns:
        return {"net_buy": 0.0, "direction": "중립"}

    sub_df = df.iloc[-period:]
    val = float(sub_df[col].sum())
    direction = "매수" if val > 0 else ("매도" if val < 0 else "중립")
    return {
        "net_buy": round(val, 2),
        "direction": direction
    }


def analyze_candidate_flow(candidate: Dict[str, Any], min_days: int = 20) -> Dict[str, Any]:
    """
    단일 후보(STOCK 또는 ETF)에 대해 기존 collector의 get_stock_flow_data를 호출하여
    1D/3D/5D/10D/20D 수급 데이터 확보 및 패턴/Tier 분류
    """
    ticker = candidate.get("ticker", "")
    name = candidate.get("name", "")
    
    # 1. 수급 데이터 Fetch (collector 기존 logic & cache 재사용)
    try:
        flow_res = get_stock_flow_data(ticker, min_days=min_days)
    except Exception as e:
        logger.warning(f"[FlowScreener] Exception fetching flow for {name}({ticker}): {e}")
        flow_res = None

    if not flow_res or not flow_res.get("data_available", False):
        return {
            **candidate,
            "flow_status": flow_res.get("status_code", "FETCH_FAILED") if flow_res else "FETCH_FAILED",
            "data_available": False,
            "foreign": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
            "institution": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
            "flow_pattern": "DATA_INSUFFICIENT",
            "flow_tier": "TIER_D",
            "flow_reasons": ["수급 데이터 수집 실패 또는 데이터 부족"]
        }

    df = flow_res.get("df")
    if df is None or len(df) < 5:
        return {
            **candidate,
            "flow_status": "DATA_INSUFFICIENT",
            "data_available": False,
            "foreign": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
            "institution": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
            "flow_pattern": "DATA_INSUFFICIENT",
            "flow_tier": "TIER_D",
            "flow_reasons": ["유효 거래일 데이터 5일 미만"]
        }

    # 2. 외국인 & 기관 1d/3d/5d/10d/20d 수급 추출
    periods = [1, 3, 5, 10, 20]
    foreign_flows = {f"{p}d": _extract_period_flow(df, "foreign_net_buy", p) for p in periods}
    inst_flows = {f"{p}d": _extract_period_flow(df, "institution_net_buy", p) for p in periods}

    f1, f3, f5, f10, f20 = [foreign_flows[f"{p}d"]["net_buy"] for p in periods]
    i1, i3, i5, i10, i20 = [inst_flows[f"{p}d"]["net_buy"] for p in periods]

    # 3. 단기/중기 수급 판단 보조 변수
    # 단기 (1D, 3D, 5D)
    def _is_pos(v):
        if v is None or pd.isna(v):
            return False
        return float(v) > 0

    f_st_strict_buy = _is_pos(f1) and _is_pos(f3) and _is_pos(f5)
    i_st_strict_buy = _is_pos(i1) and _is_pos(i3) and _is_pos(i5)
    is_strict_joint_buy = f_st_strict_buy and i_st_strict_buy

    f_st_pos_cnt = sum(1 for v in [f1, f3, f5] if _is_pos(v))
    f_st_neg_cnt = sum(1 for v in [f1, f3, f5] if v is not None and not pd.isna(v) and float(v) < 0)
    i_st_pos_cnt = sum(1 for v in [i1, i3, i5] if _is_pos(v))
    i_st_neg_cnt = sum(1 for v in [i1, i3, i5] if v is not None and not pd.isna(v) and float(v) < 0)

    f_st_buy = (f_st_pos_cnt >= 2 and (f1 + f3 + f5) > 0)
    f_st_sell = (f_st_neg_cnt >= 2 and (f1 + f3 + f5) < 0)
    i_st_buy = (i_st_pos_cnt >= 2 and (i1 + i3 + i5) > 0)
    i_st_sell = (i_st_neg_cnt >= 2 and (i1 + i3 + i5) < 0)

    # 중기 (10D, 20D)
    f_mt_neg = (f10 <= 0 or f20 <= 0 or (f10 + f20) <= 0)
    i_mt_neg = (i10 <= 0 or i20 <= 0 or (i10 + i20) <= 0)

    # 전 기간 (1D~20D)
    f_all_pos = all(_is_pos(v) for v in [f1, f3, f5, f10, f20])
    i_all_pos = all(_is_pos(v) for v in [i1, i3, i5, i10, i20])

    # 4. 수급 패턴 식별 (Prioritized Pattern Classification)
    pattern = "MIXED"
    tier = "TIER_C"
    reasons = []

    # A. PERSISTENT_ACCUMULATION (단기/중기 전 기간 지속 매집)
    if (f_all_pos and i5 >= 0) or (i_all_pos and f5 >= 0) or (f_all_pos and i_all_pos):
        pattern = "PERSISTENT_ACCUMULATION"
        tier = "TIER_A"
        if f_all_pos and i_all_pos:
            reasons.append("외국인·기관 1D~20D 전 기간 동반 지속 매집")
        elif f_all_pos:
            reasons.append("외국인 1D~20D 전 기간 지속 매집 유입")
        else:
            reasons.append("기관 1D~20D 전 기간 지속 매집 유입")

    # B. JOINT_BUY (외국인·기관 엄격 동반 순매수 / 6개 수급 1D/3D/5D 모두 > 0)
    elif is_strict_joint_buy:
        pattern = "JOINT_BUY"
        tier = "TIER_A"
        reasons.append("외국인·기관 단기(1D/3D/5D) 동반 순매수(쌍끌이)")

    # C. FLOW_IMPROVING (중기 약세/매도에서 최근 단기 수급 개선)
    elif (f_mt_neg and f_st_buy) or (i_mt_neg and i_st_buy):
        pattern = "FLOW_IMPROVING"
        # 외국인/기관 모두 단기 전환 시 TIER_A, 한쪽만 강하게 전환 시 TIER_A or TIER_B
        if f_st_buy and i_st_buy:
            tier = "TIER_A"
            reasons.append("중기 약세 탈출, 외국인·기관 단기 수급 턴어라운드 동반 순매수")
        elif f_st_buy and i5 >= 0:
            tier = "TIER_A"
            reasons.append("중기 매도세 극복, 외국인 단기 수급 강한 개선 전환")
        elif i_st_buy and f5 >= 0:
            tier = "TIER_A"
            reasons.append("중기 매도세 극복, 기관 단기 수급 강한 개선 전환")
        else:
            tier = "TIER_B"
            improving_target = "외국인" if f_st_buy else "기관"
            reasons.append(f"중기 매도 대비 {improving_target} 단기 수급 개선 유입")

    # D. DETERIORATING (최근 단기 수급 악화)
    elif (f_st_sell and i_st_sell) or (f_st_sell and i5 <= 0) or (i_st_sell and f5 <= 0):
        pattern = "DETERIORATING"
        tier = "TIER_D"
        if f_st_sell and i_st_sell:
            reasons.append("외국인·기관 단기(1D/3D/5D) 동반 매도세 확대")
        else:
            reasons.append("단기(1D/3D/5D) 주력 수급 매도 전환 및 악화")

    # E. MIXED (기타 방향 엇갈림 or 기간별 혼조)
    else:
        pattern = "MIXED"
        # 단기 긍정 수급이 일부 존재하면 TIER_B, 그렇지 않으면 TIER_C
        if (f1 > 0 and f5 > 0) or (i1 > 0 and i5 > 0):
            tier = "TIER_B"
            reasons.append("외국인/기관 수급 방향 엇갈림 속 부분적 단기 순매수")
        else:
            tier = "TIER_C"
            reasons.append("외국인/기관 수급 엇갈림 및 기간별 혼조")

    return {
        **candidate,
        "flow_status": "OK",
        "data_available": True,
        "foreign": foreign_flows,
        "institution": inst_flows,
        "flow_pattern": pattern,
        "flow_tier": tier,
        "flow_reasons": reasons
    }


def process_candidates_flow_parallel(
    candidates: List[Dict[str, Any]],
    max_workers: int = 10
) -> List[Dict[str, Any]]:
    """
    후보 리스트에 대해 Bounded ThreadPoolExecutor 기반 안전한 병렬 수급 분석 수행
    개별 종목 예외 발생 시 전체 분석이 멈추지 않도록 isolation 적용
    """
    results = []
    if not candidates:
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cand = {executor.submit(analyze_candidate_flow, cand): cand for cand in candidates}
        for future in concurrent.futures.as_completed(future_to_cand):
            cand = future_to_cand[future]
            try:
                res = future.result(timeout=10.0)
                results.append(res)
            except concurrent.futures.TimeoutError:
                logger.warning(f"[FlowScreener] Timeout analyzing flow for {cand.get('name')}({cand.get('ticker')})")
                results.append({
                    **cand,
                    "flow_status": "TIMEOUT",
                    "data_available": False,
                    "foreign": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
                    "institution": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
                    "flow_pattern": "DATA_INSUFFICIENT",
                    "flow_tier": "TIER_D",
                    "flow_reasons": ["수급 분석 타임아웃 발생"]
                })
            except Exception as e:
                logger.error(f"[FlowScreener] Exception analyzing flow for {cand.get('name')}({cand.get('ticker')}): {e}")
                results.append({
                    **cand,
                    "flow_status": "EXCEPTION",
                    "data_available": False,
                    "foreign": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
                    "institution": {p: {"net_buy": 0.0, "direction": "중립"} for p in ["1d", "3d", "5d", "10d", "20d"]},
                    "flow_pattern": "DATA_INSUFFICIENT",
                    "flow_tier": "TIER_D",
                    "flow_reasons": [f"수급 분석 중 예외 발생: {str(e)}"]
                })

    # 원래 후보 순서(Stage1 유동성 순위) 보존
    ticker_to_result = {r["ticker"]: r for r in results}
    ordered_results = [ticker_to_result.get(c["ticker"], analyze_candidate_flow(c)) for c in candidates]
    return ordered_results


def _compress_stage3_candidates(
    analyzed_candidates: List[Dict[str, Any]],
    target_count: int
) -> List[Dict[str, Any]]:
    """
    Tier 및 수급 긍정 가점 기준으로 Stage3 정밀분석 대상 후보 압축
    - 1순위: TIER_A (지속매집, 쌍끌이, 강력 턴어라운드)
    - 2순위: TIER_B (부분적 긍정 수급, 개선 전환)
    - TIER_C/D는 정밀분석 압축 후보에서 기본 제외
    - 시장 수급 조건 충족 종목이 적으면 억지로 숫자를 채우지 않음 (가짜 후보 생성 금지)
    """
    tier_a = [c for c in analyzed_candidates if c.get("flow_tier") == "TIER_A"]
    tier_b = [c for c in analyzed_candidates if c.get("flow_tier") == "TIER_B"]

    def _flow_score(c):
        # 수급 긍정 결합도 계산 (정렬 보조용)
        f_5d = c.get("foreign", {}).get("5d", {}).get("net_buy", 0.0)
        i_5d = c.get("institution", {}).get("5d", {}).get("net_buy", 0.0)
        f_1d = c.get("foreign", {}).get("1d", {}).get("net_buy", 0.0)
        i_1d = c.get("institution", {}).get("1d", {}).get("net_buy", 0.0)
        return (f_5d + i_5d) + (f_1d + i_1d)

    tier_a_sorted = sorted(tier_a, key=_flow_score, reverse=True)
    tier_b_sorted = sorted(tier_b, key=_flow_score, reverse=True)

    compressed = []
    compressed.extend(tier_a_sorted)

    if len(compressed) < target_count:
        needed = target_count - len(compressed)
        compressed.extend(tier_b_sorted[:needed])

    return compressed


def run_flow_screener(
    stock_stage1_count: int = 100,
    etf_stage1_count: int = 50,
    stock_stage3_target: int = 25,
    etf_stage3_target: int = 15,
    max_workers: int = 10
) -> Dict[str, Any]:
    """
    Phase 3-C 수급 2차 스크리너 메인 실행 함수
    Stage 1 후보(STOCK 100, ETF 50)에 대해서만 수급 정밀 스크리닝 및 압축 수행
    """
    t_start = time.time()

    # 1. Stage 1 유동성 스크리닝 공급
    stock_stage1_res = screen_stock_universe(stock_stage1_count)
    etf_stage1_res = screen_etf_universe(etf_stage1_count)

    stock_candidates_input = stock_stage1_res.get("candidates", [])
    etf_candidates_input = etf_stage1_res.get("candidates", [])

    # 2. STOCK 수급 분석 (병렬)
    t0_stock = time.time()
    stock_analyzed = process_candidates_flow_parallel(stock_candidates_input, max_workers=max_workers)
    t_stock_elapsed = time.time() - t0_stock

    # 3. ETF 수급 분석 (병렬)
    t0_etf = time.time()
    etf_analyzed = process_candidates_flow_parallel(etf_candidates_input, max_workers=max_workers)
    t_etf_elapsed = time.time() - t0_etf

    # 4. Stage 3 정밀분석 대상 후보 압축
    stock_stage3 = _compress_stage3_candidates(stock_analyzed, stock_stage3_target)
    etf_stage3 = _compress_stage3_candidates(etf_analyzed, etf_stage3_target)

    # 5. 통계 및 요약 산출
    def _get_stats(analyzed_list):
        succ = sum(1 for c in analyzed_list if c.get("data_available", False))
        fail = len(analyzed_list) - succ
        tier_a_cnt = sum(1 for c in analyzed_list if c.get("flow_tier") == "TIER_A")
        tier_b_cnt = sum(1 for c in analyzed_list if c.get("flow_tier") == "TIER_B")
        tier_c_cnt = sum(1 for c in analyzed_list if c.get("flow_tier") == "TIER_C")
        tier_d_cnt = sum(1 for c in analyzed_list if c.get("flow_tier") == "TIER_D")
        
        pattern_counts = {
            "JOINT_BUY": sum(1 for c in analyzed_list if c.get("flow_pattern") == "JOINT_BUY"),
            "FLOW_IMPROVING": sum(1 for c in analyzed_list if c.get("flow_pattern") == "FLOW_IMPROVING"),
            "PERSISTENT_ACCUMULATION": sum(1 for c in analyzed_list if c.get("flow_pattern") == "PERSISTENT_ACCUMULATION"),
            "MIXED": sum(1 for c in analyzed_list if c.get("flow_pattern") == "MIXED"),
            "DETERIORATING": sum(1 for c in analyzed_list if c.get("flow_pattern") == "DETERIORATING"),
            "DATA_INSUFFICIENT": sum(1 for c in analyzed_list if c.get("flow_pattern") == "DATA_INSUFFICIENT")
        }
        return {
            "total_input": len(analyzed_list),
            "success_count": succ,
            "failed_count": fail,
            "tier_a": tier_a_cnt,
            "tier_b": tier_b_cnt,
            "tier_c": tier_c_cnt,
            "tier_d": tier_d_cnt,
            "pattern_counts": pattern_counts
        }

    stock_stats = _get_stats(stock_analyzed)
    etf_stats = _get_stats(etf_analyzed)

    total_elapsed = time.time() - t_start

    return {
        "status": "success",
        "max_workers": max_workers,
        "total_elapsed_sec": round(total_elapsed, 2),
        "stock_results": {
            "stats": stock_stats,
            "elapsed_sec": round(t_stock_elapsed, 2),
            "stage3_count": len(stock_stage3),
            "stage3_candidates": stock_stage3,
            "all_analyzed": stock_analyzed
        },
        "etf_results": {
            "stats": etf_stats,
            "elapsed_sec": round(t_etf_elapsed, 2),
            "stage3_count": len(etf_stage3),
            "stage3_candidates": etf_stage3,
            "all_analyzed": etf_analyzed
        }
    }
