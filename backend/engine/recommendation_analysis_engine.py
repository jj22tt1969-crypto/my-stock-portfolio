import os
import time
import logging
import concurrent.futures
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

from backend.engine.recommendation_flow_screener import run_flow_screener, analyze_candidate_flow
from backend.data.collector import fetch_stock_chart_analysis, get_stock_flow_data
from backend.engine.flow_engine import calculate_ffcs, analyze_period_flows
from backend.engine.technical_engine import calculate_technical_indicators
from backend.engine.timing_engine import calculate_bollinger_bands
from backend.engine.decision_engine import (
    calculate_buy_score,
    calculate_sell_score,
    calculate_watering_score,
    make_final_decision,
    apply_conditional_trend_filter
)

logger = logging.getLogger(__name__)


_QUANT_CHART_CACHE: Dict[str, tuple] = {}
_CHART_CACHE_TTL = 600  # 10분 TTL


def _get_cached_chart_analysis(ticker: str, timeframe: str = 'day') -> Optional[Dict[str, Any]]:
    now = time.time()
    if ticker in _QUANT_CHART_CACHE:
        ts, res = _QUANT_CHART_CACHE[ticker]
        if now - ts < _CHART_CACHE_TTL:
            return res
    res = fetch_stock_chart_analysis(ticker, timeframe=timeframe)
    if res and res.get("status") == "success":
        _QUANT_CHART_CACHE[ticker] = (now, res)
    return res


def classify_etf_type(name: str) -> str:
    """
    ETF 상품명 기반 9가지 상세 자산군/유형 분류
    - PLAIN_EQUITY, SECTOR_THEME, LEVERAGED, INVERSE, BOND_RATE, MONEY_MARKET, COMMODITY, SINGLE_STOCK, OTHER
    """
    name_upper = name.upper()
    
    # 1. 인버스 (곱버스 포함)
    if any(k in name_upper for k in ["인버스", "INVERSE", "2X인버스", "곱버스"]):
        if any(k in name_upper for k in ["단일종목", "SK하이닉스선물", "삼성전자선물"]):
            return "SINGLE_STOCK"
        return "INVERSE"

    # 2. 레버리지
    if any(k in name_upper for k in ["레버리지", "LEVERAGE", "2X"]):
        if any(k in name_upper for k in ["단일종목", "SK하이닉스선물", "삼성전자선물"]):
            return "SINGLE_STOCK"
        return "LEVERAGED"

    # 3. 단일종목 ETF
    if any(k in name_upper for k in ["단일종목", "SINGLE"]):
        return "SINGLE_STOCK"

    # 4. 현금성 / 단기금리형 (MMF)
    if any(k in name_upper for k in ["MMF", "KOFR", "SOFR", "CD금리", "파킹", "금리액티브", "단기채권액티브"]):
        return "MONEY_MARKET"

    # 5. 채권 / 금리형
    if any(k in name_upper for k in ["채권", "국채", "회사채", "통화", "금리", "미국30년", "10년국채"]):
        return "BOND_RATE"

    # 6. 원자재 / 상품
    if any(k in name_upper for k in ["원유", "WTI", "금선물", "골드", "은선물", "구리", "농산물", "원자재"]):
        return "COMMODITY"

    # 7. 섹터 & 테마
    if any(k in name_upper for k in [
        "반도체", "2차전지", "AI", "바이오", "헬스케어", "자동차", "조선", "방산",
        "테크", "플랫폼", "로봇", "빅테크", "우주", "전력", "신재생", "원자력", "소부장",
        "IT", "미디어", "게임", "화장품", "소비재", "금융", "고배당", "주주환원"
    ]):
        return "SECTOR_THEME"

    # 8. 대표 지수형 (KOSPI 200, KOSDAQ 150, S&P500, NASDAQ100 등)
    if any(k in name_upper for k in ["200", "150", "S&P500", "나스닥100", "NASDAQ", "KOSPI", "KOSDAQ", "MSCI"]):
        return "PLAIN_EQUITY"

    return "OTHER"


