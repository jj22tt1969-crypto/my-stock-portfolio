import logging
from typing import Dict, Any, Optional, Union, List, Tuple

from backend.engine.fundamental_engine import get_fundamental_context
from backend.engine.fundamental_state_engine import get_fundamental_state

logger = logging.getLogger(__name__)


def compute_valuation_consistency(
    per: Optional[float],
    pbr: Optional[float],
    roe: Optional[float]
) -> Dict[str, Any]:
    """
    PER / PBR / ROE의 회계적 항등식(PBR = PER * ROE / 100) 정합성을 검증합니다.
    
    [엄격한 원칙 - F8B-R 준수]
    1. 평가 가능 조건: PER > 0, PBR > 0, ROE > 0 모두 만족해야 함.
       그 외의 경우(결측치, 음수 PER, 음수 ROE) valuation_evaluable = False.
    2. 음수 PER/ROE를 저평가 신호로 절대 사용하지 않음.
    3. identity_gap_pct 자체를 가치평가(저평가/고평가) 점수나 가점으로 사용 절대 금지!
       회계기간/산식/보통주 차이를 확인하는 Data Quality 및 Consistency 참고 정보로만 사용.
    """
    is_evaluable = (
        per is not None and per > 0 and
        pbr is not None and pbr > 0 and
        roe is not None and roe > 0
    )

    if not is_evaluable:
        return {
            "valuation_evaluable": False,
            "actual_pbr": pbr,
            "implied_pbr": None,
            "identity_gap_pct": None,
            "consistency_status": "NOT_EVALUABLE",
            "consistency_note": "PER, PBR, ROE 중 결측치 또는 비양수(적자/음수) 값이 존재하여 정합성 평가 불가"
        }

    # PBR = PER * ROE / 100
    implied_pbr = round((per * roe) / 100.0, 4)
    actual_pbr = pbr

    if actual_pbr > 0:
        gap_pct = round(abs(actual_pbr - implied_pbr) / actual_pbr * 100.0, 2)
    else:
        gap_pct = None

    if gap_pct is not None and gap_pct <= 20.0:
        consistency_status = "CONSISTENT"
        consistency_note = "PER*ROE와 PBR 지표가 회계적으로 높은 정합성을 보임 (오차 20% 이내)"
    elif gap_pct is not None and gap_pct <= 40.0:
        consistency_status = "MODERATE_GAP"
        consistency_note = "주가 기준일시, 보통주/우선주 희석 또는 지배주주 순이익 차이로 인한 완만한 격차 존재"
    else:
        consistency_status = "DIVERGENT"
        consistency_note = "회계 결산 시점 차이 또는 특수 지분 구조로 인한 유의미한 수치 격차 존재"

    return {
        "valuation_evaluable": True,
        "actual_pbr": actual_pbr,
        "implied_pbr": implied_pbr,
        "identity_gap_pct": gap_pct,
        "consistency_status": consistency_status,
        "consistency_note": consistency_note
    }


