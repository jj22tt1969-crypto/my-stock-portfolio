import pandas as pd
import numpy as np
from typing import Dict, Any, List

def calculate_consecutive_days(series: pd.Series) -> int:
    """
    최신 데이터 기준 순매수(+) 또는 순매도(-) 연속일수 계산
    (장중 미집계 또는 0 데이터 발생 시 최신 유효 거래일 기준으로 연속성 산출)
    """
    if series is None or series.empty:
        return 0
    
    # 0이 아니고 NaN이 아닌 유효 수급 데이터 추출
    valid_values = [v for v in series.values if v != 0 and not pd.isna(v)]
    if not valid_values:
        return 0
    
    last_val = valid_values[-1]
    is_positive = last_val > 0
    count = 0
    
    for val in reversed(valid_values):
        if (val > 0 and is_positive) or (val < 0 and not is_positive):
            count += 1
        else:
            break
            
    return count if is_positive else -count


def analyze_period_flows(df: pd.DataFrame, periods: List[int] = [1, 3, 5, 10, 20]) -> Dict[str, Any]:
    """
    1, 3, 5, 10, 20일간의 외국인 및 기관 수급 세부 분석
    """
    res = {"foreign": {}, "institution": {}}
    total_len = len(df)
    
    for p in periods:
        if total_len < p:
            continue
            
        sub_df = df.iloc[-p:]
        
        # 외국인 & 기관 순매수 합계 (원)
        frgn_sum = float(sub_df['foreign_net_buy'].sum())
        inst_sum = float(sub_df['institution_net_buy'].sum())
        
        # 거래대금 합계 (원)
        trading_val_sum = float(sub_df['trading_value'].sum()) if 'trading_value' in sub_df and sub_df['trading_value'].sum() > 0 else 1.0

        # 거래대금 대비 순매수 비율 (%)
        frgn_ratio = (frgn_sum / trading_val_sum) * 100
        inst_ratio = (inst_sum / trading_val_sum) * 100

        # 수급 방향 (매수/매도/중립)
        frgn_dir = "매수" if frgn_sum > 0 else ("매도" if frgn_sum < 0 else "중립")
        inst_dir = "매수" if inst_sum > 0 else ("매도" if inst_sum < 0 else "중립")

        # 수급 강도 (-100 ~ +100 표준화)
        frgn_strength = round(np.clip(frgn_ratio * 5, -100, 100), 2)
        inst_strength = round(np.clip(inst_ratio * 5, -100, 100), 2)

        res["foreign"][f"{p}d"] = {
            "net_buy": frgn_sum,
            "direction": frgn_dir,
            "trading_ratio": round(frgn_ratio, 2),
            "strength": frgn_strength
        }
        
        res["institution"][f"{p}d"] = {
            "net_buy": inst_sum,
            "direction": inst_dir,
            "trading_ratio": round(inst_ratio, 2),
            "strength": inst_strength
        }

    # 연속일수 계산
    res["foreign"]["consecutive_days"] = calculate_consecutive_days(df['foreign_net_buy'])
    res["institution"]["consecutive_days"] = calculate_consecutive_days(df['institution_net_buy'])

    # 외국인 수급 변화율 및 수급 가속도
    if total_len >= 10:
        f5 = df.iloc[-5:]['foreign_net_buy'].sum()
        f10_prev = df.iloc[-10:-5]['foreign_net_buy'].sum()
        frgn_flow_change_rate = round(((f5 - f10_prev) / abs(f10_prev)) * 100, 2) if abs(f10_prev) > 0 else 0.0
        
        f3_avg = df.iloc[-3:]['foreign_net_buy'].mean()
        f10_avg = df.iloc[-10:]['foreign_net_buy'].mean()
        frgn_flow_accel = float(f3_avg - f10_avg)
    else:
        frgn_flow_change_rate = 0.0
        frgn_flow_accel = 0.0

    res["foreign"]["flow_change_rate"] = frgn_flow_change_rate
    res["foreign"]["flow_acceleration"] = frgn_flow_accel

    # 기관 수급 변화율 및 수급 가속도
    if total_len >= 10:
        i5 = df.iloc[-5:]['institution_net_buy'].sum()
        i10_prev = df.iloc[-10:-5]['institution_net_buy'].sum()
        inst_flow_change_rate = round(((i5 - i10_prev) / abs(i10_prev)) * 100, 2) if abs(i10_prev) > 0 else 0.0

        i3_avg = df.iloc[-3:]['institution_net_buy'].mean()
        i10_avg = df.iloc[-10:]['institution_net_buy'].mean()
        inst_flow_accel = float(i3_avg - i10_avg)
    else:
        inst_flow_change_rate = 0.0
        inst_flow_accel = 0.0

    res["institution"]["flow_change_rate"] = inst_flow_change_rate
    res["institution"]["flow_acceleration"] = inst_flow_accel

    return res


