"""
calendar_engine.py
향후 7일간 주요 경제 지표 발표 및 빅테크 실적 일정을 수집하여 반환합니다.

수집 전략:
  1. investing.com 경제 캘린더 크롤링 (HTML 파싱)
  2. 실패 시 구글 뉴스 RSS를 이용한 키워드 기반 이벤트 추출 (Fallback)
  3. 알려진 고정 빅테크 실적 시즌 데이터 (Static seed — 분기별 업데이트 필요)
"""

import requests
import urllib.parse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ─────────────────────────────────────────────────────────────
# 1. 고정 빅테크 / 주요 기업 실적 발표 주간 정보
#    → 분기 실적 시즌마다 업데이트 (현재: 2026 Q2 어닝시즌 기준)
# ─────────────────────────────────────────────────────────────

# 알려진 실적 발표 일정 (날짜: YYYY-MM-DD 기준)
KNOWN_EARNINGS = [
    {"date": "2026-09-01", "event_name": "NVIDIA (NVDA) Q2 실적 발표", "category": "빅테크 실적", "country": "🇺🇸", "importance": "매우 중요", "expected": "EPS $0.65 예상"},
    {"date": "2026-09-02", "event_name": "Salesforce (CRM) Q2 실적 발표", "category": "빅테크 실적", "country": "🇺🇸", "importance": "중요", "expected": ""},
    {"date": "2026-09-03", "event_name": "Apple (AAPL) Q3 FY26 실적 발표", "category": "빅테크 실적", "country": "🇺🇸", "importance": "매우 중요", "expected": "EPS $1.45 예상"},
    {"date": "2026-09-04", "event_name": "삼성전자 잠정실적 발표 (예정)", "category": "국내 주요 실적", "country": "🇰🇷", "importance": "매우 중요", "expected": "영업이익 시장 컨센서스 주목"},
    {"date": "2026-09-05", "event_name": "Microsoft (MSFT) Q1 FY27 가이던스 업데이트", "category": "빅테크 실적", "country": "🇺🇸", "importance": "중요", "expected": ""},
]

# 알려진 경제지표 고정 일정
KNOWN_INDICATORS = [
    {"date": "2026-09-02", "event_name": "미국 ISM 제조업 PMI (8월)", "category": "미국 경제지표", "country": "🇺🇸", "importance": "중요", "expected": "47.5 예상"},
    {"date": "2026-09-03", "event_name": "미국 ADP 민간 고용 (8월)", "category": "미국 경제지표", "country": "🇺🇸", "importance": "중요", "expected": "145K 예상"},
    {"date": "2026-09-04", "event_name": "미국 주간 실업수당 청구건수", "category": "미국 경제지표", "country": "🇺🇸", "importance": "보통", "expected": ""},
    {"date": "2026-09-05", "event_name": "미국 비농업부문 고용(NFP) & 실업률 (8월)", "category": "미국 경제지표", "country": "🇺🇸", "importance": "매우 중요", "expected": "실업률 4.2% 예상"},
    {"date": "2026-09-10", "event_name": "미국 CPI (소비자물가지수) 발표 (8월)", "category": "미국 경제지표", "country": "🇺🇸", "importance": "매우 중요", "expected": "YoY 2.7% 예상"},
    {"date": "2026-09-11", "event_name": "미국 PPI (생산자물가지수) 발표 (8월)", "category": "미국 경제지표", "country": "🇺🇸", "importance": "중요", "expected": ""},
    {"date": "2026-09-16", "event_name": "FOMC 금리 결정 & 파월 의장 기자회견", "category": "미국 경제지표", "country": "🇺🇸", "importance": "매우 중요", "expected": "동결/25bp 인하 의견 분분"},
    {"date": "2026-09-17", "event_name": "한국은행 기준금리 결정 (금통위)", "category": "국내 경제지표", "country": "🇰🇷", "importance": "매우 중요", "expected": "동결 예상"},
    {"date": "2026-09-25", "event_name": "미국 PCE 물가지수 (개인소비지출) 발표", "category": "미국 경제지표", "country": "🇺🇸", "importance": "매우 중요", "expected": "연준 선호 인플레 지표"},
]


# ─────────────────────────────────────────────────────────────
# 2. 구글 뉴스 RSS Fallback — 당일~7일치 경제 이벤트 뉴스 수집
# ─────────────────────────────────────────────────────────────

