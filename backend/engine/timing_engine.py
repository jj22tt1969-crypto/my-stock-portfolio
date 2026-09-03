import pandas as pd
import numpy as np
from typing import Dict, Any, List

def calculate_bollinger_bands(close: pd.Series, window: int = 20, num_std: float = 2.0) -> Dict[str, Any]:
    """
    볼린저 밴드 (20, 2.0) 계산 및 매매 신호/사유 분석
    - MB: 20일 이동평균선
    - UB: MB + 2.0 * std
    - LB: MB - 2.0 * std
    """
    if len(close) < window:
        return {"signal": "NEUTRAL", "score": 0, "reason": "볼린저 밴드: 데이터 기간 부족"}

    mb = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std()
    
    ub = mb + (num_std * std)
    lb = mb - (num_std * std)

    latest_close = float(close.iloc[-1])
    latest_mb = float(mb.iloc[-1])
    latest_ub = float(ub.iloc[-1])
    latest_lb = float(lb.iloc[-1])

    prev_close = float(close.iloc[-2]) if len(close) >= 2 else latest_close
    prev_lb = float(lb.iloc[-2]) if len(lb) >= 2 else latest_lb
    prev_ub = float(ub.iloc[-2]) if len(ub) >= 2 else latest_ub

    # 밴드폭 (Band Width %) 및 스퀴즈 감지
    bandwidth = ((latest_ub - latest_lb) / latest_mb * 100) if latest_mb > 0 else 0.0
    
    # 신호 및 사유 판정
    signal = "NEUTRAL"
    score = 0
    reason = ""

    # 하단 터치/하회 후 반등 또는 하단 2% 이내 밀착
    if prev_close <= prev_lb or latest_close <= latest_lb:
        signal = "BUY"
        score = 1
        reason = f"볼린저 밴드: 하단선({int(latest_lb):,}원) 터치/하회로 과매도 반등 매수 타이밍"
    elif latest_close <= latest_lb * 1.02:
        signal = "BUY"
        score = 1
        reason = f"볼린저 밴드: 하단 지지선({int(latest_lb):,}원) 근접으로 반등 기대"
    # 상단 터치/상회 또는 상단 2% 이내 밀착
    elif prev_close >= prev_ub or latest_close >= latest_ub:
        signal = "SELL"
        score = -1
        reason = f"볼린저 밴드: 상단선({int(latest_ub):,}원) 돌파/상회로 매도/수익실현 타이밍"
    elif latest_close >= latest_ub * 0.98:
        signal = "SELL"
        score = -1
        reason = f"볼린저 밴드: 상단 저항선({int(latest_ub):,}원) 근접으로 저항 가능성"
    else:
        signal = "NEUTRAL"
        score = 0
        if bandwidth < 10.0:
            reason = f"볼린저 밴드: 밴드 수축(Bandwidth {bandwidth:.1f}%) 상태로 에너지 축적 중"
        else:
            reason = f"볼린저 밴드: 중심선({int(latest_mb):,}원) 부근 밴드 내부 안착 추세"

    return {
        "middle": int(latest_mb),
        "upper": int(latest_ub),
        "lower": int(latest_lb),
        "bandwidth": round(bandwidth, 1),
        "signal": signal,
        "score": score,
        "reason": reason
    }


def calculate_macd_timing(close: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9) -> Dict[str, Any]:
    """
    MACD (12, 26, 9) 계산 및 크로스 매매 신호/사유 분석
    """
    if len(close) < slow + signal_period:
        return {"signal": "NEUTRAL", "score": 0, "reason": "MACD: 데이터 기간 부족"}

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal_period, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    latest_macd = float(macd_line.iloc[-1])
    latest_sig = float(macd_signal.iloc[-1])
    latest_hist = float(macd_hist.iloc[-1])
    prev_hist = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else 0.0

    signal = "NEUTRAL"
    score = 0
    reason = ""

    # 골든크로스 / 데드크로스 감지
    if prev_hist <= 0 and latest_hist > 0:
        signal = "BUY"
        score = 1
        reason = "MACD: 9일 시그널선 골든크로스 발생 (상승 모멘텀 전환)"
    elif prev_hist >= 0 and latest_hist < 0:
        signal = "SELL"
        score = -1
        reason = "MACD: 9일 시그널선 데드크로스 발생 (하락 모멘텀 전환)"
    elif latest_hist > 0:
        signal = "BUY"
        score = 1
        reason = f"MACD: 매수 우세 구간 지속 (Histogram +{round(latest_hist, 1)})"
    elif latest_hist < 0:
        signal = "SELL"
        score = -1
        reason = f"MACD: 매도 우세 구간 지속 (Histogram {round(latest_hist, 1)})"
    else:
        signal = "NEUTRAL"
        score = 0
        reason = "MACD: 시그널선 수렴 관망 구간"

    return {
        "macd": round(latest_macd, 1),
        "signal_line": round(latest_sig, 1),
        "histogram": round(latest_hist, 1),
        "signal": signal,
        "score": score,
        "reason": reason
    }


