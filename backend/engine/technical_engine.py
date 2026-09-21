import pandas as pd
import numpy as np
from typing import Dict, Any

def calculate_relative_strength(
    df: pd.DataFrame, 
    benchmark_df: Any = None, 
    market: str = "KOSPI", 
    asset_type: str = "STOCK"
) -> Dict[str, Any]:
    """
    시장 대비 상대강도(Relative Strength) 계산:
    - 개별 주식의 5/20/60 거래일 수익률을 해당 시장(KOSPI / KOSDAQ)과 비교
    - ETF는 벤치마크 미정의로 available: False 반환
    """
    if str(asset_type).upper() == "ETF":
        return {
            "available": False,
            "reason": "ETF 벤치마크 정보 없음"
        }

    if benchmark_df is None:
        return {
            "available": False,
            "reason": "벤치마크 지수 데이터 미제공"
        }

    bm_data = None
    if isinstance(benchmark_df, dict):
        if benchmark_df.get("status") == "success" and "dates" in benchmark_df and "closes" in benchmark_df:
            bm_data = pd.DataFrame({
                "date": benchmark_df["dates"],
                "close_price": benchmark_df["closes"]
            })
    elif isinstance(benchmark_df, pd.DataFrame):
        bm_data = benchmark_df

    if bm_data is None or bm_data.empty or "date" not in bm_data.columns or "close_price" not in bm_data.columns:
        return {
            "available": False,
            "reason": "유효하지 않은 벤치마크 데이터"
        }

    if df.empty or "date" not in df.columns or "close_price" not in df.columns:
        return {
            "available": False,
            "reason": "유효하지 않은 종목 가격 데이터"
        }

    # 날짜 정렬 및 공통 거래일 Inner Join
    df_clean = df[['date', 'close_price']].copy()
    df_clean['date'] = df_clean['date'].astype(str)
    df_clean['stock_close'] = df_clean['close_price'].astype(float)

    bm_clean = bm_data[['date', 'close_price']].copy()
    bm_clean['date'] = bm_clean['date'].astype(str)
    bm_clean['bm_close'] = bm_clean['close_price'].astype(float)

    merged = pd.merge(df_clean[['date', 'stock_close']], bm_clean[['date', 'bm_close']], on='date', how='inner')
    merged.sort_values(by='date', ascending=True, inplace=True)
    merged.reset_index(drop=True, inplace=True)

    common_days = len(merged)
    if common_days < 6:
        return {
            "available": False,
            "reason": f"공통 거래일 부족 (최소 6일 이상 필요, 현재 {common_days}일)"
        }

    bm_name = market.upper() if market else "KOSPI"
    latest_common_date = merged['date'].iloc[-1]

    def get_period_metrics(days_required: int):
        if common_days < days_required + 1:
            return None, None, None
        stock_curr = merged['stock_close'].iloc[-1]
        stock_prev = merged['stock_close'].iloc[-(days_required + 1)]
        bm_curr = merged['bm_close'].iloc[-1]
        bm_prev = merged['bm_close'].iloc[-(days_required + 1)]

        if stock_prev <= 0 or bm_prev <= 0:
            return None, None, None

        s_ret = (stock_curr / stock_prev - 1.0) * 100.0
        b_ret = (bm_curr / bm_prev - 1.0) * 100.0
        rs_val = s_ret - b_ret
        return round(s_ret, 2), round(b_ret, 2), round(rs_val, 2)

    s_ret_5d, b_ret_5d, rs_5d = get_period_metrics(5)
    s_ret_20d, b_ret_20d, rs_20d = get_period_metrics(20)
    s_ret_60d, b_ret_60d, rs_60d = get_period_metrics(60)

    if rs_20d is None:
        return {
            "available": False,
            "reason": f"20일 상대강도 연산 위한 공통 거래일 부족 (필요 21일, 현재 {common_days}일)"
        }

    if rs_20d >= 10.0:
        rs_state = "STRONG"
    elif rs_20d >= 3.0:
        rs_state = "OUTPERFORM"
    elif rs_20d > -3.0:
        rs_state = "NEUTRAL"
    elif rs_20d > -10.0:
        rs_state = "UNDERPERFORM"
    else:
        rs_state = "WEAK"

    rs_reasons = []
    rs_reasons.append(f"최근 20일 종목 {s_ret_20d:+.1f}%, {bm_name} {b_ret_20d:+.1f}%")
    rs_reasons.append(f"시장 대비 20일 상대강도 {rs_20d:+.1f}%p")

    if rs_60d is not None:
        if rs_60d > 0:
            rs_reasons.append(f"60일 기준 시장 대비 +{rs_60d:.1f}%p 상회")
        else:
            rs_reasons.append(f"60일 기준 시장 대비 {rs_60d:.1f}%p 하회")
    elif rs_5d is not None:
        rs_reasons.append(f"5일 상대강도 {rs_5d:+.1f}%p")

    return {
        "available": True,
        "benchmark": bm_name,
        "benchmark_date": latest_common_date,
        "common_days": common_days,
        "rs_5d": rs_5d,
        "rs_20d": rs_20d,
        "rs_60d": rs_60d,
        "stock_return_5d": s_ret_5d,
        "benchmark_return_5d": b_ret_5d,
        "stock_return_20d": s_ret_20d,
        "benchmark_return_20d": b_ret_20d,
        "stock_return_60d": s_ret_60d,
        "benchmark_return_60d": b_ret_60d,
        "rs_state": rs_state,
        "rs_reasons": rs_reasons[:3]
    }