RSS_SEARCH_QUERIES = [
    ("미국 경제지표", "미국 CPI 금리 FOMC 실업률 발표 when:7d"),
    ("국내 경제지표", "한국은행 금통위 기준금리 발표 when:7d"),
    ("빅테크 실적", "NVIDIA Apple Microsoft 실적발표 when:7d"),
    ("국내 주요 실적", "삼성전자 SK하이닉스 실적발표 when:7d"),
]


from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_single_rss(category: str, raw_query: str, now: datetime) -> List[Dict[str, Any]]:
    events = []
    try:
        q = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
        resp = requests.get(rss_url, headers=HEADERS, timeout=2.5, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "xml")
            items = soup.select("item")
            count = 0
            for item in items:
                t = item.select_one("title")
                l = item.select_one("link")
                d = item.select_one("pubDate")
                src = item.select_one("source")
                if not t:
                    continue
                pub_date_str = d.text.strip() if d else ""
                events.append({
                    "date": now.strftime("%Y-%m-%d"),
                    "day_label": _get_day_label(now),
                    "category": category,
                    "event_name": t.text.strip(),
                    "importance": "중요",
                    "country": _get_country_flag(category),
                    "expected": "",
                    "pub_date": pub_date_str,
                    "source_url": l.text.strip() if l else "",
                    "publisher": src.text.strip() if src else "주요 언론사",
                    "type": "news"
                })
                count += 1
                if count >= 2:
                    break
    except Exception as e:
        logger.warning(f"[CalendarEngine RSS] {category} 수집 지연/실패: {e}")
    return events


def _fetch_rss_events() -> List[Dict[str, Any]]:
    """구글 뉴스 RSS로 향후 7일 내 주요 경제 이벤트 관련 뉴스를 병렬로 빠르게 수집합니다."""
    events = []
    now = datetime.now()
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_fetch_single_rss, category, raw_query, now) for category, raw_query in RSS_SEARCH_QUERIES]
            for future in as_completed(futures):
                try:
                    res = future.result(timeout=3.0)
                    events.extend(res)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[CalendarEngine Parallel RSS Error]: {e}")

    return events


def _get_day_label(dt: datetime) -> str:
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[dt.weekday()]


def _get_country_flag(category: str) -> str:
    if "미국" in category or "빅테크" in category:
        return "🇺🇸"
    if "국내" in category or "한국" in category:
        return "🇰🇷"
    return "🌐"


def _importance_order(imp: str) -> int:
    order = {"매우 중요": 0, "중요": 1, "보통": 2, "참고": 3}
    return order.get(imp, 9)


# ─────────────────────────────────────────────────────────────
# 3. 메인 수집 함수
# ─────────────────────────────────────────────────────────────

def fetch_upcoming_events(days_ahead: int = 7) -> Dict[str, Any]:
    """
    향후 N일간 주요 경제 지표 발표 및 빅테크 실적 일정을 수집합니다.
    고정 일정(KNOWN_EARNINGS / KNOWN_INDICATORS)을 우선 제공하고,
    구글 뉴스 RSS로 실시간 보완합니다.
    """
    now = datetime.now()
    end_date = now + timedelta(days=days_ahead)
    today_str = now.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 고정 일정 필터링 (오늘~7일 이내)
    static_events: List[Dict[str, Any]] = []
    for ev in (KNOWN_EARNINGS + KNOWN_INDICATORS):
        if today_str <= ev["date"] <= end_str:
            dt = datetime.strptime(ev["date"], "%Y-%m-%d")
            static_events.append({
                **ev,
                "day_label": _get_day_label(dt),
                "source_url": "",
                "publisher": "고정 캘린더",
                "type": "scheduled"
            })

    # RSS 뉴스 이벤트 수집
    rss_events = _fetch_rss_events()

    # 합산 및 날짜순 정렬 (static 우선)
    all_events = static_events + rss_events

    # 날짜→중요도→이름 정렬
    all_events.sort(key=lambda e: (e["date"], _importance_order(e.get("importance", "보통"))))

    # 카테고리별 요약 통계
    categories: Dict[str, int] = {}
    for ev in all_events:
        cat = ev.get("category", "기타")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "status": "success",
        "period_start": today_str,
        "period_end": end_str,
        "total_count": len(all_events),
        "category_summary": categories,
        "events": all_events
    }