def _calculate_median(values: List[float]) -> Optional[float]:
    """리스트의 중앙값을 산출합니다."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return float((s[mid - 1] + s[mid]) / 2.0)


def compute_metric_own_history(
    metric_name: str,
    latest_val: Optional[float],
    prior_vals: List[Optional[float]]
) -> Dict[str, Any]:
    """
    PER 또는 PBR의 자기 역사(Own-History) 비교 컨텍스트를 산출합니다.
    
    [F8C-1 엄격한 안전 규칙]
    - annual actual만 사용 (Consensus 사용 절대 금지).
    - latest 값을 prior median 계산에 절대 포함하지 않음 (미래/현재 누수 방지).
    - 양수 값만 history 비교에 사용 (음수/0 제외).
    - 과거 양수 Actual이 최소 2개 이상일 때만 history_available=True.
    - '저평가/고평가/싸다/비싸다/적정' 주관적 판정 단어 일체 금지.
    """
    # 1. 양수 값만 필터링 (음수/0/None 제외)
    prior_positives: List[float] = [
        round(float(v), 4) for v in prior_vals
        if v is not None and isinstance(v, (int, float)) and v > 0
    ]

    has_enough_history = (len(prior_positives) >= 2)
    is_current_valid = (latest_val is not None and isinstance(latest_val, (int, float)) and latest_val > 0)

    key_current = f"current_{metric_name}"

    if not has_enough_history or not is_current_valid:
        prior_med = round(_calculate_median(prior_positives), 4) if prior_positives else None
        prior_min = min(prior_positives) if prior_positives else None
        prior_max = max(prior_positives) if prior_positives else None
        
        return {
            key_current: latest_val,
            "prior_positive_values": prior_positives,
            "prior_median": prior_med,
            "prior_min": prior_min,
            "prior_max": prior_max,
            "vs_prior_median_pct": None,
            "position": "NOT_EVALUABLE",
            "history_available": False,
            "note": "이전 2개년 이상 양수 Actual 지표 부재 또는 현재 지표 비양수로 자체 역사 비교 불가"
        }

    # 2. Prior Median, Min, Max 산출
    prior_med = round(_calculate_median(prior_positives), 4)
    prior_min = min(prior_positives)
    prior_max = max(prior_positives)

    # 3. vs prior median pct 산출
    if prior_med and prior_med > 0:
        diff_pct = round(((latest_val - prior_med) / prior_med) * 100.0, 2)
    else:
        diff_pct = None

    # 4. 상대적 위치 판정 (중립 밴드 ±5.0%, 주관적 단어 배제)
    if diff_pct is None:
        position = "NOT_EVALUABLE"
    elif diff_pct < -5.0:
        position = "BELOW_PRIOR_MEDIAN"
    elif diff_pct > 5.0:
        position = "ABOVE_PRIOR_MEDIAN"
    else:
        position = "NEAR_PRIOR_MEDIAN"

    return {
        key_current: latest_val,
        "prior_positive_values": prior_positives,
        "prior_median": prior_med,
        "prior_min": prior_min,
        "prior_max": prior_max,
        "vs_prior_median_pct": diff_pct,
        "position": position,
        "history_available": True,
        "note": f"과거 {len(prior_positives)}개년 양수 Actual 중앙값({prior_med}) 대비 현재({latest_val})의 상대적 위치"
    }


def compute_roe_own_history(
    latest_roe: Optional[float],
    prior_roes: List[Optional[float]]
) -> Dict[str, Any]:
    """
    ROE의 자기 역사(Own-History) 추세 컨텍스트를 산출합니다.
    
    [F8C-1 규칙 준수]
    - raw history 보존 (양/음수 포함).
    - 직전 Actual 대비 변동 방향성(IMPROVING / DECLINING / FLAT / NOT_COMPARABLE)만 산출.
    - ROE를 PER/PBR과 중복 점수화하지 않음.
    """
    # 과거 양/음수 포함 raw 보존
    valid_priors = [
        round(float(v), 2) for v in prior_roes
        if v is not None and isinstance(v, (int, float))
    ]
    previous_roe = valid_priors[-1] if valid_priors else None

    if latest_roe is None or previous_roe is None:
        return {
            "latest_roe": latest_roe,
            "previous_roe": previous_roe,
            "roe_change_pct_point": None,
            "direction": "NOT_COMPARABLE",
            "raw_history": valid_priors,
            "note": "비교 가능한 직전 Actual ROE 부재로 추세 비교 불가"
        }

    # 퍼센트포인트(%p) 단순 차이
    diff_pp = round(latest_roe - previous_roe, 2)

    # 방향성 판정 (변동폭 ±0.5%p 기준)
    if diff_pp > 0.5:
        direction = "IMPROVING"
    elif diff_pp < -0.5:
        direction = "DECLINING"
    else:
        direction = "FLAT"

    return {
        "latest_roe": latest_roe,
        "previous_roe": previous_roe,
        "roe_change_pct_point": diff_pp,
        "direction": direction,
        "raw_history": valid_priors,
        "note": f"직전 Actual 결산({previous_roe}%) 대비 최신 Actual({latest_roe}%) ROE 변동: {diff_pp:+0.2f}%p"
    }


def extract_own_history_valuation_context(
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    fundamental_context의 annual actual 시계열로부터
    PER, PBR, ROE의 자기 역사(Own-History) 비교 컨텍스트를 추출합니다.
    """
    clean_ticker = str(context.get("ticker", "")).strip().zfill(6)
    from backend.engine.fundamental_engine import get_fundamental_snapshot_cache
    cache = get_fundamental_snapshot_cache()
    stock_record = cache.get("stocks", {}).get(clean_ticker) if cache else None
    
    annual_data = stock_record.get("annual", {}) if stock_record else {}
    periods: List[Dict[str, Any]] = annual_data.get("periods") or []
    metrics: Dict[str, Any] = annual_data.get("metrics") or {}

    # 1. Actual 결산 기간만 필터링 (is_consensus == False, key 오름차순 정렬)
    actual_periods = [
        p for p in periods
        if isinstance(p, dict) and not p.get("is_consensus", False)
    ]
    actual_periods = sorted(actual_periods, key=lambda x: str(x.get("key", "")))

    if not actual_periods:
        empty_per = compute_metric_own_history("per", None, [])
        empty_pbr = compute_metric_own_history("pbr", None, [])
        empty_roe = compute_roe_own_history(None, [])
        return {
            "per_history": empty_per,
            "pbr_history": empty_pbr,
            "roe_history": empty_roe,
            "history_available": False,
            "actual_period_count": 0,
            "note": "실제 결산 Actual 시계열 데이터 부재"
        }

    # 2. Latest Actual과 Prior Actuals 엄격 분리
    latest_period = actual_periods[-1]
    prior_periods = actual_periods[:-1]

    latest_key = str(latest_period.get("key", ""))
    prior_keys = [str(p.get("key", "")) for p in prior_periods]

    # 3. 각 지표별 값 추출
    per_values_map = (metrics.get("per") or {}).get("values") or {}
    pbr_values_map = (metrics.get("pbr") or {}).get("values") or {}
    roe_values_map = (metrics.get("roe") or {}).get("values") or {}

    latest_per = per_values_map.get(latest_key)
    prior_pers = [per_values_map.get(k) for k in prior_keys]

    latest_pbr = pbr_values_map.get(latest_key)
    prior_pbrs = [pbr_values_map.get(k) for k in prior_keys]

    latest_roe = roe_values_map.get(latest_key)
    prior_roes = [roe_values_map.get(k) for k in prior_keys]

    # 4. 개별 Own-History 컨텍스트 산출
    per_history = compute_metric_own_history("per", latest_per, prior_pers)
    pbr_history = compute_metric_own_history("pbr", latest_pbr, prior_pbrs)
    roe_history = compute_roe_own_history(latest_roe, prior_roes)

    has_any_history = bool(
        per_history.get("history_available", False) or
        pbr_history.get("history_available", False)
    )

    return {
        "per_history": per_history,
        "pbr_history": pbr_history,
        "roe_history": roe_history,
        "history_available": has_any_history,
        "actual_period_count": len(actual_periods),
        "latest_fiscal_period": latest_period.get("fiscal_period"),
        "prior_fiscal_periods": [p.get("fiscal_period") for p in prior_periods],
        "note": "동일 기업의 과거 Actual 실적 지표 대비 현재 밸류에이션 위치 비교 (업종/Peer 배제)"
    }