def determine_concurrency(foreign_net: float, inst_net: float) -> Dict[str, str]:
    """
    외국인 및 기관 동조화 현상 분석 (4가지 유형)
    """
    if foreign_net > 0 and inst_net > 0:
        code = "BOTH_BUY"
        desc = "외국인 + 기관 동시매수 (쌍끌이 매수)"
    elif foreign_net < 0 and inst_net < 0:
        code = "BOTH_SELL"
        desc = "외국인 + 기관 동시매도 (쌍끌이 매도)"
    elif foreign_net > 0 and inst_net < 0:
        code = "FRGN_BUY_INST_SELL"
        desc = "외국인 매수 + 기관 매도 (외국인 주도 장세)"
    elif foreign_net < 0 and inst_net > 0:
        code = "FRGN_SELL_INST_BUY"
        desc = "외국인 매도 + 기관 매수 (기관 방어 장세)"
    else:
        code = "NEUTRAL"
        desc = "수급 관망 / 중립"
        
    return {"code": code, "description": desc}


def detect_divergence(df: pd.DataFrame) -> Dict[str, Any]:
    """
    수급 다이버전스 탐지:
    1. 긍정적 다이버전스: 주가 하락/횡보 & 외국인 순매수 증가 ➔ 매집 가능성
    2. 부정적 다이버전스: 주가 상승 & 외국인 순매도 증가 ➔ 분배 가능성
    """
    if len(df) < 10:
        return {"type": "NONE", "title": "다이버전스 없음", "description": "데이터 부족 (최소 10일 필요)", "signal": "NORMAL"}

    recent_10 = df.iloc[-10:]
    first_half = recent_10.iloc[:5]
    second_half = recent_10.iloc[5:]

    price_change = (second_half['close_price'].iloc[-1] - first_half['close_price'].iloc[0]) / first_half['close_price'].iloc[0] * 100
    
    frgn_first_sum = first_half['foreign_net_buy'].sum()
    frgn_second_sum = second_half['foreign_net_buy'].sum()
    frgn_trend_diff = frgn_second_sum - frgn_first_sum

    # 긍정적 다이버전스: 주가 등락률 <= 1% (하락/횡보) & 외국인 순매수세 대폭 증가
    if price_change <= 1.0 and frgn_second_sum > 0 and frgn_trend_diff > 0:
        return {
            "type": "POSITIVE",
            "title": "긍정적 수급 다이버전스",
            "description": "주가가 하락/횡보하는 동안 외국인 순매수세가 크게 증가하여 세력 매집 가능성이 높습니다.",
            "signal": "BULLISH_ACCUMULATION"
        }
    
    # 부정적 다이버전스: 주가 등락률 >= 3% (상승) & 외국인 순매도 전환 또는 순매수 급감
    if price_change >= 3.0 and frgn_second_sum < 0:
        return {
            "type": "NEGATIVE",
            "title": "부정적 수급 다이버전스",
            "description": "주가는 상승하고 있으나 외국인이 순매도로 대응하여 물량을 분배(차익실현)하는 신호가 포착되었습니다.",
            "signal": "BEARISH_DISTRIBUTION"
        }

    return {
        "type": "NONE",
        "title": "다이버전스 없음",
        "description": "주가 흐름과 외국인 수급 방향이 일반적인 동조 경향을 나타냅니다.",
        "signal": "NORMAL"
    }


