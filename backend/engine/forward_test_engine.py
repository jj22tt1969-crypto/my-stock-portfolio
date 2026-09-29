import os
import sqlite3
import datetime
import statistics
from typing import List, Dict, Any, Optional

def get_connection():
    from backend.db.database import get_connection as get_db_conn
    return get_db_conn()

def get_cursor(conn, db_type):
    from backend.db.database import get_cursor as get_db_cur
    return get_db_cur(conn, db_type)

def init_forward_test_db():
    """Forward Test 독립 전용 DB 테이블 생성 및 Additive Migration (PostgreSQL / SQLite Dual 호환)"""
    conn, db_type = get_connection()
    cursor = get_cursor(conn, db_type)
    
    if db_type == "POSTGRESQL":
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forward_test_signals (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(50) NOT NULL,
                name VARCHAR(255) NOT NULL,
                asset_type VARCHAR(50) DEFAULT 'STOCK',
                signal_date VARCHAR(50) NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                original_decision VARCHAR(50) NOT NULL,
                final_decision VARCHAR(50) NOT NULL,
                fcs_score DOUBLE PRECISION,
                ffcs_score DOUBLE PRECISION,
                rsi DOUBLE PRECISION,
                rmi DOUBLE PRECISION,
                smart_score DOUBLE PRECISION,
                smart_grade VARCHAR(50),
                concurrency_code VARCHAR(50),
                ma60 DOUBLE PRECISION,
                ma120 DOUBLE PRECISION,
                is_ma_downtrend INTEGER DEFAULT 0,
                timing_signal VARCHAR(50),
                cross_status VARCHAR(50),
                data_source VARCHAR(100),
                timestamp_str VARCHAR(100),
                price_5d DOUBLE PRECISION,
                ret_5d DOUBLE PRECISION,
                status_5d VARCHAR(50) DEFAULT 'PENDING',
                price_10d DOUBLE PRECISION,
                ret_10d DOUBLE PRECISION,
                status_10d VARCHAR(50) DEFAULT 'PENDING',
                price_20d DOUBLE PRECISION,
                ret_20d DOUBLE PRECISION,
                status_20d VARCHAR(50) DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, signal_date)
            )
        """)
    else:
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

    # Forward Test 2.0 Additive Migration Columns Check & Execute
    existing_cols = set()
    try:
        cursor.execute("SELECT * FROM forward_test_signals LIMIT 0")
        if cursor.description:
            existing_cols = {desc[0].lower() for desc in cursor.description}
    except Exception:
        existing_cols = set()

    type_map = {
        "POSTGRESQL": {
            "TEXT": "VARCHAR(255)",
            "REAL": "DOUBLE PRECISION",
            "TIMESTAMP": "TIMESTAMP"
        },
        "SQLITE": {
            "TEXT": "TEXT",
            "REAL": "REAL",
            "TIMESTAMP": "TIMESTAMP"
        }
    }

    new_columns = [
        ("source_type", "TEXT DEFAULT 'MANUAL'"),
        ("data_as_of", "TEXT"),
        ("formula_version", "TEXT"),
        ("buy_score", "REAL"),
        ("sell_score", "REAL"),
        ("watering_score", "REAL"),
        ("mfi", "REAL"),
        ("trend_state", "TEXT"),
        ("trend_score", "REAL"),
        ("volume_state", "TEXT"),
        ("volume_ratio", "REAL"),
        ("flow_state", "TEXT"),
        ("rs_state", "TEXT"),
        ("rs_20d", "REAL"),
        ("risk_state", "TEXT"),
        ("atr_pct", "REAL"),
        ("evaluated_at", "TIMESTAMP"),
        ("max_gain", "REAL"),
        ("max_drawdown", "REAL"),
    ]

    for col_name, col_type_def in new_columns:
        if col_name.lower() not in existing_cols:
            try:
                base_type = col_type_def.split()[0]
                rest_def = col_type_def[len(base_type):]
                mapped_type = type_map[db_type].get(base_type, base_type) + rest_def
                cursor.execute(f"ALTER TABLE forward_test_signals ADD COLUMN {col_name} {mapped_type}")
                conn.commit()
            except Exception:
                pass

    conn.close()

def record_signal_snapshot(
    ticker: str,
    name: str,
    asset_type: str,
    price: float,
    analysis_data: Dict[str, Any],
    source_type: str = "MANUAL"
) -> bool:
    """
    신호 발생 시 당시의 모든 분석 지표를 스냅샷으로 독립 기록 (D0 Snapshot 2.0)
    - 미래 데이터 사용 금지 (Look-ahead bias = 0)
    - 동일 종목 동일 날짜 중복 스냅샷 방지
    """
    init_forward_test_db()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    def safe_float(val):
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    dec = analysis_data.get("decision", {}) if isinstance(analysis_data.get("decision"), dict) else {}
    flow = analysis_data.get("flow_analysis", {}) if isinstance(analysis_data.get("flow_analysis"), dict) else {}
    tech = analysis_data.get("technical_analysis", {}) if isinstance(analysis_data.get("technical_analysis"), dict) else {}
    timing = analysis_data.get("timing_analysis", {}) if isinstance(analysis_data.get("timing_analysis"), dict) else {}
    cross = analysis_data.get("cross_analysis", {}) if isinstance(analysis_data.get("cross_analysis"), dict) else {}
    meta = analysis_data.get("metadata", {}) if isinstance(analysis_data.get("metadata"), dict) else {}
    tf = dec.get("trend_filter", {}) if isinstance(dec.get("trend_filter"), dict) else {}

    orig_dec = dec.get("original_decision", dec.get("decision", "HOLD"))
    final_dec = dec.get("decision", "HOLD")

    # Subdicts
    trend_an = tech.get("trend_analysis", {}) if isinstance(tech.get("trend_analysis"), dict) else {}
    vol_an = tech.get("volume_analysis", {}) if isinstance(tech.get("volume_analysis"), dict) else {}
    rs_an = tech.get("relative_strength_analysis", {}) if isinstance(tech.get("relative_strength_analysis"), dict) else {}
    risk_an = tech.get("risk_analysis", {}) if isinstance(tech.get("risk_analysis"), dict) else {}
    smart_an = flow.get("smart_analysis", {}) or analysis_data.get("smart_analysis", {}) or analysis_data.get("smart_score", {})
    if not isinstance(smart_an, dict):
        smart_an = {}

    # Safe Extraction: Missing -> None/NULL (No false 0 / 50 defaults)
    data_as_of = analysis_data.get("data_as_of") or (meta.get("updated_at") if isinstance(meta, dict) else None) or flow.get("last_updated")
    formula_version = None

    buy_score = safe_float(dec.get("buy_score"))
    sell_score = safe_float(dec.get("sell_score"))
    watering_score = safe_float(dec.get("watering_score"))

    mfi = safe_float(tech.get("mfi"))

    trend_state = trend_an.get("trend_state") or tech.get("trend_state")
    trend_score = safe_float(trend_an.get("trend_score") if trend_an.get("trend_score") is not None else tech.get("trend_score"))

    volume_state = vol_an.get("volume_state") or tech.get("volume_state")
    vol_ratio_val = vol_an.get("volume_ratio") if vol_an.get("volume_ratio") is not None else tech.get("volume_ratio")
    volume_ratio = safe_float(vol_ratio_val)

    flow_state = flow.get("flow_state")

    rs_state = rs_an.get("rs_state") or tech.get("rs_state")
    rs_20d = safe_float(rs_an.get("rs_20d") if rs_an.get("rs_20d") is not None else tech.get("rs_20d"))

    risk_state = risk_an.get("risk_state") or tech.get("risk_state")
    atr_pct = safe_float(risk_an.get("atr_pct") if risk_an.get("atr_pct") is not None else tech.get("atr_pct"))

    s_score_val = smart_an.get("score") if smart_an.get("score") is not None else (
        smart_an.get("smart_score") if smart_an.get("smart_score") is not None else None
    )
    smart_score = safe_float(s_score_val)
    smart_grade = smart_an.get("signal_grade") or smart_an.get("grade") or smart_an.get("smart_grade")

    fcs_score = safe_float(flow.get("fcs_score"))
    ffcs_score = safe_float(flow.get("ffcs_score"))
    rsi = safe_float(tech.get("rsi"))
    rmi = safe_float(tech.get("rmi"))
    ma60 = safe_float(tech.get("ma60"))
    ma120 = safe_float(tech.get("ma120"))

    concurrency_code = flow.get("concurrency", {}).get("code", "NONE") if isinstance(flow.get("concurrency"), dict) else "NONE"

    conn, db_type = get_connection()
    cursor = get_cursor(conn, db_type)

    try:
        if db_type == "POSTGRESQL":
            sql = """
                INSERT INTO forward_test_signals (
                    ticker, name, asset_type, signal_date, price,
                    original_decision, final_decision,
                    fcs_score, ffcs_score, rsi, rmi,
                    smart_score, smart_grade, concurrency_code,
                    ma60, ma120, is_ma_downtrend, timing_signal, cross_status,
                    data_source, timestamp_str,
                    source_type, data_as_of, formula_version,
                    buy_score, sell_score, watering_score,
                    mfi, trend_state, trend_score, volume_state, volume_ratio,
                    flow_state, rs_state, rs_20d, risk_state, atr_pct
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (ticker, signal_date) DO NOTHING
            """
        else:
            sql = """
                INSERT OR IGNORE INTO forward_test_signals (
                    ticker, name, asset_type, signal_date, price,
                    original_decision, final_decision,
                    fcs_score, ffcs_score, rsi, rmi,
                    smart_score, smart_grade, concurrency_code,
                    ma60, ma120, is_ma_downtrend, timing_signal, cross_status,
                    data_source, timestamp_str,
                    source_type, data_as_of, formula_version,
                    buy_score, sell_score, watering_score,
                    mfi, trend_state, trend_score, volume_state, volume_ratio,
                    flow_state, rs_state, rs_20d, risk_state, atr_pct
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
            """
        cursor.execute(sql, (
            ticker, name, asset_type or 'STOCK', today_str, float(price),
            orig_dec, final_dec,
            fcs_score, ffcs_score, rsi, rmi,
            smart_score, smart_grade,
            concurrency_code,
            ma60, ma120,
            1 if tf.get("active", False) else 0,
            timing.get("timing_signal", "NEUTRAL"),
            cross.get("status_label", "정상"),
            "실시간 QUANT API",
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source_type or 'MANUAL', data_as_of, formula_version,
            buy_score, sell_score, watering_score,
            mfi, trend_state, trend_score, volume_state, volume_ratio,
            flow_state, rs_state, rs_20d, risk_state, atr_pct
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False

def delete_signal_snapshot(signal_id: int) -> bool:
    """Forward Test 신호 스냅샷 삭제 (ID 기반)"""
    init_forward_test_db()
    conn, db_type = get_connection()
    cursor = get_cursor(conn, db_type)
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    try:
        cursor.execute(f"DELETE FROM forward_test_signals WHERE id = {ph}", (signal_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        conn.close()
        return False

def evaluate_forward_outcomes() -> Dict[str, Any]:
    """
    저장된 스냅샷에 대해 실제 미래 가격(5D/10D/20D 후)을 추적하여 수익률 자동 업데이트
    - 데이터 부족 시 추정 금지, PENDING 상태 유지
    """
    init_forward_test_db()
    conn, db_type = get_connection()
    cursor = get_cursor(conn, db_type)
    ph = "%s" if db_type == "POSTGRESQL" else "?"

    cursor.execute("""
        SELECT * FROM forward_test_signals
        WHERE status_5d = 'PENDING' OR status_10d = 'PENDING' OR status_20d = 'PENDING' OR (status_20d = 'COMPLETED' AND max_drawdown IS NULL)
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
        base_price = float(row["price"])

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
        is_20d_completed = row["status_20d"] == 'COMPLETED' or (row["status_20d"] == 'PENDING' and days_after >= 20)
        if row["status_20d"] == 'PENDING' and days_after >= 20:
            p20 = float(after_df.iloc[19]["close_price"])
            ret20 = ((p20 - base_price) / base_price) * 100.0
            up_dict["price_20d"] = p20
            up_dict["ret_20d"] = round(ret20, 2)
            up_dict["status_20d"] = 'COMPLETED'

        # max_gain & max_drawdown (D+20까지 성숙한 CASE에만 계산)
        if is_20d_completed and days_after >= 20 and (row.get("max_drawdown") is None or "status_20d" in up_dict):
            p_list = [base_price] + [float(x) for x in after_df.iloc[:20]["close_price"]]
            max_p = max(p_list)
            max_gain_val = round(((max_p - base_price) / base_price) * 100.0, 2)

            peak = p_list[0]
            max_dd_val = 0.0
            for p in p_list:
                if p > peak:
                    peak = p
                dd = ((p - peak) / peak) * 100.0
                if dd < max_dd_val:
                    max_dd_val = dd
            max_drawdown_val = round(max_dd_val, 2)

            up_dict["max_gain"] = max_gain_val
            up_dict["max_drawdown"] = max_drawdown_val
            up_dict["evaluated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if up_dict:
            set_clause = ", ".join([f"{k} = {ph}" for k in up_dict.keys()])
            values = list(up_dict.values()) + [row["id"]]
            cursor.execute(f"UPDATE forward_test_signals SET {set_clause} WHERE id = {ph}", values)
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
    conn, db_type = get_connection()
    cursor = get_cursor(conn, db_type)

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
    # 1) 외인기관 쌍끌이 순매수(BOTH_BUY)
    core_1 = [r for r in rows if r.get("concurrency_code") == "BOTH_BUY"]
    # 2) MA60/120 역배열 + 동시 순매도(BOTH_SELL)
    core_2 = [r for r in rows if r.get("is_ma_downtrend") == 1 and r.get("concurrency_code") == "BOTH_SELL"]
    # 3) MA60/120 필터로 BUY -> HOLD 된 경우
    core_3 = [r for r in rows if r.get("original_decision") in ["BUY", "AVERAGE"] and r.get("final_decision") == "HOLD"]

    core_signal_stats = {
        "smart_both_buy": {
            "name": "1. 외인기관 쌍끌이 순매수(BOTH_BUY)",
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

    # 4. Forward Test Renewal F3C-1 Additive Read Model (performance_v2)
    def calc_horizon_perf(status_key, ret_key):
        completed = [r for r in rows if r.get(status_key) == 'COMPLETED' and r.get(ret_key) is not None]
        completed_cnt = len(completed)
        pos_cnt = len([r for r in completed if r[ret_key] > 0])
        neg_cnt = len([r for r in completed if r[ret_key] < 0])
        flat_cnt = len([r for r in completed if r[ret_key] == 0])
        denom = pos_cnt + neg_cnt
        pos_rate = round((pos_cnt / denom) * 100.0, 2) if denom > 0 else None
        return {
            "completed_count": completed_cnt,
            "positive_count": pos_cnt,
            "negative_count": neg_cnt,
            "flat_count": flat_cnt,
            "positive_return_rate": pos_rate
        }

    def calc_decision_acc(status_key, ret_key):
        completed = [r for r in rows if r.get(status_key) == 'COMPLETED' and r.get(ret_key) is not None]
        correct_cnt = 0
        wrong_cnt = 0
        flat_cnt = 0
        non_dir_cnt = 0
        for r in completed:
            dec = r.get("final_decision")
            ret = r.get(ret_key)
            if dec in ["HOLD", "TAKE_PROFIT"]:
                non_dir_cnt += 1
            elif dec in ["BUY", "AVERAGE"]:
                if ret > 0:
                    correct_cnt += 1
                elif ret < 0:
                    wrong_cnt += 1
                else:
                    flat_cnt += 1
            elif dec == "REDUCE":
                if ret < 0:
                    correct_cnt += 1
                elif ret > 0:
                    wrong_cnt += 1
                else:
                    flat_cnt += 1
            else:
                non_dir_cnt += 1
        eligible_cnt = correct_cnt + wrong_cnt
        acc_pct = round((correct_cnt / eligible_cnt) * 100.0, 2) if eligible_cnt > 0 else None
        return {
            "eligible_count": eligible_cnt,
            "correct_count": correct_cnt,
            "wrong_count": wrong_cnt,
            "flat_count": flat_cnt,
            "non_directional_count": non_dir_cnt,
            "accuracy_pct": acc_pct
        }

    def calc_action_perf(action_name, status_key, ret_key):
        act_rows = [r for r in rows if r.get("final_decision") == action_name and r.get(status_key) == 'COMPLETED' and r.get(ret_key) is not None]
        sample_cnt = len(act_rows)
        if sample_cnt == 0:
            return {
                "sample_count": 0,
                "avg_return": None,
                "median_return": None,
                "positive_return_rate": None,
                "direction_accuracy": None
            }
        rets = [r[ret_key] for r in act_rows]
        avg_ret = round(sum(rets) / len(rets), 2)
        med_ret = round(statistics.median(rets), 2)
        pos_cnt = len([r for r in rets if r > 0])
        neg_cnt = len([r for r in rets if r < 0])
        denom = pos_cnt + neg_cnt
        pos_rate = round((pos_cnt / denom) * 100.0, 2) if denom > 0 else None

        dir_acc = None
        if action_name in ["BUY", "AVERAGE"]:
            dir_acc = pos_rate
        elif action_name == "REDUCE":
            dir_acc = round((neg_cnt / denom) * 100.0, 2) if denom > 0 else None

        return {
            "sample_count": sample_cnt,
            "avg_return": avg_ret,
            "median_return": med_ret,
            "positive_return_rate": pos_rate,
            "direction_accuracy": dir_acc
        }

    def calc_data_quality(status_key, ret_key):
        total = len(rows)
        pending_cnt = len([r for r in rows if r.get(status_key) == 'PENDING'])
        completed_cnt = len([r for r in rows if r.get(status_key) == 'COMPLETED'])
        null_cnt = len([r for r in rows if r.get(status_key) == 'COMPLETED' and r.get(ret_key) is None])
        flat_cnt = len([r for r in rows if r.get(status_key) == 'COMPLETED' and r.get(ret_key) == 0])
        insufficient_cnt = pending_cnt + null_cnt
        return {
            "total_signals": total,
            "pending_count": pending_cnt,
            "completed_count": completed_cnt,
            "null_count": null_cnt,
            "excluded_flat_count": flat_cnt,
            "excluded_data_insufficient_count": insufficient_cnt
        }

    actions = ["BUY", "AVERAGE", "HOLD", "TAKE_PROFIT", "REDUCE"]
    horizons = [("5D", "status_5d", "ret_5d"), ("10D", "status_10d", "ret_10d"), ("20D", "status_20d", "ret_20d")]

    horizon_perf = {}
    decision_acc = {}
    data_qual = {}
    for h_label, s_key, r_key in horizons:
        horizon_perf[h_label] = calc_horizon_perf(s_key, r_key)
        decision_acc[h_label] = calc_decision_acc(s_key, r_key)
        data_qual[h_label] = calc_data_quality(s_key, r_key)

    action_perf = {}
    for act in actions:
        action_perf[act] = {}
        for h_label, s_key, r_key in horizons:
            action_perf[act][h_label] = calc_action_perf(act, s_key, r_key)

    # 5. Forward Test Renewal F3C-2 Additive Read Model (Score Calibration & Feature Performance)
    def calc_spearman_corr(x_list: List[float], y_list: List[float]) -> Optional[float]:
        n = len(x_list)
        if n < 3:
            return None

        def get_ranks(val_list):
            sorted_indices = sorted(range(len(val_list)), key=lambda k: val_list[k])
            ranks = [0.0] * len(val_list)
            i = 0
            while i < len(sorted_indices):
                j = i
                while j < len(sorted_indices) and val_list[sorted_indices[j]] == val_list[sorted_indices[i]]:
                    j += 1
                avg_rank = (i + 1 + j) / 2.0
                for k in range(i, j):
                    ranks[sorted_indices[k]] = avg_rank
                i = j
            return ranks

        rx = get_ranks(x_list)
        ry = get_ranks(y_list)

        mean_rx = sum(rx) / n
        mean_ry = sum(ry) / n

        num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
        den_x = sum((rx[i] - mean_rx) ** 2 for i in range(n))
        den_y = sum((ry[i] - mean_ry) ** 2 for i in range(n))

        if den_x == 0 or den_y == 0:
            return None

        r = num / ((den_x * den_y) ** 0.5)
        return round(r, 4)

    def calc_score_calibration(score_key, status_key, ret_key):
        valid_items = []
        for r in rows:
            if r.get(status_key) == 'COMPLETED' and r.get(ret_key) is not None and r.get(score_key) is not None:
                try:
                    val = float(r[score_key])
                    ret = float(r[ret_key])
                    valid_items.append((val, ret))
                except (ValueError, TypeError):
                    pass

        sample_cnt = len(valid_items)
        if sample_cnt == 0:
            return {
                "sample_count": 0,
                "min": None,
                "max": None,
                "average": None,
                "avg_return": None,
                "median_return": None,
                "positive_return_rate": None,
                "spearman_correlation": None
            }

        scores = [item[0] for item in valid_items]
        returns = [item[1] for item in valid_items]

        score_min = round(min(scores), 2)
        score_max = round(max(scores), 2)
        score_avg = round(sum(scores) / len(scores), 2)

        avg_ret = round(sum(returns) / len(returns), 2)
        med_ret = round(statistics.median(returns), 2)

        pos_rets = [r for r in returns if r > 0]
        neg_rets = [r for r in returns if r < 0]
        pos_denom = len(pos_rets) + len(neg_rets)
        pos_rate = round((len(pos_rets) / pos_denom) * 100.0, 2) if pos_denom > 0 else None

        spearman_corr = calc_spearman_corr(scores, returns)

        return {
            "sample_count": sample_cnt,
            "min": score_min,
            "max": score_max,
            "average": score_avg,
            "avg_return": avg_ret,
            "median_return": med_ret,
            "positive_return_rate": pos_rate,
            "spearman_correlation": spearman_corr
        }

    def calc_feature_performance(feature_key, status_key, ret_key):
        unique_states = sorted(list({str(r[feature_key]) for r in rows if r.get(feature_key) is not None and str(r[feature_key]).strip() != ""}))
        result_by_state = {}
        for state_val in unique_states:
            state_rows = [r for r in rows if str(r.get(feature_key)) == state_val and r.get(status_key) == 'COMPLETED' and r.get(ret_key) is not None]
            sample_cnt = len(state_rows)
            if sample_cnt == 0:
                result_by_state[state_val] = {
                    "sample_count": 0,
                    "avg_return": None,
                    "median_return": None,
                    "positive_return_rate": None,
                    "directional_accuracy": None
                }
                continue

            rets = [r[ret_key] for r in state_rows]
            avg_ret = round(sum(rets) / len(rets), 2)
            med_ret = round(statistics.median(rets), 2)

            pos_rets = [r for r in rets if r > 0]
            neg_rets = [r for r in rets if r < 0]
            pos_denom = len(pos_rets) + len(neg_rets)
            pos_rate = round((len(pos_rets) / pos_denom) * 100.0, 2) if pos_denom > 0 else None

            dir_correct = 0
            dir_wrong = 0
            for r in state_rows:
                dec = r.get("final_decision")
                ret = r.get(ret_key)
                if dec in ["BUY", "AVERAGE"]:
                    if ret > 0: dir_correct += 1
                    elif ret < 0: dir_wrong += 1
                elif dec == "REDUCE":
                    if ret < 0: dir_correct += 1
                    elif ret > 0: dir_wrong += 1

            dir_denom = dir_correct + dir_wrong
            dir_acc = round((dir_correct / dir_denom) * 100.0, 2) if dir_denom > 0 else None

            result_by_state[state_val] = {
                "sample_count": sample_cnt,
                "avg_return": avg_ret,
                "median_return": med_ret,
                "positive_return_rate": pos_rate,
                "directional_accuracy": dir_acc
            }

        return result_by_state

    score_keys = ["buy_score", "sell_score", "watering_score", "ffcs_score", "trend_score", "rs_20d", "volume_ratio", "atr_pct"]
    feature_keys = ["trend_state", "volume_state", "flow_state", "rs_state", "risk_state"]

    score_calibration = {}
    for skey in score_keys:
        score_calibration[skey] = {}
        for h_label, s_key, r_key in horizons:
            score_calibration[skey][h_label] = calc_score_calibration(skey, s_key, r_key)

    feature_performance = {}
    for fkey in feature_keys:
        feature_performance[fkey] = {}
        for h_label, s_key, r_key in horizons:
            feature_performance[fkey][h_label] = calc_feature_performance(fkey, s_key, r_key)

    performance_v2 = {
        "horizon_performance": horizon_perf,
        "decision_accuracy": decision_acc,
        "action_performance": action_perf,
        "data_quality": data_qual,
        "score_calibration": score_calibration,
        "feature_performance": feature_performance
    }

    recent_rows = [dict(r) for r in rows[:20]]
    if recent_rows:
        try:
            from backend.data.collector import fetch_naver_realtime_price
            import time
            from concurrent.futures import ThreadPoolExecutor

            global _REALTIME_PRICE_CACHE
            if '_REALTIME_PRICE_CACHE' not in globals():
                _REALTIME_PRICE_CACHE = {}

            now_ts = time.time()
            unique_tickers = list({r["ticker"] for r in recent_rows if r.get("ticker")})
            prices_map = {}

            tickers_to_fetch = []
            for t in unique_tickers:
                if t in _REALTIME_PRICE_CACHE:
                    c_time, c_price = _REALTIME_PRICE_CACHE[t]
                    if now_ts - c_time < 60:
                        prices_map[t] = c_price
                        continue
                tickers_to_fetch.append(t)

            if tickers_to_fetch:
                def _get_price(t):
                    try:
                        res = fetch_naver_realtime_price(t)
                        if res and res.get("current_price"):
                            return t, int(res["current_price"])
                    except Exception:
                        pass
                    return t, None

                with ThreadPoolExecutor(max_workers=min(10, len(tickers_to_fetch))) as executor:
                    results = executor.map(_get_price, tickers_to_fetch)
                    for t, p in results:
                        if p is not None:
                            prices_map[t] = p
                            _REALTIME_PRICE_CACHE[t] = (now_ts, p)

            for r in recent_rows:
                r["current_price"] = prices_map.get(r.get("ticker"))
        except Exception:
            for r in recent_rows:
                r["current_price"] = None

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
        "recent_signals": recent_rows,  # 최근 20개 신호 스냅샷 (현재가격 포함)
        "performance_v2": performance_v2
    }