def calculate_quality_shadow_score(
    earnings_ctx: Dict[str, Any],
    growth_ctx: Dict[str, Any],
    prof_ctx: Dict[str, Any],
    data_state: str,
    asset_type: str
) -> Dict[str, Any]:
    """
    재무 품질(Financial Quality) 전용 객관적 팩트 기반 Shadow Score를 산출합니다. (0~100점)
    
    [F8B-R 엄격한 분리 및 안전 규칙]
    - earnings, profitability, growth 3대 팩트만 사용.
    - PER, PBR, ROE 3중 가중 절대 금지.
    - identity consistency를 가치평가 점수로 절대 사용 금지.
    - 종목명이나 키워드로 업종을 추측하여 가감점 부여 금지.
    - 적자기업, NO_FINANCE_DATA, ETF는 안전하게 점수 산출 배제 (억지 점수 생성 금지).
    - 기존 Decision에 절대 미반영 (Shadow 전용).
    """
    # 1. 안전 관문 (Ineligibility Gates)
    if asset_type == "ETF" or data_state == "NOT_APPLICABLE":
        return {
            "quality_shadow_score_available": False,
            "quality_shadow_score": None,
            "breakdown": None,
            "reasons": ["ETF 종목은 기업 고유 재무제표가 성립되지 않아 재무품질 스코어 산출 대상에서 제외됩니다."],
            "ineligibility_reason": "ETF_NOT_APPLICABLE"
        }

    if data_state != "SUCCESS":
        return {
            "quality_shadow_score_available": False,
            "quality_shadow_score": None,
            "breakdown": None,
            "reasons": ["스냅샷 재무제표 미제공(스팩/인프라/미제공) 종목으로 스코어 산출이 불가합니다."],
            "ineligibility_reason": "NO_FINANCE_DATA"
        }

    # 적자 기업 여부 확인
    e_status = earnings_ctx.get("status", "UNKNOWN")
    if e_status in ["OPERATING_LOSS", "NET_LOSS"]:
        return {
            "quality_shadow_score_available": False,
            "quality_shadow_score": None,
            "breakdown": None,
            "reasons": [f"영업이익 또는 순이익 적자({e_status}) 상태로, 안전한 선형 재무품질 점수 산출 대상에서 제외됩니다."],
            "ineligibility_reason": "UNPROFITABLE_DEFICIT"
        }

    # 2. 모든 관문을 통과한 정상 흑자 기업의 팩트 기반 재무품질 스코어링 (100점 만점)
    score = 0.0
    breakdown = {}
    reasons = []

    # 1) Earnings Quality (최대 40점)
    op = earnings_ctx.get("operating_profit")
    np_val = earnings_ctx.get("net_profit")
    op_margin_sign = prof_ctx.get("operating_margin_sign", "UNKNOWN")

    earnings_score = 0.0
    if op is not None and op > 0 and np_val is not None and np_val > 0:
        earnings_score += 25.0
        reasons.append("영업이익 및 당기순이익 동시 흑자 달성 (+25점)")
    
    if op_margin_sign == "POSITIVE":
        earnings_score += 15.0
        reasons.append("영업이익률 양수 마진 기록 (+15점)")
    
    breakdown["earnings_quality"] = {"score": earnings_score, "max": 40.0}
    score += earnings_score

    # 2) Growth Momentum (최대 35점)
    growth_score = 0.0
    op_growth = growth_ctx.get("operating_profit", {})
    rev_growth = growth_ctx.get("revenue", {})

    if op_growth.get("direction") == "INCREASE" or op_growth.get("status") == "TURNAROUND":
        growth_score += 20.0
        reasons.append("영업이익 전년 대비 증가/흑자전환 (+20점)")

    if rev_growth.get("direction") == "INCREASE":
        growth_score += 15.0
        reasons.append("매출액 전년 대비 증가 성장 (+15점)")

    breakdown["growth_momentum"] = {"score": growth_score, "max": 35.0}
    score += growth_score

    # 3) Capital Profitability (최대 25점)
    prof_score = 0.0
    roe_sign = prof_ctx.get("roe_sign", "UNKNOWN")
    net_margin_sign = prof_ctx.get("net_margin_sign", "UNKNOWN")

    if roe_sign == "POSITIVE":
        prof_score += 15.0
        reasons.append("자기자본이익률(ROE) 양수 창출 (+15점)")

    if net_margin_sign == "POSITIVE":
        prof_score += 10.0
        reasons.append("순이익률 양수 유지 (+10점)")

    breakdown["capital_profitability"] = {"score": prof_score, "max": 25.0}
    score += prof_score

    final_score = round(score, 1)

    return {
        "quality_shadow_score_available": True,
        "quality_shadow_score": final_score,
        "breakdown": breakdown,
        "reasons": reasons,
        "ineligibility_reason": None
    }


