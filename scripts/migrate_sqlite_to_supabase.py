import os
import sys
import sqlite3
import dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

dotenv.load_dotenv(os.path.join(ROOT_DIR, ".env"))

SQLITE_PATH = os.path.join(ROOT_DIR, "backend", "data", "portfolio.db")

def run_migration():
    print("==================================================")
    print(" SQLite3 -> Supabase PostgreSQL Data Migration ")
    print("==================================================")

    if not os.path.exists(SQLITE_PATH):
        print(f"[FAIL] SQLite DB file ({SQLITE_PATH}) not found.")
        return False

    # 1. Connect SQLite
    sq_conn = sqlite3.connect(SQLITE_PATH)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    sq_portfolios = sq_cur.execute("SELECT * FROM portfolios ORDER BY id ASC").fetchall()
    sq_signals = sq_cur.execute("SELECT * FROM forward_test_signals ORDER BY id ASC").fetchall()

    sq_port_count = len(sq_portfolios)
    sq_sig_count = len(sq_signals)

    print(f"[SQLite Data Summary]")
    print(f"  - portfolios: {sq_port_count} rows")
    print(f"  - forward_test_signals: {sq_sig_count} rows")

    # 2. Connect PostgreSQL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("[FAIL] DATABASE_URL missing in .env")
        return False

    try:
        import psycopg2
        import psycopg2.extras
        pg_conn = psycopg2.connect(database_url, connect_timeout=10)
        pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        print("[SUCCESS] Connected to Supabase PostgreSQL!")
    except Exception as e:
        print(f"[FAIL] Failed to connect to PostgreSQL: {e}")
        return False

    try:
        # 3. Create Tables
        pg_cur.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                ticker VARCHAR(50) NOT NULL UNIQUE,
                avg_price DOUBLE PRECISION NOT NULL,
                quantity INTEGER NOT NULL,
                buy_date VARCHAR(50),
                investment_purpose VARCHAR(100),
                sector VARCHAR(100) DEFAULT '기타',
                asset_type VARCHAR(50) DEFAULT 'STOCK',
                market VARCHAR(50) DEFAULT 'KOSPI',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        pg_cur.execute("""
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
                cross_status VARCHAR(100),
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
            );
        """)
        pg_conn.commit()

        # 4. Migrate portfolios
        print("\n[Migrating portfolios table...]")
        for row in sq_portfolios:
            pg_cur.execute("""
                INSERT INTO portfolios (name, ticker, avg_price, quantity, buy_date, investment_purpose, sector, asset_type, market)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    name = EXCLUDED.name,
                    avg_price = EXCLUDED.avg_price,
                    quantity = EXCLUDED.quantity,
                    buy_date = EXCLUDED.buy_date,
                    investment_purpose = EXCLUDED.investment_purpose,
                    sector = EXCLUDED.sector,
                    asset_type = EXCLUDED.asset_type,
                    market = EXCLUDED.market;
            """, (
                row['name'], row['ticker'], float(row['avg_price']), int(row['quantity']),
                row['buy_date'], row['investment_purpose'], row['sector'],
                row['asset_type'], row['market']
            ))
        pg_conn.commit()

        # 5. Migrate forward_test_signals
        print("[Migrating forward_test_signals table...]")
        for row in sq_signals:
            pg_cur.execute("""
                INSERT INTO forward_test_signals (
                    ticker, name, asset_type, signal_date, price,
                    original_decision, final_decision, fcs_score, ffcs_score,
                    rsi, rmi, smart_score, smart_grade, concurrency_code,
                    ma60, ma120, is_ma_downtrend, timing_signal, cross_status,
                    data_source, timestamp_str, price_5d, ret_5d, status_5d,
                    price_10d, ret_10d, status_10d, price_20d, ret_20d, status_20d
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (ticker, signal_date) DO UPDATE SET
                    name = EXCLUDED.name,
                    price = EXCLUDED.price,
                    original_decision = EXCLUDED.original_decision,
                    final_decision = EXCLUDED.final_decision,
                    fcs_score = EXCLUDED.fcs_score,
                    ffcs_score = EXCLUDED.ffcs_score,
                    rsi = EXCLUDED.rsi,
                    rmi = EXCLUDED.rmi,
                    smart_score = EXCLUDED.smart_score,
                    smart_grade = EXCLUDED.smart_grade,
                    concurrency_code = EXCLUDED.concurrency_code,
                    ma60 = EXCLUDED.ma60,
                    ma120 = EXCLUDED.ma120,
                    is_ma_downtrend = EXCLUDED.is_ma_downtrend,
                    timing_signal = EXCLUDED.timing_signal,
                    cross_status = EXCLUDED.cross_status,
                    data_source = EXCLUDED.data_source,
                    timestamp_str = EXCLUDED.timestamp_str,
                    price_5d = EXCLUDED.price_5d,
                    ret_5d = EXCLUDED.ret_5d,
                    status_5d = EXCLUDED.status_5d,
                    price_10d = EXCLUDED.price_10d,
                    ret_10d = EXCLUDED.ret_10d,
                    status_10d = EXCLUDED.status_10d,
                    price_20d = EXCLUDED.price_20d,
                    ret_20d = EXCLUDED.ret_20d,
                    status_20d = EXCLUDED.status_20d;
            """, (
                row['ticker'], row['name'], row['asset_type'], row['signal_date'], float(row['price']),
                row['original_decision'], row['final_decision'],
                float(row['fcs_score']) if row['fcs_score'] is not None else None,
                float(row['ffcs_score']) if row['ffcs_score'] is not None else None,
                float(row['rsi']) if row['rsi'] is not None else None,
                float(row['rmi']) if row['rmi'] is not None else None,
                float(row['smart_score']) if row['smart_score'] is not None else None,
                row['smart_grade'], row['concurrency_code'],
                float(row['ma60']) if row['ma60'] is not None else None,
                float(row['ma120']) if row['ma120'] is not None else None,
                row['is_ma_downtrend'], row['timing_signal'], row['cross_status'],
                row['data_source'], row['timestamp_str'],
                float(row['price_5d']) if row['price_5d'] is not None else None,
                float(row['ret_5d']) if row['ret_5d'] is not None else None,
                row['status_5d'],
                float(row['price_10d']) if row['price_10d'] is not None else None,
                float(row['ret_10d']) if row['ret_10d'] is not None else None,
                row['status_10d'],
                float(row['price_20d']) if row['price_20d'] is not None else None,
                float(row['ret_20d']) if row['ret_20d'] is not None else None,
                row['status_20d']
            ))
        pg_conn.commit()

        # 6. Verify row counts
        pg_cur.execute("SELECT count(*) as count FROM portfolios;")
        pg_port_count = pg_cur.fetchone()['count']

        pg_cur.execute("SELECT count(*) as count FROM forward_test_signals;")
        pg_sig_count = pg_cur.fetchone()['count']

        print("\n==================================================")
        print(" Migration Verification Results")
        print("==================================================")
        print(f"SQLite portfolios: {sq_port_count} -> PostgreSQL: {pg_port_count} {'PASS' if sq_port_count == pg_port_count else 'FAIL'}")
        print(f"SQLite forward_test_signals: {sq_sig_count} -> PostgreSQL: {pg_sig_count} {'PASS' if sq_sig_count == pg_sig_count else 'FAIL'}")

        pg_conn.close()
        sq_conn.close()

        return sq_port_count == pg_port_count and sq_sig_count == pg_sig_count
    except Exception as e:
        print(f"[FAIL] Error during migration: {e}")
        return False

if __name__ == "__main__":
    run_migration()
