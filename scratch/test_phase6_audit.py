import sys
import os
import time
import warnings
import asyncio

warnings.filterwarnings("ignore")
sys.path.insert(0, r"d:\antigravity\stock_포트폴리오(0825)")

from backend.router.recommend_router import ask_quant_recommendation, RecommendRequest
from backend.main import (
    get_market_overview,
    get_qna_stock_news,
    get_market_index_history
)
from backend.engine.recommendation_analysis_engine import _QUANT_CHART_CACHE
from backend.db import database as db

def main():
    print("=" * 70)
    print("PHASE 6: FULL PRODUCTION E2E & PERFORMANCE & REGRESSION AUDIT")
    print("=" * 70)

    prompts = [
        ("1. 단기 매매 후보 5개", "단기 매매 후보 5개 찾아줘"),
        ("2. 중기 ETF 3개", "중기 ETF 3개 추천해줘"),
        ("3. 외국인 기관 쌍끌이", "외국인 기관 쌍끌이 종목 찾아줘"),
        ("4. 최근 수급 개선", "최근 수급이 개선된 종목 알려줘"),
        ("5. 비과열 상승추세", "과열되지 않은 상승추세 종목 찾아줘"),
        ("6. 보유종목 단기 유망순", "현재 보유종목 중 단기 유망순으로 보여줘"),
        ("7. 눌림목 후보", "눌림목 후보 찾아줘"),
        ("8. 중기 종목 10개", "중기 종목 10개 보여줘"),
        ("9. 수급 좋은 ETF", "수급 좋은 ETF 찾아줘"),
        ("10. 기관 최근 매집", "기관이 최근 매집하는 종목 알려줘")
    ]

    results_summary = []
    perf_table = {}
    hallucinated_cnt = 0
    mismatch_cnt = 0
    joint_buy_fp = 0
    ineligible_etf_cnt = 0
    portfolio_mismatch_cnt = 0
    data_quality_err = 0

    portfolio_tickers = set(item['ticker'] for item in db.get_all_stocks(asset_type="ALL"))
    print(f"Portfolio DB Total Tickers: {len(portfolio_tickers)}")

    # Clear cache for first Cold run
    _QUANT_CHART_CACHE.clear()

    for idx, (label, text) in enumerate(prompts, 1):
        print(f"\n[{label}] Testing prompt: '{text}'")

        # Cold execution
        t0_cold = time.time()
        res_cold = ask_quant_recommendation(RecommendRequest(question=text))
        dur_cold = time.time() - t0_cold

        # Warm execution
        t0_warm = time.time()
        res_warm = ask_quant_recommendation(RecommendRequest(question=text))
        dur_warm = time.time() - t0_warm

        status = res_warm.get("status")
        intent = res_warm.get("intent")
        req_cnt = res_warm.get("requested_count")
        ret_cnt = res_warm.get("returned_count")
        items = res_warm.get("results", [])

        print(f"  Status: {status} | Intent: {intent} | Req: {req_cnt} | Ret: {ret_cnt}")
        print(f"  Cold: {dur_cold:.2f}s | Warm: {dur_warm:.2f}s")
        print(f"  Message: {res_warm.get('message')}")

        if label in ["1. 단기 매매 후보 5개", "2. 중기 ETF 3개", "3. 외국인 기관 쌍끌이", "6. 보유종목 단기 유망순"]:
            perf_table[label] = {"cold": round(dur_cold, 2), "warm": round(dur_warm, 2)}

        # Audit items
        for item in items:
            ticker = item.get("ticker", "")
            name = item.get("name", "")
            
            # Hallucination check
            if not ticker or len(ticker) < 6 or not name:
                hallucinated_cnt += 1
                print(f"    [HALLUCINATION ERR] Invalid ticker/name: {ticker} / {name}")

            # Data quality check (null/NaN classification error)
            if item.get("grade") in ["STRONG_CANDIDATE", "CANDIDATE"] and item.get("flow_pattern") == "DATA_INSUFFICIENT":
                data_quality_err += 1
                print(f"    [DATA QUALITY ERR] {name}({ticker}) is DATA_INSUFFICIENT but grade={item.get('grade')}")

            # Joint Buy strictness check
            if intent == "FLOW_JOINT_BUY":
                # Check if strict joint buy
                fp = item.get("flow_pattern")
                if fp != "JOINT_BUY":
                    joint_buy_fp += 1
                    print(f"    [JOINT BUY ERR] {name}({ticker}) flow_pattern={fp} != JOINT_BUY")

            # ETF eligibility check
            if intent == "ETF_MID_RECOMMEND":
                asset_t = item.get("asset_type")
                name_u = name.upper()
                if any(k in name_u for k in ["인버스", "INVERSE", "레버리지", "LEVERAGE", "2X", "MMF", "KOFR", "SOFR", "CD금리", "채권"]):
                    ineligible_etf_cnt += 1
                    print(f"    [ETF ELIGIBILITY ERR] {name}({ticker}) is inverse/leveraged/bond/mmf in MID top pool")

            # Portfolio restriction check
            if intent == "PORTFOLIO_SHORT_RANK":
                if ticker not in portfolio_tickers:
                    portfolio_mismatch_cnt += 1
                    print(f"    [PORTFOLIO ERR] {name}({ticker}) not in user's portfolio holdings!")

        # Accuracy check (backend raw values completeness)
        for item in items[:2]:
            if not item.get("ticker") or not item.get("grade") or not item.get("flow_pattern"):
                mismatch_cnt += 1

        results_summary.append({
            "idx": idx,
            "label": label,
            "status": "PASS" if status == "ok" else "FAIL",
            "intent": intent,
            "ret_cnt": ret_cnt,
            "cold_s": round(dur_cold, 2),
            "warm_s": round(dur_warm, 2)
        })

    # -------------------------------------------------------------
    # REGRESSION CHECK ON EXISTING APP FUNCTIONS
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print("EXISTING APPLICATION REGRESSION AUDIT")
    print("=" * 70)

    # 1. Market overview API
    mkt_res = get_market_overview()
    print(f"1. Market Overview API => {mkt_res.get('status', 'ok')}")

    # 2. Q&A News API
    qna_news_res = asyncio.run(get_qna_stock_news("005930"))
    print(f"2. Q&A News API (005930) => {len(qna_news_res)} articles")

    # 3. Portfolio DB items
    port_items = db.get_all_stocks(asset_type="ALL")
    print(f"3. Portfolio DB Items => {len(port_items)} holdings")

    # 4. Forward Test Engine DB
    try:
        from backend.engine.forward_test_engine import init_forward_test_db
        init_forward_test_db()
        ft_ok = True
    except Exception:
        ft_ok = False
    print(f"4. Forward Test DB => {'OK' if ft_ok else 'FAIL'}")

    print("\n" + "=" * 70)
    print("PHASE 6 AUDIT METRICS SUMMARY")
    print("=" * 70)
    print(f"10 E2E Prompts Pass Rate: {sum(1 for r in results_summary if r['status'] == 'PASS')}/10")
    print(f"Backend <-> UI Mismatch: {mismatch_cnt}")
    print(f"Hallucinated Tickers: {hallucinated_cnt}")
    print(f"JOINT_BUY False Positives: {joint_buy_fp}")
    print(f"Ineligible Mid ETFs: {ineligible_etf_cnt}")
    print(f"Portfolio Non-holding Mismatches: {portfolio_mismatch_cnt}")
    print(f"Data Quality Classification Errors: {data_quality_err}")
    print(f"Performance Metrics: {perf_table}")

    print("\nPHASE 6 AUDIT COMPLETE!")

if __name__ == "__main__":
    main()