def calculate_price_risk_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """
    가격 리스크 분석 (risk_analysis):
    - True Range 및 ATR(14) (SMA_14 방식)
    - ATR% (ATR / 현재가 * 100)
    - 유효 기간 내 최고가 (period_high) 및 유효 거래일 수 (period_high_days)
    - 최고가 대비 현재 낙폭 (drawdown_from_high_pct)
    - 4단계 리스크 상태 (risk_state) & 사유 (risk_reasons)
    """
    if df.empty or len(df) < 5:
        return {
            "available": False,
            "reason": "가격 리스크 분석을 위한 데이터 부족"
        }

    df = df.copy()
    latest_close = float(df['close_price'].iloc[-1])
    if latest_close <= 0:
        return {
            "available": False,
            "reason": "유효하지 않은 현재가"
        }

    # 1. 고점 및 낙폭 연산 (high_price 컬럼 존재 여부 확인)
    has_high = ('high_price' in df.columns and df['high_price'].notna().any()) or ('high' in df.columns and df['high'].notna().any())
    has_low = ('low_price' in df.columns and df['low_price'].notna().any()) or ('low' in df.columns and df['low'].notna().any())

    high_col = 'high_price' if 'high_price' in df.columns else ('high' if 'high' in df.columns else None)
    low_col = 'low_price' if 'low_price' in df.columns else ('low' if 'low' in df.columns else None)

    if has_high and high_col:
        high_series = df[high_col].astype(float)
        period_high = float(high_series.max())
    else:
        period_high = float(df['close_price'].max())

    period_high_days = len(df)
    drawdown_from_high_pct = round(((latest_close / period_high) - 1.0) * 100.0, 2) if period_high > 0 else 0.0

    # 2. ATR(14) 계산 (high/low가 모두 있어야만 실제 ATR 계산, close로 임의 대체 금지)
    atr_14 = None
    atr_pct = None
    atr_available = False

    if has_high and has_low and high_col and low_col and len(df) >= 15:
        highs = df[high_col].astype(float)
        lows = df[low_col].astype(float)
        closes = df['close_price'].astype(float)

        valid_mask = (highs > 0) & (lows > 0) & (closes > 0) & (highs >= lows)
        if valid_mask.sum() >= 15:
            df_valid = df[valid_mask].copy()
            h = df_valid[high_col].astype(float)
            l = df_valid[low_col].astype(float)
            c = df_valid['close_price'].astype(float)
            prev_c = c.shift(1)

            tr1 = h - l
            tr2 = (h - prev_c).abs()
            tr3 = (l - prev_c).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # SMA_14 (Simple Moving Average 14일 롤링)
            atr_series = tr.rolling(window=14, min_periods=14).mean()
            if not pd.isna(atr_series.iloc[-1]) and atr_series.iloc[-1] > 0:
                atr_14 = float(atr_series.iloc[-1])
                atr_pct = round((atr_14 / latest_close) * 100.0, 2)
                atr_available = True

    # 3. risk_state 판정 (atr_pct가 유효할 때만 연산, 결측 시 None)
    if atr_pct is not None:
        if atr_pct < 2.0:
            risk_state = "LOW"
            state_desc = "낮음"
        elif atr_pct < 4.0:
            risk_state = "NORMAL"
            state_desc = "보통"
        elif atr_pct < 7.0:
            risk_state = "HIGH"
            state_desc = "높음"
        else:
            risk_state = "VERY_HIGH"
            state_desc = "매우 높음"
    else:
        risk_state = None
        state_desc = None

    # 4. risk_reasons 생성 (최대 3개)
    risk_reasons = []
    if atr_available and atr_14 is not None and atr_pct is not None:
        risk_reasons.append(f"ATR 14일 {int(round(atr_14)):,}원, 현재가 대비 {atr_pct:.1f}%")
        if state_desc:
            risk_reasons.append(f"일평균 가격 변동성은 {state_desc} 수준")
    else:
        risk_reasons.append("고가/저가 OHLC 데이터 부족으로 ATR 연산 제외됨")

    risk_reasons.append(f"최근 {period_high_days}거래일 고점 대비 {drawdown_from_high_pct:+.1f}%")

    return {
        "available": True,
        "atr_14": int(round(atr_14)) if atr_14 is not None else None,
        "atr_pct": atr_pct,
        "atr_method": "SMA_14",
        "period_high": int(period_high),
        "period_high_days": period_high_days,
        "drawdown_from_high_pct": drawdown_from_high_pct,
        "risk_state": risk_state,
        "risk_reasons": risk_reasons[:3]
    }