def analyze_quant_candidate(cand: Dict[str, Any]) -> Dict[str, Any]:
    """
    단일 Stage 3 후보에 대해 기존 Quant 엔진(FFCS, technical, bollinger, TODAY ACTION)을 재사용하여
    SHORT / MID 추천 등급 및 Flag 산출
    """
    ticker = cand.get("ticker", "")
    name = cand.get("name", "")
    asset_type = cand.get("asset_type", "STOCK")
    
    etf_type = classify_etf_type(name) if asset_type == "ETF" else None

    # 데이터 미비 종목 예외 처리
    if not cand.get("data_available", False) or cand.get("flow_pattern") == "DATA_INSUFFICIENT":
        return {
            **cand,
            "etf_type": etf_type,
            "ffcs": 50.0,
            "fcs": "데이터 부족",
            "today_action": "HOLD",
            "today_action_desc": "수급/가격 데이터 부족으로 관망",
            "rsi": 50.0,
            "rmi": 50.0,
            "mfi": 50.0,
            "bollinger_status": "MID_BAND",
            "ma60": None,
            "ma120": None,
            "trend_6m": 0.0,
            "short_grade": "EXCLUDE",
            "short_reasons": ["수급 데이터 부족으로 단기 추천 제외"],
            "mid_grade": "EXCLUDE",
            "mid_reasons": ["수급 데이터 부족으로 중기 추천 제외"],
            "confidence": "LOW",
            "trend_up": False,
            "overheated": False,
            "non_overheated_uptrend": False,
            "pullback_candidate": False
        }

    # 1. 차트/가격 데이터 수집 (collector 기존 fetch_stock_chart_analysis 재사용 + 캐시 적용)
    try:
        chart_res = _get_cached_chart_analysis(ticker, timeframe='day')
    except Exception as e:
        logger.warning(f"[QuantEngine] Chart fetch exception for {name}({ticker}): {e}")
        chart_res = None

    if not chart_res or chart_res.get("status") != "success" or not chart_res.get("closes"):
        return {
            **cand,
            "etf_type": etf_type,
            "ffcs": 50.0,
            "fcs": "데이터 부족",
            "today_action": "HOLD",
            "today_action_desc": "차트 데이터 수집 실패",
            "rsi": 50.0,
            "rmi": 50.0,
            "mfi": 50.0,
            "bollinger_status": "MID_BAND",
            "ma60": None,
            "ma120": None,
            "trend_6m": 0.0,
            "short_grade": "EXCLUDE",
            "short_reasons": ["가격 차트 데이터 수집 실패"],
            "mid_grade": "EXCLUDE",
            "mid_reasons": ["가격 차트 데이터 수집 실패"],
            "confidence": "LOW",
            "trend_up": False,
            "overheated": False,
            "non_overheated_uptrend": False,
            "pullback_candidate": False
        }

    closes = chart_res.get("closes", [])
    volumes = chart_res.get("volumes", [])
    mfi_list = chart_res.get("mfi", [])
    rmi_list = chart_res.get("rmi", [])
    dates = chart_res.get("dates", [])

    close_latest = float(closes[-1])
    rsi_latest = float(chart_res.get("rsi", 50.0)) if "rsi" in chart_res else 50.0
    rmi_latest = float(rmi_list[-1]) if rmi_list else 50.0
    mfi_latest = float(mfi_list[-1]) if mfi_list else 50.0

    # pandas DataFrame 구축 (기존 technical/timing/decision 엔진 재사용용)
    df_chart = pd.DataFrame({
        "date": dates,
        "close_price": closes,
        "open_price": closes,
        "high_price": closes,
        "low_price": closes,
        "volume": volumes,
        "trading_value": [c * v for c, v in zip(closes, volumes)]
    })

    close_series = df_chart["close_price"]

    # 2. 기존 기술지표 계산 재사용 (technical_engine & timing_engine)
    tech_res = calculate_technical_indicators(df_chart)
    bollinger_res = calculate_bollinger_bands(close_series, window=20, num_std=2.0)

    rsi_latest = float(tech_res.get("rsi", rsi_latest))

    # 볼린저 밴드 이격 위치
    b_upper = float(bollinger_res.get("upper", close_latest * 1.2))
    b_lower = float(bollinger_res.get("lower", close_latest * 0.8))
    b_middle = float(bollinger_res.get("middle", close_latest))

    if close_latest >= b_upper * 1.01:
        bollinger_status = "ABOVE_UPPER"
    elif close_latest >= b_upper * 0.98:
        bollinger_status = "UPPER_BAND"
    elif close_latest <= b_lower * 0.99:
        bollinger_status = "BELOW_LOWER"
    elif close_latest <= b_lower * 1.02:
        bollinger_status = "LOWER_BAND"
    else:
        bollinger_status = "MID_BAND"

    # 3. 이동평균선 (MA60, MA120) 및 6개월 추세 계산
    ma60_val = float(tech_res.get("ma60", close_latest))
    if len(close_series) >= 120:
        ma120_val = float(close_series.rolling(120).mean().iloc[-1])
    else:
        ma120_val = ma60_val

    price_6m_ago = float(closes[-min(120, len(closes))])
    trend_6m = round(((close_latest - price_6m_ago) / price_6m_ago) * 100, 2) if price_6m_ago > 0 else 0.0

    # 4. 기존 수급 FFCS 및 TODAY ACTION 계산 (flow_engine & decision_engine)
    # Stage 2 수급 df 가 존재하면 사용, 없으면 mock 생성
    try:
        flow_raw = get_stock_flow_data(ticker, min_days=20)
        flow_df = flow_raw.get("df") if flow_raw and flow_raw.get("data_available") else None
    except Exception:
        flow_df = None

    if flow_df is not None and not flow_df.empty:
        period_analysis = analyze_period_flows(flow_df)
        ffcs_res = calculate_ffcs(flow_df, period_analysis)
        ffcs_score = round(float(ffcs_res.get("score", 50.0)), 1)
        fcs_stage = ffcs_res.get("stage", "관망")
    else:
        ffcs_score = 50.0
        fcs_stage = cand.get("flow_tier", "TIER_C")
        period_analysis = {"foreign": cand.get("foreign", {}), "institution": cand.get("institution", {})}

    # Decision Engine (TODAY ACTION)
    flow_info_for_decision = {
        "ffcs_score": ffcs_score,
        "foreign_direction": cand.get("foreign", {}).get("5d", {}).get("direction", "중립"),
        "institution_direction": cand.get("institution", {}).get("5d", {}).get("direction", "중립"),
        "concurrency": {
            "code": "BOTH_BUY" if cand.get("flow_pattern") == "JOINT_BUY" else "NEUTRAL",
            "description": "쌍끌이 순매수" if cand.get("flow_pattern") == "JOINT_BUY" else "수급 관망"
        }
    }

    buy_info = calculate_buy_score(flow_info_for_decision, tech_res)
    sell_info = calculate_sell_score(flow_info_for_decision, tech_res)
    water_info = calculate_watering_score(flow_info_for_decision, tech_res)
    decision_res = make_final_decision(buy_info, sell_info, water_info, flow_info_for_decision, tech_res)

    today_action = decision_res.get("decision", "HOLD")
    today_action_desc = decision_res.get("decision_desc", "관망")

    # 5. 비과열 상승추세 및 눌림목 Flag 계산 (Section 8 & 9)
    trend_up = (ma60_val >= ma120_val * 0.97) and (close_latest >= ma60_val * 0.96) and (trend_6m > -3.0)
    overheated = (rsi_latest >= 70.0) or (rmi_latest >= 72.0) or (mfi_latest >= 75.0) or (close_latest >= b_upper * 1.02)
    non_overheated_uptrend = (trend_up is True and overheated is False)

    # 눌림목 조건: 중기 상승추세 유지 + 최근 5일 조정/안정 + 과열 해소 + 수급 양호
    recent_5d_ret = ((close_latest - closes[-min(5, len(closes))]) / closes[-min(5, len(closes))]) * 100 if len(closes) >= 5 else 0.0
    pullback_candidate = (
        trend_up is True and
        overheated is False and
        cand.get("flow_pattern") != "DETERIORATING" and
        cand.get("flow_tier") in ["TIER_A", "TIER_B"] and
        (-6.0 <= recent_5d_ret <= 2.5) and
        (rsi_latest <= 62.0)
    )

    # 6. SHORT (단기 3~10일) 정밀 추천 평가 (Section 6)
    short_grade = "WATCH"
    short_reasons = []

    flow_p = cand.get("flow_pattern", "MIXED")
    flow_t = cand.get("flow_tier", "TIER_C")

    if flow_p == "DETERIORATING" or rsi_latest >= 75.0:
        short_grade = "EXCLUDE"
        if flow_p == "DETERIORATING":
            short_reasons.append("최근 단기 수급 악화 유출")
        if rsi_latest >= 75.0:
            short_reasons.append(f"RSI {rsi_latest} 기술적 과열 경고")
    elif flow_t == "TIER_A" and today_action in ["BUY", "AVERAGE"] and not overheated and rsi_latest <= 68.0:
        short_grade = "STRONG_CANDIDATE"
        short_reasons.append(f"수급 1순위({flow_p}) + TODAY ACTION({today_action}) 단기 긍정 부합")
    elif flow_t in ["TIER_A", "TIER_B"] and not overheated and flow_p != "DETERIORATING":
        short_grade = "CANDIDATE"
        short_reasons.append("단기 수급 개선 및 기술적 비과열 구간 유지")
    else:
        short_grade = "WATCH"
        short_reasons.append("단기 수급 혼조 또는 모멘텀 관망 필요")

    # 7. MID (중기 3~8주) 정밀 추천 평가 (Section 7)
    mid_grade = "WATCH"
    mid_reasons = []

    # 역배열/하락추세 또는 과열 시 STRONG_CANDIDATE 금지
    if trend_6m < -15.0 or (ma60_val < ma120_val * 0.90) or flow_p == "DETERIORATING":
        mid_grade = "EXCLUDE"
        if trend_6m < -15.0:
            mid_reasons.append(f"6개월 추세 하락({trend_6m}%) 위험")
        if flow_p == "DETERIORATING":
            mid_reasons.append("중기 수급 이탈 및 악화")
    elif flow_t == "TIER_A" and trend_up and not overheated and rsi_latest <= 65.0:
        mid_grade = "STRONG_CANDIDATE"
        if ma60_val >= ma120_val:
            mid_reasons.append("중기 매집 수급 + 60/120일선 정배열 상승 구조 충족")
        else:
            mid_reasons.append(f"중기 매집 수급 + 60일선 지지 및 6개월 추세 상승(+{trend_6m}%)")
    elif flow_t in ["TIER_A", "TIER_B"] and close_latest >= ma60_val * 0.95 and flow_p != "DETERIORATING":
        mid_grade = "CANDIDATE"
        mid_reasons.append("중기 수급 유입 및 60일선 지지 구조 형성")
    else:
        mid_grade = "WATCH"
        mid_reasons.append("중기 추세 방향성 및 수급 지속성 관찰 필요")

    # 8. Confidence 연산 (데이터 지표 합의도)
    if (short_grade == "STRONG_CANDIDATE" or mid_grade == "STRONG_CANDIDATE") and non_overheated_uptrend:
        confidence = "HIGH"
    elif short_grade in ["STRONG_CANDIDATE", "CANDIDATE"] or mid_grade in ["STRONG_CANDIDATE", "CANDIDATE"]:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        **cand,
        "etf_type": etf_type,
        "ffcs": ffcs_score,
        "fcs": fcs_stage,
        "today_action": today_action,
        "today_action_desc": today_action_desc,
        "rsi": rsi_latest,
        "rmi": rmi_latest,
        "mfi": mfi_latest,
        "bollinger_status": bollinger_status,
        "ma60": round(ma60_val, 1) if ma60_val else None,
        "ma120": round(ma120_val, 1) if ma120_val else None,
        "trend_6m": trend_6m,
        "short_grade": short_grade,
        "short_reasons": short_reasons,
        "mid_grade": mid_grade,
        "mid_reasons": mid_reasons,
        "confidence": confidence,
        "trend_up": trend_up,
        "overheated": overheated,
        "non_overheated_uptrend": non_overheated_uptrend,
        "pullback_candidate": pullback_candidate
    }