def calculate_stochastic_slow(df: pd.DataFrame, n: int = 14, k_period: int = 3, d_period: int = 3) -> Dict[str, Any]:
    """
    스토캐스틱 슬로우 (14, 3, 3) 계산 및 매매 신호/사유 분석
    - Fast %K = (Close - MinLow14) / (MaxHigh14 - MinLow14) * 100
    - Slow %K = Fast %K의 k_period 이동평균
    - Slow %D = Slow %K의 d_period 이동평균
    """
    if len(df) < n + k_period + d_period:
        return {"signal": "NEUTRAL", "score": 0, "reason": "스토캐스틱: 데이터 기간 부족"}

    close = df['close_price'].astype(float)
    high = df['high_price'].astype(float) if 'high_price' in df.columns else close
    low = df['low_price'].astype(float) if 'low_price' in df.columns else close

    lowest_low = low.rolling(window=n, min_periods=n).min()
    highest_high = high.rolling(window=n, min_periods=n).max()

    fast_k = ((close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)) * 100
    slow_k = fast_k.rolling(window=k_period, min_periods=k_period).mean()
    slow_d = slow_k.rolling(window=d_period, min_periods=d_period).mean()

    latest_k = float(slow_k.fillna(50.0).iloc[-1])
    latest_d = float(slow_d.fillna(50.0).iloc[-1])
    prev_k = float(slow_k.fillna(50.0).iloc[-2]) if len(slow_k) >= 2 else latest_k

    signal = "NEUTRAL"
    score = 0
    reason = ""

    # 20 이하 탈출 (매수) / 80 이상 이탈 (매도)
    if prev_k <= 20 and latest_k > 20:
        signal = "BUY"
        score = 1
        reason = f"스토캐스틱: 과매도 구간(20 이하) 상향 탈출 (%K {round(latest_k, 1)}) ➔ 매수 신호"
    elif latest_k <= 20:
        signal = "BUY"
        score = 1
        reason = f"스토캐스틱: 과매도 바닥 영역 안착 (%K {round(latest_k, 1)}) ➔ 분할매수 관심"
    elif prev_k >= 80 and latest_k < 80:
        signal = "SELL"
        score = -1
        reason = f"스토캐스틱: 과매수 구간(80 이상) 하향 이탈 (%K {round(latest_k, 1)}) ➔ 매도 신호"
    elif latest_k >= 80:
        signal = "SELL"
        score = -1
        reason = f"스토캐스틱: 과매수 과열 영역 안착 (%K {round(latest_k, 1)}) ➔ 경계 및 익절 타겟"
    else:
        signal = "NEUTRAL"
        score = 0
        reason = f"스토캐스틱: 중립 적정 구간 위치 (%K {round(latest_k, 1)} / %D {round(latest_d, 1)})"

    return {
        "slow_k": round(latest_k, 1),
        "slow_d": round(latest_d, 1),
        "signal": signal,
        "score": score,
        "reason": reason
    }


def analyze_trading_timing(df: pd.DataFrame) -> Dict[str, Any]:
    """
    개별종목 3대 매매 타이밍 보조지표 종합 분석 모듈 (로직 보존형 플러그인)
    1. 볼린저 밴드 (20, 2.0)
    2. MACD (12, 26, 9)
    3. 스토캐스틱 슬로우 (14, 3, 3)
    ➔ 5단계 종합 판정 & 상세 판정 사유(reasons) 리스트 생성
    """
    if df.empty or len(df) < 10:
        return {
            "status": "error",
            "message": "매매 타이밍 분석을 위한 데이터가 부족합니다.",
            "overall_decision": "관망",
            "overall_score": 0,
            "badge_class": "HOLD",
            "reasons": ["데이터 부족으로 관망 추천"],
            "summary_guide": "충분한 주가 데이터가 수집되면 분석이 재개됩니다."
        }

    close = df['close_price'].astype(float)

    bb_res = calculate_bollinger_bands(close, window=20, num_std=2.0)
    macd_res = calculate_macd_timing(close, fast=12, slow=26, signal_period=9)
    stoch_res = calculate_stochastic_slow(df, n=14, k_period=3, d_period=3)

    # 3개 지표 점수 합산 (-3 ~ +3)
    total_score = bb_res.get("score", 0) + macd_res.get("score", 0) + stoch_res.get("score", 0)

    # 5단계 종합 판정 및 배지 클래스
    if total_score >= 2:
        overall_decision = "강력매수"
        badge_class = "BUY"
        summary_guide = "3개 주요 보조지표가 동시에 강력한 매수 타이밍을 가리키고 있습니다."
    elif total_score == 1:
        overall_decision = "매수"
        badge_class = "AVERAGE"
        summary_guide = "기술적 지표상 단기 매수 우위 포착 구간입니다."
    elif total_score == 0:
        overall_decision = "관망"
        badge_class = "HOLD"
        summary_guide = "매수/매도 신호가 팽팽히 엇갈리는 관망 구간입니다."
    elif total_score == -1:
        overall_decision = "매도"
        badge_class = "REDUCE"
        summary_guide = "단기 상단 저항 및 매도 신호 우위 구간입니다."
    else: # -2, -3
        overall_decision = "강력매도"
        badge_class = "TAKE_PROFIT"
        summary_guide = "보조지표가 동시에 과열 이탈 및 강력 매도 경고를 나타냅니다."

    # 지표별 상세 판정 사유 목록
    reasons = [
        bb_res.get("reason", ""),
        macd_res.get("reason", ""),
        stoch_res.get("reason", "")
    ]
    reasons = [r for r in reasons if r]

    return {
        "status": "success",
        "overall_decision": overall_decision,
        "overall_score": total_score,
        "badge_class": badge_class,
        "summary_guide": summary_guide,
        "reasons": reasons,
        "bollinger_bands": bb_res,
        "macd": macd_res,
        "stochastic_slow": stoch_res
    }
