import sqlite3
import os
import logging
from typing import List, Dict, Any, Optional

# 로거 설정
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "portfolio.db")

def get_connection():
    """
    DB 커넥션 생성 함수:
    1. DATABASE_URL 환경변수가 존재할 경우 Supabase PostgreSQL 연결 시도
    2. 연결 실패(DNS 에러, 타임아웃, 접속불가) 또는 DATABASE_URL 부재 시 기존 SQLite(portfolio.db)로 100% 안전 Fallback
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(database_url, connect_timeout=3)
            # Row 딕셔너리처럼 접근 가능하도록 extras.RealDictCursor 등록
            return conn, "POSTGRESQL"
        except Exception as e:
            logger.warning(f"[DB Layer] Supabase PostgreSQL 연결 실패 ({e}). 로컬 SQLite(portfolio.db)로 안전하게 Fallback합니다.")

    # SQLite fallback
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn, "SQLITE"

def init_db():
    conn, db_type = get_connection()
    cursor = conn.cursor()
    
    if db_type == "POSTGRESQL":
        cursor.execute("""
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
            )
        """)
        conn.commit()
        conn.close()
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ticker TEXT NOT NULL UNIQUE,
                avg_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                buy_date TEXT,
                investment_purpose TEXT,
                sector TEXT DEFAULT '기타',
                asset_type TEXT DEFAULT 'STOCK',
                market TEXT DEFAULT 'KOSPI',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # 컬럼 마이그레이션 체크
        cursor.execute("PRAGMA table_info(portfolios)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'asset_type' not in columns:
            cursor.execute("ALTER TABLE portfolios ADD COLUMN asset_type TEXT DEFAULT 'STOCK'")
            conn.commit()
        if 'market' not in columns:
            cursor.execute("ALTER TABLE portfolios ADD COLUMN market TEXT DEFAULT 'KOSPI'")
            conn.commit()
        conn.close()

    try:
        from backend.engine.forward_test_engine import init_forward_test_db
        init_forward_test_db()
    except Exception as e:
        pass

def add_stock(name: str, ticker: str, avg_price: float, quantity: int, buy_date: str = "", investment_purpose: str = "", sector: str = "기타", asset_type: str = "STOCK", market: str = "KOSPI") -> Dict[str, Any]:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    asset_type = asset_type.upper() if asset_type else "STOCK"
    market = market.upper() if market else "KOSPI"
    try:
        if db_type == "POSTGRESQL":
            cursor.execute("""
                INSERT INTO portfolios (name, ticker, avg_price, quantity, buy_date, investment_purpose, sector, asset_type, market)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(ticker) DO UPDATE SET
                    avg_price = (portfolios.avg_price * portfolios.quantity + EXCLUDED.avg_price * EXCLUDED.quantity) / (portfolios.quantity + EXCLUDED.quantity),
                    quantity = portfolios.quantity + EXCLUDED.quantity,
                    buy_date = EXCLUDED.buy_date,
                    investment_purpose = EXCLUDED.investment_purpose,
                    sector = EXCLUDED.sector,
                    asset_type = EXCLUDED.asset_type,
                    market = EXCLUDED.market
                RETURNING id;
            """, (name, ticker, avg_price, quantity, buy_date, investment_purpose, sector, asset_type, market))
            item_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO portfolios (name, ticker, avg_price, quantity, buy_date, investment_purpose, sector, asset_type, market)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    avg_price = (portfolios.avg_price * portfolios.quantity + excluded.avg_price * excluded.quantity) / (portfolios.quantity + excluded.quantity),
                    quantity = portfolios.quantity + excluded.quantity,
                    buy_date = excluded.buy_date,
                    investment_purpose = excluded.investment_purpose,
                    sector = excluded.sector,
                    asset_type = excluded.asset_type,
                    market = excluded.market
            """, (name, ticker, avg_price, quantity, buy_date, investment_purpose, sector, asset_type, market))
            item_id = cursor.lastrowid
        conn.commit()
        return {"success": True, "id": item_id, "message": f"'{name}'({ticker}) 종목이 포트폴리오에 추가되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def get_all_stocks(asset_type: Optional[str] = "STOCK") -> List[Dict[str, Any]]:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    if asset_type and asset_type.upper() != "ALL":
        target = asset_type.upper()
        cursor.execute(f"SELECT * FROM portfolios WHERE UPPER(COALESCE(asset_type, 'STOCK')) = {ph} ORDER BY id DESC", (target,))
    else:
        cursor.execute("SELECT * FROM portfolios ORDER BY id DESC")
    rows = cursor.fetchall()
    result = [dict(row) for row in rows]
    conn.close()
    return result

def get_stock_by_id(item_id: int) -> Optional[Dict[str, Any]]:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    cursor.execute(f"SELECT * FROM portfolios WHERE id = {ph}", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_stock_by_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    cursor.execute(f"SELECT * FROM portfolios WHERE ticker = {ph}", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_stock(item_id: int) -> bool:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    cursor.execute(f"DELETE FROM portfolios WHERE id = {ph}", (item_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def update_stock(item_id: int, avg_price: float, quantity: int, buy_date: str = "", investment_purpose: str = "", sector: str = "기타", market: str = "KOSPI") -> Dict[str, Any]:
    conn, db_type = get_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "POSTGRESQL" else "?"
    try:
        cursor.execute(f"""
            UPDATE portfolios
            SET avg_price = {ph}, quantity = {ph}, buy_date = {ph}, investment_purpose = {ph}, sector = {ph}, market = {ph}
            WHERE id = {ph}
        """, (avg_price, quantity, buy_date, investment_purpose, sector, market, item_id))
        conn.commit()
        affected = cursor.rowcount
        if affected > 0:
            return {"success": True, "message": "종목 매입단가, 보유수량 및 업종 정보가 수정되었습니다."}
        else:
            return {"success": False, "error": "해당 종목을 찾을 수 없습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def clear_all_stocks():
    conn, db_type = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolios")
    conn.commit()
    conn.close()

# 데이터베이스 초기화 실행
init_db()

