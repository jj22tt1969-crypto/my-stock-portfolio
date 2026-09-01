import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "portfolio.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 컬럼 마이그레이션 체크 (asset_type 및 market 없을 경우 자동 추가)
    cursor.execute("PRAGMA table_info(portfolios)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'asset_type' not in columns:
        cursor.execute("ALTER TABLE portfolios ADD COLUMN asset_type TEXT DEFAULT 'STOCK'")
        conn.commit()
    if 'market' not in columns:
        cursor.execute("ALTER TABLE portfolios ADD COLUMN market TEXT DEFAULT 'KOSPI'")
        conn.commit()

    conn.close()

def add_stock(name: str, ticker: str, avg_price: float, quantity: int, buy_date: str = "", investment_purpose: str = "", sector: str = "기타", asset_type: str = "STOCK", market: str = "KOSPI") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    asset_type = asset_type.upper() if asset_type else "STOCK"
    market = market.upper() if market else "KOSPI"
    try:
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
        conn.commit()
        item_id = cursor.lastrowid
        return {"success": True, "id": item_id, "message": f"'{name}'({ticker}) 종목이 포트폴리오에 추가되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def get_all_stocks(asset_type: Optional[str] = "STOCK") -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if asset_type and asset_type.upper() != "ALL":
        target = asset_type.upper()
        cursor.execute("SELECT * FROM portfolios WHERE UPPER(COALESCE(asset_type, 'STOCK')) = ? ORDER BY id DESC", (target,))
    else:
        cursor.execute("SELECT * FROM portfolios ORDER BY id DESC")
    rows = cursor.fetchall()
    result = [dict(row) for row in rows]
    conn.close()
    return result

def get_stock_by_id(item_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM portfolios WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_stock_by_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM portfolios WHERE ticker = ?", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_stock(item_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolios WHERE id = ?", (item_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def update_stock(item_id: int, avg_price: float, quantity: int, buy_date: str = "", investment_purpose: str = "", sector: str = "기타", market: str = "KOSPI") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE portfolios
            SET avg_price = ?, quantity = ?, buy_date = ?, investment_purpose = ?, sector = ?, market = ?
            WHERE id = ?
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolios")
    conn.commit()
    conn.close()

# 데이터베이스 초기화 실행
init_db()