def analyze_candidates_quant_parallel(
    candidates: List[Dict[str, Any]],
    max_workers: int = 10
) -> List[Dict[str, Any]]:
    """
    Stage 3 후보군에 대해 ThreadPoolExecutor(max_workers=10) 기반 병렬 차트/Quant 분석 수행
    """
    results = []
    if not candidates:
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cand = {executor.submit(analyze_quant_candidate, cand): cand for cand in candidates}
        for future in concurrent.futures.as_completed(future_to_cand):
            cand = future_to_cand[future]
            try:
                res = future.result(timeout=10.0)
                results.append(res)
            except concurrent.futures.TimeoutError:
                logger.warning(f"[QuantEngine] Timeout analyzing quant for {cand.get('name')}({cand.get('ticker')})")
                results.append(analyze_quant_candidate({**cand, "data_available": False}))
            except Exception as e:
                logger.error(f"[QuantEngine] Exception analyzing quant for {cand.get('name')}({cand.get('ticker')}): {e}")
                results.append(analyze_quant_candidate({**cand, "data_available": False}))

    # 원래 후보 순서 보존
    ticker_to_res = {r["ticker"]: r for r in results}
    return [ticker_to_res.get(c["ticker"], analyze_quant_candidate(c)) for c in candidates]


def rank_quant_candidates(
    analyzed_list: List[Dict[str, Any]],
    recommend_target: str = "SHORT",
    max_count: int = 10,
    is_etf: bool = False
) -> List[Dict[str, Any]]:
    """
    Grade, 수급 Tier, FFCS, 기술적 합의, 유동성에 기반한 Deterministic 순위 정렬
    - recommend_target: "SHORT" 또는 "MID"
    - is_etf=True 일 때 MID 기본 추천 Pool에서 레버리지/인버스/단일종목/채권/MMF 제외
    """
    grade_weight = {"STRONG_CANDIDATE": 4, "CANDIDATE": 3, "WATCH": 2, "EXCLUDE": 1}
    tier_weight = {"TIER_A": 3, "TIER_B": 2, "TIER_C": 1, "TIER_D": 0}
    action_weight = {"BUY": 3, "AVERAGE": 2, "HOLD": 1, "TAKE_PROFIT": 0, "REDUCE": -1}

    filtered = []
    for c in analyzed_list:
        if not c.get("data_available", True):
            continue
        
        # ETF MID 기본 추천 제외 규칙 (Section 10)
        if is_etf and recommend_target == "MID":
            etf_type = c.get("etf_type", "")
            if etf_type in ["LEVERAGED", "INVERSE", "SINGLE_STOCK", "BOND_RATE", "MONEY_MARKET"]:
                continue

        grade_key = "short_grade" if recommend_target == "SHORT" else "mid_grade"
        g_val = c.get(grade_key, "EXCLUDE")
        
        # EXCLUDE 등급은 Top 추천 후보에서 제외
        if g_val == "EXCLUDE":
            continue

        filtered.append(c)

    def _sort_key(c):
        grade_key = "short_grade" if recommend_target == "SHORT" else "mid_grade"
        g_rank = grade_weight.get(c.get(grade_key, "EXCLUDE"), 0)
        t_rank = tier_weight.get(c.get("flow_tier", "TIER_D"), 0)
        a_rank = action_weight.get(c.get("today_action", "HOLD"), 0)
        ffcs = c.get("ffcs", 50.0)
        amount = c.get("amount", 0.0)
        trend_flag = 1 if c.get("trend_up") else 0
        non_overheated = 1 if c.get("non_overheated_uptrend") else 0

        if recommend_target == "SHORT":
            return (g_rank, t_rank, a_rank, non_overheated, ffcs, amount)
        else:
            return (g_rank, t_rank, trend_flag, non_overheated, ffcs, amount)

    sorted_list = sorted(filtered, key=_sort_key, reverse=True)
    return sorted_list[:max_count]


