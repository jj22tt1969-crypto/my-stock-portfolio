import sys
import os

sys.path.insert(0, r"d:\antigravity\stock_포트폴리오(0825)")
from backend.engine.recommend_intent_parser import parse_recommendation_intent

questions = [
    "단기 매매 후보 5개 찾아줘",
    "중기 ETF 3개 추천해줘",
    "외국인 기관 쌍끌이 종목 찾아줘",
    "최근 수급이 개선된 종목 알려줘",
    "과열되지 않은 상승추세 종목 찾아줘",
    "현재 보유종목 중 단기 유망순으로 보여줘",
    "단기 종목 추천해줘",
    "중기 종목 10개 보여줘",
    "수급 좋은 ETF 찾아줘",
    "기관이 최근 매집하는 종목 알려줘",
    "외국인 매수가 강해지는 종목 찾아줘",
    "눌림목 후보 찾아줘"
]

for q in questions:
    res = parse_recommendation_intent(q)
    print(f"'{q}' => intent: {res['intent']}, scope: {res['market_scope']}, count: {res['requested_count']}")