def calculate_ffcs(df: pd.DataFrame, period_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Foreign Flow Cycle Score (FFCS, 0~100점) 및 6단계 수급 사이클 판정

    6단계 사이클:
    1. 강한 매도 (0 ~ 20점)
    2. 매도 둔화 (21 ~ 40점)
    3. 매집 초기 (41 ~ 55점)
    4. 본격 매집 (56 ~ 75점)
    5. 분배 초기 (76 ~ 85점 또는 고점권 수급 이탈)
    6. 본격 매도 (86 ~ 100점 과열 경고 또는 지속적 매도 분배)
    """
    if len(df) < 5:
        return {
            "score": 50.0,
            "stage": "데이터 부족",
            "reliability": 0.0,
            "key_reasons": ["데이터 부족으로 점수 연산 불가"]
        }

    key_reasons = []
    
    # 1. 5일 및 20일 수급 점수 (최대 40점)
    f5_sum = period_analysis["foreign"].get("5d", {}).get("net_buy", 0)
    trading_20d_avg = df.iloc[-20:]['trading_value'].mean() if len(df) >= 20 else df['trading_value'].mean()
    if trading_20d_avg <= 0:
        trading_20d_avg = 1.0

    ratio_5d = (f5_sum / (trading_20d_avg * 5)) if trading_20d_avg > 0 else 0
    score_trend = float(np.clip(20 + (ratio_5d * 100), 0, 40))
    
    # 2. 순매수 지속성 점수 (최대 20점)
    consec_days = period_analysis["foreign"].get("consecutive_days", 0)
    if consec_days > 0:
        score_consec = min(20.0, consec_days * 3.5)
        key_reasons.append(f"외국인 {consec_days}일 연속 순매수 진행 중")
    elif consec_days < 0:
        score_consec = max(0.0, 10.0 - abs(consec_days) * 2.0)
        key_reasons.append(f"외국인 {abs(consec_days)}일 연속 순매도 진행 중")
    else:
        score_consec = 10.0

    # 3. 수급 가속도 점수 (최대 15점)
    accel = period_analysis["foreign"].get("flow_acceleration", 0)
    accel_ratio = accel / trading_20d_avg if trading_20d_avg > 0 else 0
    score_accel = float(np.clip(7.5 + (accel_ratio * 30), 0, 15))
    if accel > 0:
        key_reasons.append("외국인 수급 가속도가 플러스(+) 전환되어 매수세 유입 가속")
    elif accel < 0:
        key_reasons.append("외국인 수급 가속도가 마이너스(-)로 유입세 둔화 또는 이탈 시작")

    # 4. 기관 동조화 점수 (최대 15점)
    latest_f = df.iloc[-5:]['foreign_net_buy'].sum()
    latest_i = df.iloc[-5:]['institution_net_buy'].sum()
    concurrency_info = determine_concurrency(latest_f, latest_i)
    
    if concurrency_info["code"] == "BOTH_BUY":
        score_concurrency = 15.0
        key_reasons.append("외국인과 기관의 쌍끌이 동시 순매수 포착")
    elif concurrency_info["code"] == "BOTH_SELL":
        score_concurrency = 0.0
        key_reasons.append("외국인과 기관의 쌍끌이 동시 순매도 포착")
    elif concurrency_info["code"] == "FRGN_BUY_INST_SELL":
        score_concurrency = 10.0
        key_reasons.append("외국인 매수 vs 기관 매도 (외국인 주도 장세)")
    elif concurrency_info["code"] == "FRGN_SELL_INST_BUY":
        score_concurrency = 5.0
        key_reasons.append("외국인 매도 vs 기관 매수 (기관 방어 장세)")
    else:
        score_concurrency = 7.5

    # 5. 외국인 지분율 추세 (최대 10점)
    if 'foreign_holding_ratio' in df.columns and len(df) >= 10:
        ratio_diff = df['foreign_holding_ratio'].iloc[-1] - df['foreign_holding_ratio'].iloc[-10]
        score_holding = float(np.clip(5.0 + (ratio_diff * 10), 0, 10))
        if ratio_diff > 0.1:
            key_reasons.append(f"최근 10일간 외국인 지분율 +{ratio_diff:.2f}%p 증가")
        elif ratio_diff < -0.1:
            key_reasons.append(f"최근 10일간 외국인 지분율 {ratio_diff:.2f}%p 감소")
    else:
        score_holding = 5.0

    # 총점 계산 (0 ~ 100)
    total_ffcs = float(np.clip(score_trend + score_consec + score_accel + score_concurrency + score_holding, 0, 100))
    total_ffcs = round(total_ffcs, 1)

    # 6단계 수급 사이클 판정
    recent_max = df.iloc[-20:]['close_price'].max() if len(df) >= 20 else df['close_price'].max()
    recent_min = df.iloc[-20:]['close_price'].min() if len(df) >= 20 else df['close_price'].min()
    current_price = df.iloc[-1]['close_price']
    price_position = (current_price - recent_min) / (recent_max - recent_min) if (recent_max > recent_min) else 0.5

    if total_ffcs <= 20.0:
        stage = "강한 매도"
    elif total_ffcs <= 40.0:
        stage = "매도 둔화" if accel > 0 else "강한 매도"
    elif total_ffcs <= 55.0:
        stage = "매집 초기" if (accel > 0 or consec_days > 0) else "매도 둔화"
    elif total_ffcs <= 75.0:
        stage = "본격 매집"
    elif total_ffcs <= 88.0:
        if price_position >= 0.8 and accel < 0:
            stage = "분배 초기"
            key_reasons.append("주가 고점권에서 외국인 수급 가속도 감소 (분배 가능성)")
        else:
            stage = "본격 매집"
    else:
        if price_position >= 0.85 and (consec_days < 0 or accel < 0):
            stage = "본격 매도"
            key_reasons.append("고점권 수급 이탈로 본격 매도/분배 전환 경고")
        else:
            stage = "분배 초기"

    # 수급 신뢰도 계산 (데이터 샘플 수 및 데이터 품질 기반 0~100%)
    reliability = min(100.0, round((len(df) / 20.0) * 100, 1))

    return {
        "score": total_ffcs,
        "stage": stage,
        "reliability": reliability,
        "key_reasons": key_reasons
    }


def analyze_stock_flow(df: pd.DataFrame) -> Dict[str, Any]:
    """
    단일 종목의 수급 데이터 종합 분석 메인 함수 (PHASE 2 완성 규격)
    """
    if df.empty or len(df) < 5:
        return {
            "data_available": False,
            "error": "데이터 없음"
        }

    # 1. 기간별 세부 수급 분석 (1/3/5/10/20일)
    periods_analysis = analyze_period_flows(df)

    # 2. 최근 5일 기준 외국인 및 기관 수급 방향
    f5_sum = periods_analysis["foreign"].get("5d", {}).get("net_buy", 0)
    i5_sum = periods_analysis["institution"].get("5d", {}).get("net_buy", 0)

    foreign_direction = "매수" if f5_sum > 0 else ("매도" if f5_sum < 0 else "중립")
    institution_direction = "매수" if i5_sum > 0 else ("매도" if i5_sum < 0 else "중립")

    # 3. 기관 동조화 분석
    concurrency_info = determine_concurrency(f5_sum, i5_sum)

    # 4. 수급 다이버전스 탐지
    divergence_info = detect_divergence(df)

    # 5. Foreign Flow Cycle Score (FFCS) 및 6단계 사이클 판정
    ffcs_info = calculate_ffcs(df, periods_analysis)

    return {
        "data_available": True,
        "ffcs_score": ffcs_info["score"],
        "cycle_stage": ffcs_info["stage"],
        "foreign_direction": foreign_direction,
        "institution_direction": institution_direction,
        "concurrency": concurrency_info,
        "divergence": divergence_info,
        "reliability_score": ffcs_info["reliability"],
        "key_reasons": ffcs_info["key_reasons"],
        "periods_analysis": periods_analysis,
        "last_updated": df.iloc[-1]['date'],
        "latest_close": int(df.iloc[-1]['close_price'])
    }