def run_quant_recommendation(
    stock_stage1_count: int = 100,
    etf_stage1_count: int = 50,
    max_workers: int = 10
) -> Dict[str, Any]:
    """
    Phase 4 단기·중기 Quant 정밀 추천 메인 실행 함수
    Stage 1 -> Stage 2 수급 스크리너 -> Stage 3 Quant 정밀 평가
    """
    t_start = time.time()

    # 1. Stage 1 & Stage 2 수급 스크리닝 (Stage 3 후보 확보)
    t0_flow = time.time()
    flow_res = run_flow_screener(
        stock_stage1_count=stock_stage1_count,
        etf_stage1_count=etf_stage1_count,
        max_workers=max_workers
    )
    t_flow_elapsed = time.time() - t0_flow

    stock_stage3_input = flow_res["stock_results"]["stage3_candidates"]
    etf_stage3_input = flow_res["etf_results"]["stage3_candidates"]

    # 2. Stage 3 STOCK Quant 분석 (병렬)
    t0_stock = time.time()
    stock_quant_analyzed = analyze_candidates_quant_parallel(stock_stage3_input, max_workers=max_workers)
    t_stock_elapsed = time.time() - t0_stock

    # 3. Stage 3 ETF Quant 분석 (병렬)
    t0_etf = time.time()
    etf_quant_analyzed = analyze_candidates_quant_parallel(etf_stage3_input, max_workers=max_workers)
    t_etf_elapsed = time.time() - t0_etf

    # 4. Deterministic 순위 선정 (Top 10 SHORT / Top 10 MID)
    stock_short_top = rank_quant_candidates(stock_quant_analyzed, recommend_target="SHORT", max_count=10, is_etf=False)
    stock_mid_top = rank_quant_candidates(stock_quant_analyzed, recommend_target="MID", max_count=10, is_etf=False)

    etf_short_top = rank_quant_candidates(etf_quant_analyzed, recommend_target="SHORT", max_count=10, is_etf=True)
    etf_mid_top = rank_quant_candidates(etf_quant_analyzed, recommend_target="MID", max_count=10, is_etf=True)

    # 5. 통계 및 요약
    def _summarize_stats(analyzed_list):
        return {
            "total_input": len(analyzed_list),
            "short_strong": sum(1 for c in analyzed_list if c.get("short_grade") == "STRONG_CANDIDATE"),
            "short_candidate": sum(1 for c in analyzed_list if c.get("short_grade") == "CANDIDATE"),
            "short_watch": sum(1 for c in analyzed_list if c.get("short_grade") == "WATCH"),
            "short_exclude": sum(1 for c in analyzed_list if c.get("short_grade") == "EXCLUDE"),
            "mid_strong": sum(1 for c in analyzed_list if c.get("mid_grade") == "STRONG_CANDIDATE"),
            "mid_candidate": sum(1 for c in analyzed_list if c.get("mid_grade") == "CANDIDATE"),
            "mid_watch": sum(1 for c in analyzed_list if c.get("mid_grade") == "WATCH"),
            "mid_exclude": sum(1 for c in analyzed_list if c.get("mid_grade") == "EXCLUDE"),
            "non_overheated_uptrend_cnt": sum(1 for c in analyzed_list if c.get("non_overheated_uptrend")),
            "pullback_candidate_cnt": sum(1 for c in analyzed_list if c.get("pullback_candidate"))
        }

    etf_type_counts = {}
    for c in etf_quant_analyzed:
        t = c.get("etf_type", "OTHER")
        etf_type_counts[t] = etf_type_counts.get(t, 0) + 1

    total_elapsed = time.time() - t_start

    return {
        "status": "success",
        "total_elapsed_sec": round(total_elapsed, 2),
        "flow_screener_stats": {
            "stock_stats": flow_res["stock_results"]["stats"],
            "etf_stats": flow_res["etf_results"]["stats"]
        },
        "stage_times": {
            "stage1_stage2_flow_sec": round(t_flow_elapsed, 2),
            "stock_quant_sec": round(t_stock_elapsed, 2),
            "etf_quant_sec": round(t_etf_elapsed, 2)
        },
        "stock_results": {
            "stats": _summarize_stats(stock_quant_analyzed),
            "short_top": stock_short_top,
            "mid_top": stock_mid_top,
            "all_quant_analyzed": stock_quant_analyzed
        },
        "etf_results": {
            "stats": _summarize_stats(etf_quant_analyzed),
            "etf_type_counts": etf_type_counts,
            "short_top": etf_short_top,
            "mid_top": etf_mid_top,
            "all_quant_analyzed": etf_quant_analyzed
        }
    }
