import os
import sqlite3
import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "portfolio.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_forward_test_db():
    """Forward Test 독립 전용 DB 테이블 생성"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forward_test_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            asset_type TEXT DEFAULT 'STOCK',
            signal_date TEXT NOT NULL,
            price REAL NOT NULL,
            original_decision TEXT NOT NULL,
            final_decision TEXT NOT NULL,
            fcs_score REAL,
            ffcs_score REAL,
            rsi REAL,
            rmi REAL,
            smart_score REAL,
            smart_grade TEXT,
            concurrency_code TEXT,
            ma60 REAL,
            ma120 REAL,
            is_ma_downtrend INTEGER DEFAULT 0,
            timing_signal TEXT,
            cross_status TEXT,
            data_source TEXT,
            timestamp_str TEXT,
            price_5d REAL,
            ret_5d REAL,
            status_5d TEXT DEFAULT 'PENDING',
            price_10d REAL,
            ret_10d REAL,
            status_10d TEXT DEFAULT 'PENDING',
            price_20d REAL,
            ret_20d REAL,
            status_20d TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, signal_date)
        )
    """)
    conn.commit()
    conn.close()

def record_signal_snapshot(
    ticker: str,
    name: str,
    asset_type: str,
    price: float,
    analysis_data: Dict[str, Any]
) -> bool:
    """
    신호 발생 시 당시의 모든 분석 지표를 스냅샷으로 독립 기록
    - 미래 데이터 사용 금지 (Look-ahead bias = 0)
    - 동일 종목 동일 날짜 중복 스냅샷 방지
    """
    init_forward_test_db()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    dec = analysis_data.get("decision", {})
    flow = analysis_data.get("flow_analysis", {})
    tech = analysis_data.get("technical_analysis", {})
    timing = analysis_data.get("timing_analysis", {})
    smart = analysis_data.get("smart_flow_analysis", {})
    cross = analysis_data.get("cross_analysis", {})
    tf = dec.get("trend_filter", {})

    orig_dec = dec.get("original_decision", dec.get("decision", "HOLD"))
    final_dec = dec.get("decision", "HOLD")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR IGNORE INTO forward_test_signals (
                ticker, name, asset_type, signal_date, price,
                original_decision, final_decision,
                fcs_score, ffcs_score, rsi, rmi,
                smart_score, smart_grade, concurrency_code,
                ma60, ma120, is_ma_downtrend, timing_signal, cross_status,
                data_source, timestamp_str
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, name, asset_type or 'STOCK', today_str, float(price),
            orig_dec, final_dec,
            float(flow.get("fcs_score", 50.0)),
            float(flow.get("ffcs_score", 50.0)),
            float(tech.get("rsi", 50.0)),
            float(tech.get("rmi", 50.0)),
            float(smart.get("score", 50.0)) if smart.get("score") is not None else None,
            smart.get("signal_grade", "NEUTRAL"),
            flow.get("concurrency", {}).get("code", "NONE"),
            float(tech.get("ma60", 0.0)) if tech.get("ma60") else None,
            float(tech.get("ma120", 0.0)) if tech.get("ma120") else None,
            1 if tf.get("active", False) else 0,
            timing.get("timing_signal", "NEUTRAL"),
            cross.get("status_label", "정상"),
            "실시간 QUANT API",
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False

def evaluate_forward_outcomes() -> Dict[str, Any]:
    """
    저장된 스냅샷에 대해 실제 미래 가격(5D/10D/20D 후)을 추적하여 수익률 자동 업데이트
    - 데이터 부족 시 추정 금지, PENDING 상태 유지
    """
    init_forward_test_db()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM forward_test_signals
        WHERE status_5d = 'PENDING' OR status_10d = 'PENDING' OR status_20d = 'PENDING'
    """)
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return {"updated_count": 0}

    from backend.data.collector import get_stock_flow_data
    updated_count = 0

    for row in rows:
        ticker = row["ticker"]
        sig_date_str = row["signal_date"]
        base_price = row["price"]

        flow_info = get_stock_flow_data(ticker, min_days=40)
        if not flow_info.get("data_available"):
            continue

        df = flow_info["df"]
        if df.empty or len(df) < 5:
            continue

        # sig_date 이후의 데이터 추출
        df['date_str'] = df['date'].astype(str)
        after_df = df[df['date_str'] > sig_date_str]
        days_after = len(after_df)

        up_dict = {}

        # 5거래일 경과 평가
        if row["status_5d"] == 'PENDING' and days_after >= 5:
            p5 = float(after_df.iloc[4]["close_price"])
            ret5 = ((p5 - base_price) / base_price) * 100.0
            up_dict["price_5d"] = p5
            up_dict["ret_5d"] = round(ret5, 2)
            up_dict["status_5d"] = 'COMPLETED'

        # 10거래일 경과 평가
        if row["status_10d"] == 'PENDING' and days_after >= 10:
            p10 = float(after_df.iloc[9]["close_price"])
            ret10 = ((p10 - base_price) / base_price) * 100.0
            up_dict["price_10d"] = p10
            up_dict["ret_10d"] = round(ret10, 2)
            up_dict["status_10d"] = 'COMPLETED'

        # 20거래일 경과 평가
        if row["status_20d"] == 'PENDING' and days_after >= 20:
            p20 = float(after_df.iloc[19]["close_price"])
            ret20 = ((p20 - base_price) / base_price) * 100.0
            up_dict["price_20d"] = p20
            up_dict["ret_20d"] = round(ret20, 2)
            up_dict["status_20d"] = 'COMPLETED'

        if up_dict:
            set_clause = ", ".join([f"{k} = ?" for k in up_dict.keys()])
            values = list(up_dict.values()) + [row["id"]]
            cursor.execute(f"UPDATE forward_test_signals SET {set_clause} WHERE id = ?", values)
            updated_count += 1

    conn.commit()
    conn.close()
    return {"updated_count": updated_count}

def get_forward_test_dashboard_stats() -> Dict[str, Any]:
    """
    Forward Test 대시보드 통계 연산
    - 누적 신호 수
    - 완료된 5D / 10D / 20D 표본 수
    - BUY / HOLD / REDUCE 승률, 평균수익률, 최대손실
    - 핵심 3대 신호별 5D/10D/20D 성과
    - STOCK vs ETF 성과 비교
    """
    init_forward_test_db()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM forward_test_signals ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_signals = len(rows)

    def calc_period_stats(item_list, status_key, ret_key):
        completed = [item for item in item_list if item.get(status_key) == 'COMPLETED']
        cnt = len(completed)
        if cnt == 0:
            return {"sample_count": 0, "win_rate": 0.0, "avg_return": 0.0, "max_profit": 0.0, "max_loss": 0.0}

        rets = [item[ret_key] for item in completed if item.get(ret_key) is not None]
        if not rets:
            return {"sample_count": 0, "win_rate": 0.0, "avg_return": 0.0, "max_profit": 0.0, "max_loss": 0.0}

        wins = [r for r in rets if r > 0]
        win_rate = (len(wins) / len(rets)) * 100.0
        avg_ret = sum(rets) / len(rets)
        max_prof = max(rets)
        max_l = min(rets)

        return {
            "sample_count": cnt,
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
            "max_profit": round(max_prof, 2),
            "max_loss": round(max_l, 2)
        }

    # 1. 종합 신호별 성과 (BUY/AVERAGE vs HOLD vs REDUCE)
    buy_signals = [r for r in rows if r["final_decision"] in ["BUY", "AVERAGE"]]
    hold_signals = [r for r in rows if r["final_decision"] == "HOLD"]
    reduce_signals = [r for r in rows if r["final_decision"] == "REDUCE"]

    decision_stats = {
        "BUY": {
            "5D": calc_period_stats(buy_signals, "status_5d", "ret_5d"),
            "10D": calc_period_stats(buy_signals, "status_10d", "ret_10d"),
            "20D": calc_period_stats(buy_signals, "status_20d", "ret_20d")
        },
        "HOLD": {
            "5D": calc_period_stats(hold_signals, "status_5d", "ret_5d"),
            "10D": calc_period_stats(hold_signals, "status_10d", "ret_10d"),
            "20D": calc_period_stats(hold_signals, "status_20d", "ret_20d")
        },
        "REDUCE": {
            "5D": calc_period_stats(reduce_signals, "status_5d", "ret_5d"),
            "10D": calc_period_stats(reduce_signals, "status_10d", "ret_10d"),
            "20D": calc_period_stats(reduce_signals, "status_20d", "ret_20d")
        }
    }

    # 2. 핵심 3대 신호 추적
    # 1) Smart Money 우위 (score >= 60 또는 BUY/STRONG_BUY) + BOTH_BUY
    core_1 = [r for r in rows if (r.get("smart_score", 0) or 0) >= 60.0 and r.get("concurrency_code") == "BOTH_BUY"]
    # 2) MA60/120 역배열 + BOTH_SELL
    core_2 = [r for r in rows if r.get("is_ma_downtrend") == 1 and r.get("concurrency_code") == "BOTH_SELL"]
    # 3) MA60/120 필터로 BUY -> HOLD 된 경우
    core_3 = [r for r in rows if r.get("original_decision") in ["BUY", "AVERAGE"] and r.get("final_decision") == "HOLD"]

    core_signal_stats = {
        "smart_both_buy": {
            "name": "1. Smart Money 우위 + 외인기관 쌍끌이(BOTH_BUY)",
            "count": len(core_1),
            "5D": calc_period_stats(core_1, "status_5d", "ret_5d"),
            "10D": calc_period_stats(core_1, "status_10d", "ret_10d"),
            "20D": calc_period_stats(core_1, "status_20d", "ret_20d")
        },
        "downtrend_both_sell": {
            "name": "2. MA60/120 역배열 + 동시 순매도(BOTH_SELL)",
            "count": len(core_2),
            "5D": calc_period_stats(core_2, "status_5d", "ret_5d"),
            "10D": calc_period_stats(core_2, "status_10d", "ret_10d"),
            "20D": calc_period_stats(core_2, "status_20d", "ret_20d")
        },
        "ma_trend_restricted": {
            "name": "3. MA60/120 역배열 BUY ➔ HOLD 억제",
            "count": len(core_3),
            "5D": calc_period_stats(core_3, "status_5d", "ret_5d"),
            "10D": calc_period_stats(core_3, "status_10d", "ret_10d"),
            "20D": calc_period_stats(core_3, "status_20d", "ret_20d")
        }
    }

    # 3. STOCK vs ETF 성과 비교
    stock_rows = [r for r in rows if r.get("asset_type") == 'STOCK' and r["final_decision"] in ["BUY", "AVERAGE"]]
    etf_rows = [r for r in rows if r.get("asset_type") == 'ETF' and r["final_decision"] in ["BUY", "AVERAGE"]]

    asset_type_stats = {
        "STOCK": {
            "5D": calc_period_stats(stock_rows, "status_5d", "ret_5d"),
            "10D": calc_period_stats(stock_rows, "status_10d", "ret_10d"),
            "20D": calc_period_stats(stock_rows, "status_20d", "ret_20d")
        },
        "ETF": {
            "5D": calc_period_stats(etf_rows, "status_5d", "ret_5d"),
            "10D": calc_period_stats(etf_rows, "status_10d", "ret_10d"),
            "20D": calc_period_stats(etf_rows, "status_20d", "ret_20d")
        }
    }

    completed_5d_cnt = len([r for r in rows if r.get("status_5d") == 'COMPLETED'])
    completed_10d_cnt = len([r for r in rows if r.get("status_10d") == 'COMPLETED'])
    completed_20d_cnt = len([r for r in rows if r.get("status_20d") == 'COMPLETED'])

    return {
        "total_signals": total_signals,
        "completed_samples": {
            "5D": completed_5d_cnt,
            "10D": completed_10d_cnt,
            "20D": completed_20d_cnt
        },
        "decision_stats": decision_stats,
        "core_signal_stats": core_signal_stats,
        "asset_type_stats": asset_type_stats,
        "recent_signals": rows[:20]  # 최근 20개 신호 스냅샷
    }