def calculate_technical_indicators(
    df: pd.DataFrame, 
    benchmark_df: Any = None, 
    market: str = "KOSPI", 
    asset_type: str = "STOCK"
) -> Dict[str, Any]:
    """
    기술적 분석 지표 계산:
    - 5/20/60일 이동평균 (MA5, MA20, MA60)
    - RSI (14일)
    - MACD (12, 26, 9)
    - 거래량/거래대금 추세
    - 지지선 및 저항선 (최근 20일/60일 피봇 및 저가/고가 기준)
    - 상대강도 (Relative Strength)
    """
    if df.empty or len(df) < 5:
        return {"data_available": False, "error": "기술적 분석을 위한 데이터가 부족합니다."}

    df = df.copy()
    close = df['close_price'].astype(float)
    volume = df['volume'].astype(float)
    trading_val = df['trading_value'].astype(float) if ('trading_value' in df.columns and not df['trading_value'].empty) else (close * volume)

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

    # 7. 거래량 & 거래대금 상세 분석 (STEP 2.1: 당일 제외 직전 20일 평균 기준 & turnover_source 구분)
    if len(df) < 21:
        volume_analysis = {
            "available": False,
            "reason": "거래량/거래대금 분석을 위한 데이터 수량 부족 (최소 21일 이상 필요)"
        }
    else:
        latest_vol = float(volume.iloc[-1])
        has_tval = ('trading_value' in df.columns and not df['trading_value'].empty and not pd.isna(df['trading_value'].iloc[-1]))
        tval_series = trading_val if has_tval else (close * volume)
        turnover_source = "ACTUAL" if has_tval else "ESTIMATED"

        latest_tval = float(tval_series.iloc[-1])

        # 당일을 제외한 직전 20거래일 평균 (iloc[-21:-1])
        prev_v20_avg = float(volume.iloc[-21:-1].mean())
        prev_t20_avg = float(tval_series.iloc[-21:-1].mean())

        v_ratio = round(latest_vol / prev_v20_avg, 2) if prev_v20_avg > 0 else 1.0
        t_ratio = round(latest_tval / prev_t20_avg, 2) if prev_t20_avg > 0 else 1.0

        comb_ratio = (v_ratio + t_ratio) / 2.0

        if comb_ratio >= 2.0:
            v_state = "VERY_HIGH"
        elif comb_ratio >= 1.3:
            v_state = "HIGH"
        elif comb_ratio >= 0.7:
            v_state = "NORMAL"
        else:
            v_state = "LOW"

        v_reasons = [
            f"현재 거래량이 직전 20일 평균의 {v_ratio:.1f}배",
            f"현재 거래대금이 직전 20일 평균의 {t_ratio:.1f}배"
        ]
        if v_ratio >= 1.5 and t_ratio >= 1.5:
            v_reasons.append("거래량과 거래대금 모두 동반 급증")
        elif v_ratio < 0.7 and t_ratio < 0.7:
            v_reasons.append("거래량과 거래대금 모두 관망세 저조")

        volume_analysis = {
            "available": True,
            "volume_ratio": v_ratio,
            "turnover_ratio": t_ratio,
            "turnover_source": turnover_source,
            "volume_state": v_state,
            "volume_reasons": v_reasons[:3]
        }

    # 8. 시장 대비 상대강도 분석 (Relative Strength)
    relative_strength_analysis = calculate_relative_strength(
        df=df,
        benchmark_df=benchmark_df,
        market=market,
        asset_type=asset_type
    )

    # 9. 가격 리스크 분석 (ATR & Drawdown)
    risk_analysis = calculate_price_risk_analysis(df=df)

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
        "trend_analysis": trend_analysis,
        "volume_analysis": volume_analysis,
        "relative_strength_analysis": relative_strength_analysis,
        "risk_analysis": risk_analysis
    }

