import pandas as pd
import numpy as np
from typing import Dict, Any, List
from backend.engine.flow_engine import analyze_stock_flow
from backend.engine.technical_engine import calculate_technical_indicators

def calculate_buy_score(flow_res: Dict[str, Any], tech_res: Dict[str, Any]) -> Dict[str, Any]:
    """
    Buy Score (0~100점) 연산
    - 0~20: 매수금지
    - 21~40: 관망
    - 41~60: 분할매수 검토
    - 61~80: 매수 유리
    - 81~100: 강한 매수 후보
    """
    score = 0.0
    reasons = []

    # 1. FFCS 수급 점수 반영 (최대 30점)
    ffcs = flow_res.get("ffcs_score", 50.0)
    score += (ffcs * 0.3)
    if ffcs >= 60:
        reasons.append(f"FFCS {ffcs}점으로 외국인 수급 우위")

    # 2. 기관 및 동조화 수급 반영 (최대 15점)
    concurrency_code = flow_res.get("concurrency", {}).get("code", "")
    if concurrency_code == "BOTH_BUY":
        score += 15.0
        reasons.append("외국인+기관 쌍끌이 동시 순매수")
    elif concurrency_code == "FRGN_BUY_INST_SELL":
        score += 10.0
    elif concurrency_code == "FRGN_SELL_INST_BUY":
        score += 7.0

    # 3. 기술적 지표 RSI (최대 15점)
    rsi = tech_res.get("rsi", 50.0)
    if rsi <= 35:
        score += 15.0
        reasons.append(f"RSI {rsi:.1f}로 과매도 구간 반등 기대")
    elif 35 < rsi <= 55:
        score += 10.0
    elif rsi >= 70:
        score += 0.0

    # 4. MACD 및 이동평균선 정배열 (최대 20점)
    macd_info = tech_res.get("macd", {})
    if macd_info.get("is_golden_cross", False):
        score += 10.0
        reasons.append("MACD 골든크로스 발생")
    elif macd_info.get("histogram", 0) > 0:
        score += 5.0

    if tech_res.get("is_aligned_bullish", False):
        score += 10.0
        reasons.append("이동평균선(5/20/60일) 정배열 상승추세")

    # 5. 지지선 접근도 (최대 20점)
    dist_supp = tech_res.get("dist_to_support", 10.0)
    if dist_supp <= 3.0:
        score += 20.0
        reasons.append(f"주가가 지지선({tech_res.get('support_level', 0):,}원) 부근 위치")
    elif dist_supp <= 7.0:
        score += 10.0

    final_score = round(float(np.clip(score, 0, 100)), 1)

    if final_score <= 20.0:
        grade = "매수금지"
    elif final_score <= 40.0:
        grade = "관망"
    elif final_score <= 60.0:
        grade = "분할매수 검토"
    elif final_score <= 80.0:
        grade = "매수 유리"
    else:
        grade = "강한 매수 후보"

    return {
        "score": final_score,
        "grade": grade,
        "reasons": reasons
    }


