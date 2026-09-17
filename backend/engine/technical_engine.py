import pandas as pd
import numpy as np
from typing import Dict, Any

def calculate_technical_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    기술적 분석 지표 계산:
    - 5/20/60일 이동평균 (MA5, MA20, MA60)
    - RSI (14일)
    - MACD (12, 26, 9)
    - 거래량/거래대금 추세
    - 지지선 및 저항선 (최근 20일/60일 피봇 및 저가/고가 기준)
    """
    if df.empty or len(df) < 5:
        return {"data_available": False, "error": "기술적 분석을 위한 데이터가 부족합니다."}

    df = df.copy()
    close = df['close_price'].astype(float)
    volume = df['volume'].astype(float)
    trading_val = df['trading_value'].astype(float)

    # 1. 이동평균선 (MA5, MA20, MA60)
    df['ma5'] = close.rolling(window=5, min_periods=1).mean()
    df['ma20'] = close.rolling(window=20, min_periods=1).mean()
    df['ma60'] = close.rolling(window=60, min_periods=1).mean()

    latest_close = close.iloc[-1]
    ma5_val = float(df['ma5'].iloc[-1])
    ma20_val = float(df['ma20'].iloc[-1])
    ma60_val = float(df['ma60'].iloc[-1])

    # 2. RSI (14일)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
    rs = gain / (loss.replace(0, np.nan))
    rsi_series = 100 - (100 / (1 + rs))
    rsi_val = float(rsi_series.fillna(50.0).iloc[-1])

    # 3. MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    macd_val = float(macd_line.iloc[-1])
    macd_sig_val = float(macd_signal.iloc[-1])
    macd_hist_val = float(macd_hist.iloc[-1])
    macd_prev_hist = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else 0.0

    # 4. 거래량 & 거래대금 변화율
    v5_avg = volume.iloc[-5:].mean() if len(volume) >= 5 else volume.mean()
    v20_avg = volume.iloc[-20:].mean() if len(volume) >= 20 else volume.mean()
    volume_ratio = (v5_avg / v20_avg * 100) if v20_avg > 0 else 100.0

    # 5. 지지선 및 저항선 (최근 20일 저가/고가 및 이평선 기준)
    recent_20 = df.iloc[-20:]
    recent_min = float(recent_20['close_price'].min())
    recent_max = float(recent_20['close_price'].max())
    
    # 지지선: 20일 신저점과 20일 이평선 중 하단 가격
    support_level = min(recent_min, ma20_val)
    # 저항선: 20일 최고점과 20일 이평선 중 상단 가격
    resistance_level = max(recent_max, ma20_val)

    # 지지선/저항선 대비 현재가 이격도 (%)
    dist_to_support = ((latest_close - support_level) / support_level * 100) if support_level > 0 else 0.0
    dist_to_resistance = ((resistance_level - latest_close) / latest_close * 100) if latest_close > 0 else 0.0
    # 이동평균 배열 상태 (정배열: MA5 > MA20 > MA60)
    is_aligned_bullish = (ma5_val > ma20_val > ma60_val)
    is_aligned_bearish = (ma5_val < ma20_val < ma60_val)

    # 6. 중장기 추세 분석 (STEP 1: 기존 MA/현재가 재사용, MA120 및 5d 전 slope를 위해 125일 필요)
    df['ma120'] = close.rolling(window=120, min_periods=120).mean()
    ma120_val = float(df['ma120'].iloc[-1]) if not pd.isna(df['ma120'].iloc[-1]) else 0.0

    ma60_5d_ago = float(df['ma60'].iloc[-6]) if len(df) >= 6 and not pd.isna(df['ma60'].iloc[-6]) else ma60_val
    ma120_5d_ago = float(df['ma120'].iloc[-6]) if len(df) >= 6 and not pd.isna(df['ma120'].iloc[-6]) else ma120_val
    ma60_slope = ((ma60_val - ma60_5d_ago) / ma60_5d_ago * 100) if ma60_5d_ago > 0 else 0.0
    ma120_slope = ((ma120_val - ma120_5d_ago) / ma120_5d_ago * 100) if ma120_5d_ago > 0 else 0.0

    if len(close) < 125:
        trend_analysis = {
            "available": False,
            "reason": "추세 진단을 위한 데이터 수량 부족 (최소 125일 이상 필요)"
        }
    else:
        t_score = 50.0
        t_reasons = []

        if latest_close > ma60_val:
            t_score += 15.0
            t_reasons.append(f"현재가({int(latest_close):,}원)가 MA60({int(ma60_val):,}원) 위")
        else:
            t_score -= 15.0
            t_reasons.append(f"현재가({int(latest_close):,}원)가 MA60({int(ma60_val):,}원) 아래")

        if ma60_val > ma120_val:
            t_score += 15.0
            t_reasons.append(f"MA60({int(ma60_val):,}원)이 MA120({int(ma120_val):,}원) 위")
        else:
            t_score -= 15.0
            t_reasons.append(f"MA60({int(ma60_val):,}원)이 MA120({int(ma120_val):,}원) 아래")

        if ma20_val > ma60_val:
            t_score += 10.0
        else:
            t_score -= 10.0

        if ma60_slope > 0.1:
            t_score += 5.0
            t_reasons.append("MA60 기울기 상승")
        elif ma60_slope < -0.1:
            t_score -= 5.0
            t_reasons.append("MA60 기울기 하락")

        if ma120_slope > 0.05:
            t_score += 5.0
        elif ma120_slope < -0.05:
            t_score -= 5.0

        final_t_score = round(float(np.clip(t_score, 0, 100)), 1)

        if final_t_score >= 80.0:
            t_state = "STRONG_UP"
        elif final_t_score >= 60.0:
            t_state = "UP"
        elif final_t_score >= 40.0:
            t_state = "NEUTRAL"
        elif final_t_score >= 20.0:
            t_state = "DOWN"
        else:
            t_state = "STRONG_DOWN"

        if final_t_score >= 75.0 or final_t_score <= 25.0:
            t_strength = "STRONG"
        elif final_t_score >= 60.0 or final_t_score <= 40.0:
            t_strength = "NORMAL"
        else:
            t_strength = "WEAK"

        trend_analysis = {
            "available": True,
            "trend_state": t_state,
            "trend_score": final_t_score,
            "trend_strength": t_strength,
            "trend_reasons": t_reasons[:3],
            "ma120": round(ma120_val, 1),
            "ma60_slope": round(ma60_slope, 2),
            "ma120_slope": round(ma120_slope, 2)
        }

    return {
        "data_available": True,
        "latest_close": int(latest_close),
        "ma5": round(ma5_val, 1),
        "ma20": round(ma20_val, 1),
        "ma60": round(ma60_val, 1),
        "ma120": round(ma120_val, 1),
        "rsi": round(rsi_val, 1),
        "macd": {
            "macd": round(macd_val, 1),
            "signal": round(macd_sig_val, 1),
            "histogram": round(macd_hist_val, 1),
            "is_golden_cross": (macd_prev_hist <= 0 and macd_hist_val > 0),
            "is_dead_cross": (macd_prev_hist >= 0 and macd_hist_val < 0)
        },
        "volume_ratio": round(volume_ratio, 1),
        "support_level": int(support_level),
        "resistance_level": int(resistance_level),
        "dist_to_support": round(dist_to_support, 2),
        "dist_to_resistance": round(dist_to_resistance, 2),
        "is_aligned_bullish": is_aligned_bullish,
        "is_aligned_bearish": is_aligned_bearish,
        "trend_analysis": trend_analysis
    }
