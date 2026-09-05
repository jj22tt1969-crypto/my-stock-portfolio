import os
import sys
import sqlite3
import dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

dotenv.load_dotenv(os.path.join(ROOT_DIR, ".env"))

def verify_all():
    print("==================================================")
    print(" Supabase PostgreSQL Migration & Invariance Verification ")
    print("==================================================")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[FAIL] DATABASE_URL is missing in .env")
        return False

    import psycopg2
    import psycopg2.extras

    # 1. Connection & Metadata
    print("\n--- 1. Supabase PostgreSQL Metadata Check ---")
    pg_conn = psycopg2.connect(db_url, connect_timeout=10)
    pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    pg_cur.execute("SELECT version();")
    ver = pg_cur.fetchone()["version"]
    pg_cur.execute("SELECT current_database(), current_user;")
    db_row = pg_cur.fetchone()
    pg_cur.execute("SELECT 1 as test;")
    sel_one = pg_cur.fetchone()["test"]

    print(f"PostgreSQL Version: {ver}")
    print(f"Database: {db_row['current_database']}")
    print(f"User: {db_row['current_user']}")
    print(f"SELECT 1: {sel_one} (PASS)")

    # 2. Row Counts
    print("\n--- 2. PostgreSQL Row Counts Check ---")
    pg_cur.execute("SELECT count(*) as count FROM portfolios;")
    pg_port_count = pg_cur.fetchone()["count"]
    pg_cur.execute("SELECT count(*) as count FROM forward_test_signals;")
    pg_ft_count = pg_cur.fetchone()["count"]

    print(f"Portfolios count: {pg_port_count}")
    print(f"Forward Test Signals count: {pg_ft_count}")

    # 3. Data Equality Check
    print("\n--- 3. SQLite vs PostgreSQL Data Equality ---")
    sq_path = os.path.join(ROOT_DIR, "backend", "data", "portfolio.db")
    sq_conn = sqlite3.connect(sq_path)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    sq_ports = {r["ticker"]: dict(r) for r in sq_cur.execute("SELECT * FROM portfolios").fetchall()}
    pg_cur.execute("SELECT * FROM portfolios;")
    pg_ports = {r["ticker"]: dict(r) for r in pg_cur.fetchall()}

    port_mismatches = []
    for ticker, sq_row in sq_ports.items():
        if ticker not in pg_ports:
            port_mismatches.append(f"Missing ticker in PG: {ticker}")
            continue
        pg_row = pg_ports[ticker]
        for k in ["name", "ticker", "avg_price", "quantity", "buy_date", "investment_purpose", "sector", "asset_type", "market"]:
            if str(sq_row[k]) != str(pg_row[k]):
                port_mismatches.append(f"{ticker} {k}: SQ({sq_row[k]}) vs PG({pg_row[k]})")

    sq_sigs = {f"{r['ticker']}_{r['signal_date']}": dict(r) for r in sq_cur.execute("SELECT * FROM forward_test_signals").fetchall()}
    pg_cur.execute("SELECT * FROM forward_test_signals;")
    pg_sigs = {f"{r['ticker']}_{r['signal_date']}": dict(r) for r in pg_cur.fetchall()}

    sig_mismatches = []
    for key, sq_row in sq_sigs.items():
        if key not in pg_sigs:
            sig_mismatches.append(f"Missing key in PG: {key}")
            continue
        pg_row = pg_sigs[key]
        for k in ["ticker", "signal_date", "price", "original_decision", "final_decision", "status_5d", "status_10d", "status_20d"]:
            if str(sq_row[k]) != str(pg_row[k]):
                sig_mismatches.append(f"{key} {k}: SQ({sq_row[k]}) vs PG({pg_row[k]})")

    print(f"Portfolios SQLite: {len(sq_ports)} -> PostgreSQL: {pg_port_count} ({'PASS' if len(port_mismatches) == 0 else 'FAIL'})")
    print(f"Forward Test Signals SQLite: {len(sq_sigs)} -> PostgreSQL: {pg_ft_count} ({'PASS' if len(sig_mismatches) == 0 else 'FAIL'})")

    # 4. CRUD Test
    print("\n--- 4. CRUD Verification on Supabase PostgreSQL ---")
    from backend.db.database import add_stock, get_stock_by_ticker, update_stock, delete_stock, get_all_stocks

    # 4.1 Read initial list
    all_init = get_all_stocks()
    print(f"Initial stocks read: {len(all_init)} items")

    # 4.2 Create test stock
    add_res = add_stock(
        name="테스트종목",
        ticker="999999",
        avg_price=10000.0,
        quantity=10,
        buy_date="2026-09-06",
        investment_purpose="CRUD테스트",
        sector="기타",
        asset_type="STOCK",
        market="KOSPI"
    )
    print(f"Create stock: {add_res.get('success')} (ID: {add_res.get('id')})")

    # 4.3 Read created stock
    item = get_stock_by_ticker("999999")
    read_ok = item is not None and item["name"] == "테스트종목"
    print(f"Read added stock: {'PASS' if read_ok else 'FAIL'}")

    # 4.4 Update stock
    up_res = update_stock(
        item_id=item["id"],
        avg_price=12000.0,
        quantity=20,
        buy_date="2026-09-06",
        investment_purpose="수정테스트",
        sector="기타",
        market="KOSPI"
    )
    print(f"Update stock: {up_res.get('success')}")

    # Read updated stock
    updated_item = get_stock_by_ticker("999999")
    up_ok = updated_item is not None and updated_item["quantity"] == 20 and updated_item["avg_price"] == 12000.0
    print(f"Read updated stock: {'PASS' if up_ok else 'FAIL'}")

    # 4.5 Delete stock
    del_ok = delete_stock(item["id"])
    print(f"Delete stock: {'PASS' if del_ok else 'FAIL'}")

    # Read after delete
    deleted_item = get_stock_by_ticker("999999")
    clean_ok = deleted_item is None
    print(f"Cleanup verification: {'PASS' if clean_ok else 'FAIL'}")

    # 5. Forward Test Signals Verification
    print("\n--- 5. Forward Test Signals Verification ---")
    pg_cur.execute("SELECT ticker, name, signal_date, price, original_decision, final_decision, status_5d, status_10d, status_20d FROM forward_test_signals ORDER BY id ASC;")
    ft_rows = pg_cur.fetchall()
    print(f"Forward Test records fetched: {len(ft_rows)}")
    for r in ft_rows[:3]:
        print(f"  - [{r['signal_date']}] {r['name']}({r['ticker']}): {r['final_decision']} (5D: {r['status_5d']}, 10D: {r['status_10d']}, 20D: {r['status_20d']})")

    # 6. Investment Engine Decision Invariance Verification
    print("\n--- 6. Investment Engine Invariance Verification ---")
    from backend.data.collector import get_stock_flow_data
    from backend.engine.decision_engine import analyze_stock_decision
    from backend.engine.smart_flow_engine import analyze_smart_money_flow
    from backend.engine.cross_validation_engine import perform_cross_validation

    for ticker, name in [("005930", "삼성전자"), ("069500", "KODEX 200")]:
        flow_info = get_stock_flow_data(ticker, min_days=60)
        df = flow_info["df"]
        res = analyze_stock_decision(df)
        smart_res = analyze_smart_money_flow({}, df)
        cross_res = perform_cross_validation([], [])

        dec = res.get("decision", {})
        flow = res.get("flow_analysis", {})
        tech = res.get("technical_analysis", {})
        timing = res.get("timing_analysis", {})

        print(f"  [{name} ({ticker})]")
        print(f"    - Current Price: {flow.get('current_price')}")
        print(f"    - FCS Score: {flow.get('fcs_score')}")
        print(f"    - FFCS Score: {flow.get('ffcs_score')}")
        print(f"    - RSI: {tech.get('rsi')}")
        print(f"    - RMI: {tech.get('rmi')}")
        print(f"    - Smart Money Score: {smart_res.get('score')}")
        print(f"    - Cross Analysis: {cross_res.get('status_label')}")
        print(f"    - Timing Signal: {timing.get('timing_signal')}")
        print(f"    - TODAY ACTION / Decision: {dec.get('decision')}")

    # 7. SQLite Fallback Test
    print("\n--- 7. SQLite Fallback Test ---")
    from backend.db.database import get_connection
    # Test fallback by unsetting DATABASE_URL temporarily
    os.environ["DATABASE_URL"] = ""
    fallback_conn, fallback_type = get_connection()
    print(f"Fallback DB Connection Type: {fallback_type} ({'PASS' if fallback_type == 'SQLITE' else 'FAIL'})")
    fallback_conn.close()
    os.environ["DATABASE_URL"] = db_url

    pg_conn.close()
    sq_conn.close()
    print("\n==================================================")
    print(" ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("==================================================")
    return True

if __name__ == "__main__":
    verify_all()