def calculate_sell_score(flow_res: Dict[str, Any], tech_res: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sell Score (0~100점) 연산
    - 0~20: 보유
    - 21~40: 보유
    - 41~60: 일부 익절 검토
    - 61~80: 분할매도 검토
    - 81~100: 강한 매도 경고
    """
    score = 0.0
    reasons = []

    # 1. 외국인/기관 매도 전환 (최대 35점)
    f_dir = flow_res.get("foreign_direction", "")
    i_dir = flow_res.get("institution_direction", "")
    concurrency_code = flow_res.get("concurrency", {}).get("code", "")

    if concurrency_code == "BOTH_SELL":
        score += 35.0
        reasons.append("외국인+기관 쌍끌이 동시 순매도 발생")
    elif f_dir == "매도":
        score += 20.0
        reasons.append("외국인 매도세 전환")

    # 2. RSI 과열 (최대 20점)
    rsi = tech_res.get("rsi", 50.0)
    if rsi >= 70:
        score += 20.0
        reasons.append(f"RSI {rsi:.1f}로 과열 구간 매도 압력 높음")
    elif rsi >= 60:
        score += 10.0

    # 3. MACD 데드크로스 및 추세 이탈 (최대 25점)
    macd_info = tech_res.get("macd", {})
    if macd_info.get("is_dead_cross", False):
        score += 15.0
        reasons.append("MACD 데드크로스 발생")

    if tech_res.get("is_aligned_bearish", False):
        score += 10.0
        reasons.append("이동평균선 역배열 진행 중")

    # 4. 저항선 근접 (최대 20점)
    dist_res = tech_res.get("dist_to_resistance", 10.0)
    if dist_res <= 2.0:
        score += 20.0
        reasons.append(f"주가가 저항선({tech_res.get('resistance_level', 0):,}원)에 근접")
    elif dist_res <= 5.0:
        score += 10.0

    final_score = round(float(np.clip(score, 0, 100)), 1)

    if final_score <= 40.0:
        grade = "보유"
    elif final_score <= 60.0:
        grade = "일부 익절 검토"
    elif final_score <= 80.0:
        grade = "분할매도 검토"
    else:
        grade = "강한 매도 경고"

    return {
        "score": final_score,
        "grade": grade,
        "reasons": reasons
    }


def calculate_watering_score(
    flow_res: Dict[str, Any],
    tech_res: Dict[str, Any],
    return_rate: float = 0.0
) -> Dict[str, Any]:
    """
    Watering Score (물타기 판단 엔진)
    단순 하락시 추천 절대 금지 원칙!
    결과: 적극적 추가매수 검토 / 분할매수 / 관망 / 추가매수 금지 / 비중축소
    """
    reasons = []
    
    ffcs = flow_res.get("ffcs_score", 50.0)
    cycle = flow_res.get("cycle_stage", "")
    f_dir = flow_res.get("foreign_direction", "")
    i_dir = flow_res.get("institution_direction", "")
    rsi = tech_res.get("rsi", 50.0)
    dist_supp = tech_res.get("dist_to_support", 10.0)
    is_bearish = tech_res.get("is_aligned_bearish", False)
    divergence_type = flow_res.get("divergence", {}).get("type", "NONE")

    # 가중 점수 연산 (0~100)
    score = 50.0

    # 1. 수급 및 FFCS 조건 (매집 초기/본격 매집 시 플러스)
    if cycle in ["본격 매집", "매집 초기"]:
        score += 15.0
        reasons.append(f"외국인 수급 사이클이 [{cycle}] 상태")
    elif cycle in ["강한 매도", "분배 초기", "본격 매도"]:
        score -= 25.0
        reasons.append(f"외국인 수급 사이클이 [{cycle}] 상태로 물타기 위험")

    # 2. 수급 다이버전스
    if divergence_type == "POSITIVE":
        score += 15.0
        reasons.append("긍정적 수급 다이버전스(주가 하락/횡보 속 외국인 매집) 포착")
    elif divergence_type == "NEGATIVE":
        score -= 20.0
        reasons.append("부정적 수급 다이버전스(분배 신호) 포착")

    # 3. 기술적 지지선 및 RSI 과매도
    if dist_supp <= 4.0:
        score += 10.0
        reasons.append(f"주가가 60일선/지지선({tech_res.get('support_level', 0):,}원) 지지 받는 위치")
    
    if rsi <= 35:
        score += 10.0
        reasons.append(f"RSI {rsi:.1f} 과매도 지지 구간")

    if is_bearish:
        score -= 15.0
        reasons.append("이동평균선 완벽 역배열 하락세 지속 중")

    final_score = round(float(np.clip(score, 0, 100)), 1)

    if final_score >= 75.0 and return_rate < 0:
        action = "적극적 추가매수 검토"
    elif final_score >= 60.0:
        action = "분할매수"
    elif final_score >= 40.0:
        action = "관망"
    elif final_score >= 25.0:
        action = "추가매수 금지"
    else:
        action = "비중축소"

    return {
        "score": final_score,
        "action": action,
        "reasons": reasons
    }


def make_final_decision(
    buy_info: Dict[str, Any],
    sell_info: Dict[str, Any],
    water_info: Dict[str, Any],
    flow_res: Dict[str, Any],
    tech_res: Dict[str, Any],
    return_rate: float = 0.0
) -> Dict[str, Any]:
    """
    최종 판단 (BUY, HOLD, AVERAGE, TAKE PROFIT, REDUCE 중 하나 판정)
    및 간결한 3~5개 AI 판단 이유 생성
    """
    buy_score = buy_info["score"]
    sell_score = sell_info["score"]
    water_action = water_info["action"]

    # 5가지 액션 단계 정밀 판정 (보조지표 및 수급/스코어 종합반영)
    rsi = tech_res.get("rsi", 50.0)
    macd = tech_res.get("macd", {})
    
    buy_signals = 0
    sell_signals = 0

    if rsi <= 38: buy_signals += 1
    elif rsi >= 65: sell_signals += 1

    if macd.get("is_golden_cross", False) or macd.get("histogram", 0) > 0: buy_signals += 1
    elif macd.get("is_dead_cross", False) or macd.get("histogram", 0) < 0: sell_signals += 1

    if tech_res.get("is_aligned_bullish", False): buy_signals += 1
    elif tech_res.get("is_aligned_bearish", False): sell_signals += 1

    # 종합 점수 계산 (Buy Score, Sell Score, 기술 지표 매수/매도 시그널 반영)
    if return_rate >= 15.0 and sell_score >= 50.0:
        decision = "TAKE_PROFIT"
        decision_desc = "강력 매도 / 익절 (수익 실현 및 위험 관리)"
    elif return_rate < -5.0 and water_action in ["적극적 추가매수 검토", "분할매수"]:
        decision = "AVERAGE"
        decision_desc = "분할 매수 (평단가 관리)"
    elif return_rate < -10.0 and water_action in ["추가매수 금지", "비중축소"]:
        decision = "REDUCE"
        decision_desc = "매도 / 비중축소 (추가 손실 방지)"
    elif buy_score >= 60.0 or (buy_score >= 48.0 and buy_signals >= 2) or (buy_score >= 50.0 and buy_score > sell_score + 15.0):
        decision = "BUY"
        decision_desc = "강력 매수 (수급 우위 및 기술적 모멘텀 양호)"
    elif buy_score >= 40.0 or (buy_score >= 30.0 and buy_signals >= 1) or (buy_score > sell_score):
        decision = "AVERAGE"
        decision_desc = "매수 / 분할매수 (수급 개선 및 보조지표 반등)"
    elif sell_score >= 60.0 or (sell_score >= 48.0 and sell_signals >= 2) or (sell_score >= 50.0 and sell_score > buy_score + 15.0):
        decision = "TAKE_PROFIT"
        decision_desc = "강력 매도 (수급 유출 및 주요 지지선 이탈)"
    elif sell_score >= 40.0 or (sell_score >= 30.0 and sell_signals >= 1) or (sell_score > buy_score):
        decision = "REDUCE"
        decision_desc = "매도 / 비중축소 (추세 약화 및 하락 리스크)"
    else:
        decision = "HOLD"
        decision_desc = "관망 (추세 지지 및 방향성 관찰)"

    # AI 판단 이유 생성 (3~5개 간결한 이유)
    ai_reasons = []
    
    # 1. 외국인 수급 이유
    consec = flow_res.get("periods_analysis", {}).get("foreign", {}).get("consecutive_days", 0)
    if consec > 0:
        ai_reasons.append(f"외국인 {consec}일 연속 순매수")
    elif consec < 0:
        ai_reasons.append(f"외국인 {abs(consec)}일 연속 순매도")
    else:
        ai_reasons.append(f"외국인 수급 {flow_res.get('foreign_direction', '중립')}")

    # 2. 지지/저항 및 이평선 이유
    if tech_res.get("is_aligned_bullish", False):
        ai_reasons.append("이동평균선(5/20/60일) 정배열")
    elif tech_res.get("dist_to_support", 100) <= 5.0:
        ai_reasons.append(f"지지선({tech_res.get('support_level', 0):,}원) 부근 지지")
    elif tech_res.get("dist_to_resistance", 100) <= 3.0:
        ai_reasons.append(f"저항선({tech_res.get('resistance_level', 0):,}원) 부근 저항")

    # 3. 기관 동조화 이유
    conc_desc = flow_res.get("concurrency", {}).get("description", "")
    if conc_desc:
        ai_reasons.append(conc_desc)

    # 4. RSI / MACD 지표
    rsi = tech_res.get("rsi", 50)
    if rsi <= 35:
        ai_reasons.append(f"RSI {rsi} 과매도 지지")
    elif rsi >= 70:
        ai_reasons.append(f"RSI {rsi} 과열 구간")
    else:
        ai_reasons.append(f"FFCS {flow_res.get('ffcs_score', 50)}점 수급 상태")

    # 중복 제거 및 최대 4개로 슬라이싱
    ai_reasons = list(dict.fromkeys(ai_reasons))[:4]

    return {
        "decision": decision,
        "decision_desc": decision_desc,
        "buy_score": buy_score,
        "buy_grade": buy_info["grade"],
        "sell_score": sell_score,
        "sell_grade": sell_info["grade"],
        "watering_score": water_info["score"],
        "watering_action": water_info["action"],
        "ai_reasons": ai_reasons,
        "disclaimer": "본 분석 결과는 투자 참고용 보조 지표이며 확정적 투자 수익을 보장하지 않습니다."
    }


def analyze_stock_decision(df: pd.DataFrame, return_rate: float = 0.0) -> Dict[str, Any]:
    """
    단일 종목 통합 수급+기술적 분석+의사결정 판단 메인 함수
    """
    if df.empty or len(df) < 5:
        return {"data_available": False, "error": "분석 데이터가 부족합니다."}

    # 1. 수급 분석 엔진
    flow_res = analyze_stock_flow(df)
    # 2. 기술적 분석 엔진
    tech_res = calculate_technical_indicators(df)

    if not flow_res.get("data_available", False) or not tech_res.get("data_available", False):
        return {"data_available": False, "error": "데이터 분석 실패"}

    # 3. Buy Score, Sell Score, Watering Score 연산
    buy_info = calculate_buy_score(flow_res, tech_res)
    sell_info = calculate_sell_score(flow_res, tech_res)
    water_info = calculate_watering_score(flow_res, tech_res, return_rate=return_rate)

    # 4. 최종 종합 판단 & AI 이유 생성
    final_info = make_final_decision(buy_info, sell_info, water_info, flow_res, tech_res, return_rate=return_rate)

    # 5. 매매 타이밍 보조지표 분석 (볼린저 밴드, MACD, 스토캐스틱 슬로우 + 판정 사유)
    from backend.engine.timing_engine import analyze_trading_timing
    timing_res = analyze_trading_timing(df)

    return {
        "data_available": True,
        "flow_analysis": flow_res,
        "technical_analysis": tech_res,
        "timing_analysis": timing_res,
        "decision": final_info
    }
