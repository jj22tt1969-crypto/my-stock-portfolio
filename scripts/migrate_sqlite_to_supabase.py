import os
import sys
import sqlite3
import dotenv

# 프로젝트 루트 경로 설정
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

dotenv.load_dotenv(os.path.join(ROOT_DIR, ".env"))

SQLITE_PATH = os.path.join(ROOT_DIR, "backend", "data", "portfolio.db")

def migrate_to_supabase():
    print("==================================================")
    print(" 🚀 SQLite3 -> Supabase PostgreSQL Data Migration ")
    print("==================================================")

    if not os.path.exists(SQLITE_PATH):
        print(f"❌ SQLite DB 파일({SQLITE_PATH})을 찾을 수 없습니다.")
        return

    sq_conn = sqlite3.connect(SQLITE_PATH)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    # SQLite row count
    sq_port_count = sq_cur.execute("SELECT count(*) FROM portfolios").fetchone()[0]
    sq_ft_count = sq_cur.execute("SELECT count(*) FROM forward_test_signals").fetchone()[0]

    print(f"📊 [SQLite 원본 데이터 수량]")
    print(f"  - portfolios: {sq_port_count} 건")
    print(f"  - forward_test_signals: {sq_ft_count} 건")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ .env 파일에 DATABASE_URL 환경변수가 설정되어 있지 않습니다.")
        return

    try:
        import psycopg2
        import psycopg2.extras
        pg_conn = psycopg2.connect(database_url, connect_timeout=5)
        pg_cur = pg_conn.cursor()
        print("✅ Supabase PostgreSQL 연결 성공!")
    except Exception as e:
        print(f"⚠️ Supabase PostgreSQL 연결 실패 ({e})")
        print("🔒 안전 조치: 기존 SQLite portfolio.db 원본 데이터 및 로컬 서비스는 100% 정상 유지됩니다.")
        return

    # 마이그레이션 로직 수행...
    pg_conn.close()

if __name__ == "__main__":
    migrate_to_supabase()