def get_fundamental_shadow_context(
    ticker_or_context_or_state: Union[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Q&A, Forward Test, TODAY ACTION이 공통으로 재사용할
    단일 Valuation / Fundamental Shadow Context를 반환합니다.

    [F8C-1 핵심 구현]
    1. Own-History Valuation Context 탑재:
       - 동일 기업의 과거 Actual 실적 지표 대비 현재 PER, PBR, ROE 상대 위치 비교.
       - 음수/0 배수 제외, 최소 2개년 이전 양수 Actual 확보 시에만 평가.
    2. 점수화 금지 원칙 준수:
       - valuation_score_available=False 유지.
       - combined_score_available=False 유지.
    3. 기존 Decision / Score / Formula 변경 없음 (완전한 Shadow 격리).
    """
    # 1. State 및 Context 확보
    if isinstance(ticker_or_context_or_state, str):
        ticker = ticker_or_context_or_state.strip().zfill(6)
        state = get_fundamental_state(ticker)
        context = get_fundamental_context(ticker)
    elif isinstance(ticker_or_context_or_state, dict):
        if "data_state" in ticker_or_context_or_state:
            state = ticker_or_context_or_state
            ticker = state.get("ticker", "")
            context = get_fundamental_context(ticker) if ticker else {}
        else:
            context = ticker_or_context_or_state
            ticker = context.get("ticker", "")
            state = get_fundamental_state(context)
    else:
        raise ValueError("Invalid input: must be ticker string or dictionary")

    name = state.get("name", ticker)
    market = state.get("market", "UNKNOWN")
    asset_type = state.get("asset_type", "STOCK")
    data_state = state.get("data_state", "NO_FINANCE_DATA")

    # 2. 하위 컨텍스트 파싱
    earnings_ctx = state.get("earnings_state", {})
    profitability = state.get("profitability", {})
    growth_ctx = state.get("growth", {})
    val_raw = state.get("valuation", {})
    bs_raw = state.get("balance_sheet", {})
    data_quality = state.get("data_quality", {})
    summary_flags = list(state.get("summary_flags", []))

    # Profitability Context
    prof_ctx = {
        "roe": profitability.get("roe", {}).get("value"),
        "roe_sign": profitability.get("roe", {}).get("sign", "UNKNOWN"),
        "operating_margin": profitability.get("operating_margin", {}).get("value"),
        "operating_margin_sign": profitability.get("operating_margin", {}).get("sign", "UNKNOWN"),
        "net_margin": profitability.get("net_margin", {}).get("value"),
        "net_margin_sign": profitability.get("net_margin", {}).get("sign", "UNKNOWN"),
    }

    # Valuation Context & PBR = PER * ROE 정합성
    per_val = val_raw.get("per")
    pbr_val = val_raw.get("pbr")
    roe_val = prof_ctx.get("roe")

    consistency_res = compute_valuation_consistency(per_val, pbr_val, roe_val)

    # Own-History Valuation Context 추출 (F8C-1)
    own_history = extract_own_history_valuation_context(context)

    val_ctx = {
        "per": per_val,
        "pbr": pbr_val,
        "roe": roe_val,
        "per_status": val_raw.get("per_status", "UNKNOWN"),
        "pbr_status": val_raw.get("pbr_status", "UNKNOWN"),
        "valuation_evaluable": consistency_res["valuation_evaluable"],
        "actual_pbr": consistency_res["actual_pbr"],
        "implied_pbr": consistency_res["implied_pbr"],
        "identity_gap_pct": consistency_res["identity_gap_pct"],
        "consistency_status": consistency_res["consistency_status"],
        "consistency_note": consistency_res["consistency_note"],
        # Own-History Valuation Context (F8C-1)
        "own_history": own_history,
        # Valuation 자체의 점수화는 미산출 유지
        "valuation_score_available": False,
        "valuation_score": None,
        "valuation_score_note": "업종 Peer 또는 Own-History 밴드 기준 부재로 밸류에이션 점수 미산출 (비교 Context만 제공)"
    }

    # Balance Sheet Context
    debt_ratio = bs_raw.get("debt_ratio")
    quick_ratio = bs_raw.get("quick_ratio")

    bs_ctx = {
        "debt_ratio": debt_ratio,
        "quick_ratio": quick_ratio,
        "sector_adjustment_available": False,
        "sector_adjustment_note": "전종목 표준 업종 분류 근거 부재로 업종 조정 미적용 (원시 수치만 보존)"
    }

    # 3. Quality Shadow Score 산출
    quality_card = calculate_quality_shadow_score(
        earnings_ctx=earnings_ctx,
        growth_ctx=growth_ctx,
        prof_ctx=prof_ctx,
        data_state=data_state,
        asset_type=asset_type
    )

    # 4. Combined Score (Valuation 근거 확보 전까지 생성 금지)
    combined_card = {
        "combined_score_available": False,
        "combined_score": None,
        "combined_score_note": "Valuation 근거 확보 전까지 종합 점수 생성 금지 (재무품질 점수와 밸류에이션 미결합)"
    }

    return {
        "ticker": ticker,
        "name": name,
        "market": market,
        "asset_type": asset_type,
        "data_state": data_state,
        "data_quality": data_quality,
        "earnings_context": earnings_ctx,
        "profitability_context": prof_ctx,
        "growth_context": growth_ctx,
        "valuation_context": val_ctx,
        "balance_sheet_context": bs_ctx,
        "summary_flags": summary_flags,
        "quality_shadow_score_card": quality_card,
        "combined_score_card": combined_card
    }
