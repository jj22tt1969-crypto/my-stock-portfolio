import pandas as pd
import numpy as np
from typing import Dict, Any, List

def analyze_smart_money_flow(investor_breakdown: Dict[str, Any], df: pd.DataFrame = None, asset_type: str = "STOCK") -> Dict[str, Any]:
    """
    큰손 수급 분석 엔진 (Smart Money Flow Engine) - 3차-G 보정 적용
    
    - 기관 Fallback 임의 0.70 승수 제거 -> 기관 세부 미확인 표출
    - ETF 수급 LP/AP 특성 반영 -> 확률적 표현 및 해석 주의 안내
    """

    is_etf = (asset_type and str(asset_type).upper() == "ETF")

    # 🛡️ 데이터 안전 예외 처리 (데이터 미제공 또는 빈 데이터일 경우 판단 보류)
    if not investor_breakdown or not investor_breakdown.get("available", False):
        return {
            "available": False,
            "is_detail_available": False,
            "is_etf": is_etf,
            "score": None,
            "signal_grade": "NONE",
            "signal_label": "데이터 부족 / 판단 보류",
            "signal_color": "#94a3b8",
            "reasons": ["세부 수급 데이터 수집 대기 중 (판단 보류)"],
            "summary": {}
        }

    daily = investor_breakdown.get("daily", [])
    if not daily or len(daily) < 3:
        return {
            "available": False,
            "is_detail_available": False,
            "is_etf": is_etf,
            "score": None,
            "signal_grade": "NONE",
            "signal_label": "데이터 부족 / 판단 보류",
            "signal_color": "#94a3b8",
            "reasons": ["최소 3거래일 이상의 세부 수급 데이터가 필요합니다."],
            "summary": {}
        }

    # 1. 투자자 주체별 가중치 정의 (세부 데이터용)
    WEIGHTS = {
        "foreign": 1.00,
        "pension": 0.90,
        "private_fund": 0.75,
        "investment_trust": 0.70,
        "financial_investment": 0.40,
        "individual": 0.00
    }

    reasons = []
    has_detail_flag = False

    # 2. 5일/10일/20일 기간별 가중 순매수 금액(억원) 연산
    def calc_weighted_smart_amount(sub_daily):
        total_smart = 0.0
        has_detail = False
        
        for r in sub_daily:
            frgn = r.get("foreign_amount") or 0.0
            pension = r.get("pension_amount")
            priv = r.get("private_fund_amount")
            inv_t = r.get("investment_trust_amount")
            fin_inv = r.get("financial_investment_amount")

            # 기관 세부 데이터가 하나라도 정상 수집된 경우
            if pension is not None or priv is not None or inv_t is not None or fin_inv is not None:
                has_detail = True
                p_val = (pension or 0.0) * WEIGHTS["pension"]
                pr_val = (priv or 0.0) * WEIGHTS["private_fund"]
                it_val = (inv_t or 0.0) * WEIGHTS["investment_trust"]
                fi_val = (fin_inv or 0.0) * WEIGHTS["financial_investment"]
                inst_sum = p_val + pr_val + it_val + fi_val
            else:
                # 3차-G 보정: 임의의 0.70 승수 전면 제거! (특정 기관 오인 방지)
                # 기관 전체 수급 금액을 특정 기관으로 합산하지 않고 0.0으로 둠
                inst_sum = 0.0

            day_smart = (frgn * WEIGHTS["foreign"]) + inst_sum
            total_smart += day_smart

        return total_smart, has_detail

    amt_5d, detail_5d = calc_weighted_smart_amount(daily[-5:])
    amt_10d, detail_10d = calc_weighted_smart_amount(daily[-10:])
    amt_20d, detail_20d = calc_weighted_smart_amount(daily[-20:])

    has_detail_flag = detail_5d or detail_10d or detail_20d

    if not has_detail_flag:
        reasons.append("기관 세부 수급 미확인 (기관 전체 수급 참조)")

    if is_etf:
        reasons.append("ETF 수급 특성상 LP/AP 설정·환매 및 차익거래 자금 포함 (해석 주의)")

    # 5/10/20일 총 거래대금(억원) 연산
    def calc_total_trading_val(sub_daily):
        val_sum = 0.0
        for r in sub_daily:
            cp = r.get("close_price", 0)
            val_sum += (cp * abs(r.get("institution_qty", 0) + r.get("individual_qty", 0))) / 100000000.0
        return max(val_sum, 10.0)

    trd_5d = calc_total_trading_val(daily[-5:])
    trd_10d = calc_total_trading_val(daily[-10:])
    trd_20d = calc_total_trading_val(daily[-20:])

    # -------------------------------------------------------------
    # ① 수급 강도 점수 (40점 만점) - 거래대금 대비 수급 강도
    # -------------------------------------------------------------
    ratio_5d = amt_5d / trd_5d
    ratio_10d = amt_10d / trd_10d
    ratio_20d = amt_20d / trd_20d

    weighted_ratio = (ratio_5d * 0.45) + (ratio_10d * 0.35) + (ratio_20d * 0.20)
    intensity_score = float(np.clip(20.0 + (weighted_ratio * 400.0), 0.0, 40.0))

    if weighted_ratio > 0.03:
        reasons.append("거래대금 대비 수급 가중 비율 우수")
    elif weighted_ratio < -0.03:
        reasons.append("거래대금 대비 수급 이탈 우려")

    # -------------------------------------------------------------
    # ② 지속성·동조화 점수 (35점 만점)
    # -------------------------------------------------------------
    persistence_score = 17.5

    recent_5 = daily[-5:]
    positive_days = sum(1 for r in recent_5 if (r.get("foreign_amount", 0) or 0) > 0)
    if positive_days >= 4:
        persistence_score += 8.0
        reasons.append("최근 5일 중 4일 이상 외국인 연속 매수 유지")
    elif positive_days <= 1:
        persistence_score -= 6.0

    last_r = daily[-1]
    frgn_last = last_r.get("foreign_amount") or 0.0
    inst_last = last_r.get("institution_amount") or 0.0
    pension_last = last_r.get("pension_amount")
    fin_last = last_r.get("financial_investment_amount")

    if frgn_last > 0 and (pension_last and pension_last > 0):
        persistence_score += 9.5
        reasons.append("🔥 주요 투자자 동시 유입 (외국인+연기금 동반 매수)")
    elif frgn_last > 0 and inst_last > 0:
        persistence_score += 9.5
        reasons.append("🔥 주요 투자자 동시 유입 (외국인+기관 쌍끌이)")
    elif frgn_last < 0 and inst_last < 0:
        persistence_score -= 8.0
        if not is_etf:
            reasons.append("⚠️ 주요 투자자 수급 약화 (외국인+기관 동반 매도)")
        else:
            reasons.append("외국인 + 기관 동반 순매도 출회 (LP 유동성 매도 가능성)")

    # 🛡️ 금융투자 단독 매수 착시 감점 (세부 데이터 있을 시)
    if fin_last and fin_last > 0 and frgn_last < 0 and (pension_last is not None and pension_last <= 0):
        persistence_score -= 5.0
        reasons.append("단기 금융투자 홀로 매수 (장기 자금 유입 확인 필요)")

    persistence_score = float(np.clip(persistence_score, 0.0, 35.0))

    # -------------------------------------------------------------
    # ③ 주가·거래량·전환 점수 (25점 만점)
    # -------------------------------------------------------------
    alignment_score = 12.5

    first_cp = daily[0].get("close_price", 1)
    last_cp = daily[-1].get("close_price", 1)
    price_change_pct = ((last_cp - first_cp) / first_cp) * 100.0 if first_cp > 0 else 0.0

    if price_change_pct < -2.0 and amt_5d > 0:
        alignment_score += 6.5
        reasons.append("⚡ 역발상 수급 유입 가능성 (가격 하락 구간 큰손 매수)")
    elif price_change_pct < -2.0 and amt_5d < 0:
        alignment_score -= 5.0
        reasons.append("🔴 수급·가격 동시 약화 (주가 하락 및 수급 이탈 동반)")
    elif price_change_pct > 5.0 and amt_5d < 0:
        alignment_score -= 7.0
        reasons.append("수급·가격 다이버전스 (주가 상승 및 큰손 차익 실현 출회)")
    elif price_change_pct > 0 and amt_5d > 0:
        alignment_score += 5.0
        reasons.append("긍정적 수급 (주가 상승 및 순매수 동반 유입)")

    if len(daily) >= 6:
        prev_3d_amt, _ = calc_weighted_smart_amount(daily[-6:-3])
        last_3d_amt, _ = calc_weighted_smart_amount(daily[-3:])
        if prev_3d_amt < 0 and last_3d_amt > 0:
            alignment_score += 6.0
            reasons.append("최근 3일 수급 순매수로 긍정적 전환")

    alignment_score = float(np.clip(alignment_score, 0.0, 25.0))

    # -------------------------------------------------------------
    # 4. 최종 Smart Money Score (0~100점) 합산 및 5단계 신호 판정
    # -------------------------------------------------------------
    total_score = round(float(np.clip(intensity_score + persistence_score + alignment_score, 0.0, 100.0)), 1)

    if total_score >= 80.0:
        grade = "STRONG_BUY"
        label = "🟢 강한 수급 유입 가능성 (ETF)" if is_etf else "🟢 강한 수급 유입 가능성"
        color = "#22c55e"
    elif total_score >= 65.0:
        grade = "BUY_DOMINANT"
        label = "🟢 수급 우세 가능성 (ETF)" if is_etf else "🟢 수급 우세 가능성"
        color = "#10b981"
    elif total_score >= 45.0:
        grade = "NEUTRAL"
        label = "🟡 중립/관망 (ETF)" if is_etf else "🟡 중립/관망"
        color = "#eab308"
    elif total_score >= 25.0:
        grade = "WARNING"
        label = "🟠 수급 약화 가능성 (ETF)" if is_etf else "🟠 수급 약화 가능성"
        color = "#f97316"
    else:
        grade = "STRONG_OUTFLOW"
        label = "🔴 강한 수급 약화 가능성 (ETF)" if is_etf else "🔴 강한 수급 약화 가능성"
        color = "#ef4444"

    reasons = list(dict.fromkeys(reasons))[:4]
    if not reasons:
        reasons.append("큰손 수급 평이 수준 유지")

    return {
        "available": True,
        "is_detail_available": has_detail_flag,
        "is_etf": is_etf,
        "score": total_score,
        "signal_grade": grade,
        "signal_label": label,
        "signal_color": color,
        "reasons": reasons,
        "summary": {
            "intensity_score": round(intensity_score, 1),
            "persistence_score": round(persistence_score, 1),
            "alignment_score": round(alignment_score, 1),
            "smart_amount_5d": round(amt_5d, 2),
            "smart_amount_10d": round(amt_10d, 2),
            "smart_amount_20d": round(amt_20d, 2)
        }
    }
