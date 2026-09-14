import sys
import os
import time
import warnings
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, r"d:\antigravity\stock_포트폴리오(0825)")

from backend.engine.recommendation_analysis_engine import (
    run_quant_recommendation,
    analyze_candidates_quant_parallel,
    _QUANT_CHART_CACHE
)
from backend.engine.recommendation_flow_screener import run_flow_screener

def main():
    print("=" * 60)
    print("RUNNING COMPLETE QUANT RECOMMENDATION AUDIT (PHASE 4.1)")
    print("=" * 60)

    # 1. Flow screener run to get Stage 3 candidates
    t0_flow = time.time()
    flow_res = run_flow_screener(stock_stage1_count=100, etf_stage1_count=50, max_workers=5)
    t_flow = time.time() - t0_flow

    stock_candidates = flow_res["stock_results"]["stage3_candidates"]
    etf_candidates = flow_res["etf_results"]["stage3_candidates"]

    print(f"Stage 1+2 Screener complete: {t_flow:.2f}s | STOCK candidates: {len(stock_candidates)}, ETF candidates: {len(etf_candidates)}")

    # Clear quant chart cache to measure Cold
    _QUANT_CHART_CACHE.clear()

    # 2. Cold Run
    t0_cold = time.time()
    stock_analyzed_cold = analyze_candidates_quant_parallel(stock_candidates, max_workers=5)
    etf_analyzed_cold = analyze_candidates_quant_parallel(etf_candidates, max_workers=5)
    t_cold = time.time() - t0_cold
    print(f"Cold Stage 3 Run Time: {t_cold:.2f}s")

    # 3. Warm Run (Cache hit)
    t0_warm = time.time()
    stock_analyzed = analyze_candidates_quant_parallel(stock_candidates, max_workers=5)
    etf_analyzed = analyze_candidates_quant_parallel(etf_candidates, max_workers=5)
    t_warm = time.time() - t0_warm
    print(f"Warm Stage 3 Run Time: {t_warm:.2f}s")

    # Full Quant recommendation (Warm)
    t0_full_warm = time.time()
    full_res = run_quant_recommendation(stock_stage1_count=100, etf_stage1_count=50, max_workers=5)
    t_full_warm = time.time() - t0_full_warm
    print(f"Full Warm Engine Run Time: {t_full_warm:.2f}s")

    # -------------------------------------------------------------
    # [1] GS건설 MID 판정 재검증
    # -------------------------------------------------------------
    print("\n" + "=" * 60)
    print("[1] GS건설 (006360) MID 판정 재검증")
    print("=" * 60)

    gs_item = next((c for c in stock_analyzed if c.get("ticker") == "006360" or "GS건설" in c.get("name", "")), None)
    if gs_item:
        print(f"ticker: {gs_item.get('ticker')}")
        print(f"name: {gs_item.get('name')}")
        print(f"current_price: {gs_item.get('close_price', gs_item.get('price'))}")
        print(f"ma60: {gs_item.get('ma60')}")
        print(f"ma120: {gs_item.get('ma120')}")
        print(f"ma60 > ma120: {gs_item.get('ma60', 0) > gs_item.get('ma120', 0) if gs_item.get('ma60') and gs_item.get('ma120') else False}")
        print(f"6M Trend: {gs_item.get('trend_6m')}%")
        print(f"flow_pattern: {gs_item.get('flow_pattern')}")
        print(f"flow_tier: {gs_item.get('flow_tier')}")
        print(f"mid_grade: {gs_item.get('mid_grade')}")
        print(f"mid_reasons: {gs_item.get('mid_reasons')}")
    else:
        print("GS건설 not in Stage 3 candidates list (not in top 25 volume/flow). Fetching individually...")

    # -------------------------------------------------------------
    # [2] MID STRONG 전수검사
    # -------------------------------------------------------------
    print("\n" + "=" * 60)
    print("[2] MID STRONG 전수검사")
    print("=" * 60)

    all_analyzed = stock_analyzed + etf_analyzed
    mid_strong_list = [c for c in all_analyzed if c.get("mid_grade") == "STRONG_CANDIDATE"]

    stock_mid_strong = [c for c in stock_analyzed if c.get("mid_grade") == "STRONG_CANDIDATE"]
    etf_mid_strong = [c for c in etf_analyzed if c.get("mid_grade") == "STRONG_CANDIDATE"]

    print(f"STOCK MID STRONG: {len(stock_mid_strong)}개")
    print(f"ETF MID STRONG: {len(etf_mid_strong)}개")

    mismatch_cnt = 0
    for c in mid_strong_list:
        ticker = c.get("ticker")
        name = c.get("name")
        c_price = c.get("price")
        ma60 = c.get("ma60")
        ma120 = c.get("ma120")
        ma60_gt_120 = (ma60 > ma120) if (ma60 and ma120) else False
        t6m = c.get("trend_6m")
        reasons = c.get("mid_reasons", [])

        # Audit logic vs reasons
        has_false_explanation = False
        for r in reasons:
            if "정배열" in r and not ma60_gt_120:
                has_false_explanation = True
                mismatch_cnt += 1
                print(f"  [MISMATCH] {name}({ticker}): ma60={ma60} < ma120={ma120} but reason='{r}'")

        print(f"  [{c.get('asset_type')}] {name}({ticker}) | P:{c_price} | MA60:{ma60} | MA120:{ma120} | MA60>120:{ma60_gt_120} | 6M:{t6m}% | reasons:{reasons}")

    print(f"\nTotal MID STRONG Reason Mismatches: {mismatch_cnt}")

    # -------------------------------------------------------------
    # [3] SHORT STRONG 전수검사
    # -------------------------------------------------------------
    print("\n" + "=" * 60)
    print("[3] SHORT STRONG 전수검사")
    print("=" * 60)

    short_strong_list = [c for c in all_analyzed if c.get("short_grade") == "STRONG_CANDIDATE"]
    print(f"SHORT STRONG Total: {len(short_strong_list)}개")

    overheated_err = 0
    flow_err = 0
    data_err = 0

    for c in short_strong_list:
        name = c.get("name")
        ticker = c.get("ticker")
        overheated = c.get("overheated", False)
        flow_p = c.get("flow_pattern")
        rsi = c.get("rsi")
        today_act = c.get("today_action")

        if overheated:
            overheated_err += 1
            print(f"  [OVERHEATED ERR] {name}({ticker}) is overheated but SHORT STRONG")
        if flow_p == "DETERIORATING":
            flow_err += 1
            print(f"  [FLOW ERR] {name}({ticker}) is DETERIORATING but SHORT STRONG")
        if flow_p == "DATA_INSUFFICIENT" or not c.get("data_available", True):
            data_err += 1
            print(f"  [DATA ERR] {name}({ticker}) is DATA_INSUFFICIENT but SHORT STRONG")

        print(f"  [{c.get('asset_type')}] {name}({ticker}) | Flow:{flow_p} | Action:{today_act} | RSI:{rsi} | Overheated:{overheated} | Reasons:{c.get('short_reasons')}")

    print(f"\nSHORT STRONG Errors - Overheated: {overheated_err}, Flow: {flow_err}, Data: {data_err}")

    # -------------------------------------------------------------
    # [4] ETF 유형 & 기본 MID Pool 오염 검사
    # -------------------------------------------------------------
    print("\n" + "=" * 60)
    print("[4] ETF Eligibility & Default Pool Contamination")
    print("=" * 60)

    etf_top_mid = full_res["etf_results"]["mid_top"]
    inverse_cnt = sum(1 for c in etf_analyzed if c.get("etf_type") == "INVERSE")
    leveraged_cnt = sum(1 for c in etf_analyzed if c.get("etf_type") == "LEVERAGED")
    bond_cnt = sum(1 for c in etf_analyzed if c.get("etf_type") == "BOND_RATE")
    single_cnt = sum(1 for c in etf_analyzed if c.get("etf_type") == "SINGLE_STOCK")
    mmf_cnt = sum(1 for c in etf_analyzed if c.get("etf_type") == "MONEY_MARKET")

    pool_contamination = sum(1 for c in etf_top_mid if c.get("etf_type") in ["INVERSE", "LEVERAGED", "BOND_RATE", "SINGLE_STOCK", "MONEY_MARKET"])

    print(f"Total ETF Stage 3 Breakdown:")
    print(f"  INVERSE: {inverse_cnt}")
    print(f"  LEVERAGED: {leveraged_cnt}")
    print(f"  BOND_RATE: {bond_cnt}")
    print(f"  SINGLE_STOCK: {single_cnt}")
    print(f"  MONEY_MARKET: {mmf_cnt}")
    print(f"Default Mid Recommendation Top Pool Contamination Count: {pool_contamination} (must be 0)")

    # -------------------------------------------------------------
    # [5] Concurrency Performance Test (Workers 3, 5, 8)
    # -------------------------------------------------------------
    print("\n" + "=" * 60)
    print("[5] Concurrency Workers Benchmark (Cold Runs)")
    print("=" * 60)

    for w in [3, 5, 8]:
        _QUANT_CHART_CACHE.clear()
        t0 = time.time()
        res_s = analyze_candidates_quant_parallel(stock_candidates, max_workers=w)
        res_e = analyze_candidates_quant_parallel(etf_candidates, max_workers=w)
        dur = time.time() - t0
        success_cnt = sum(1 for c in (res_s + res_e) if c.get("data_available", True))
        print(f"Workers={w} | Time: {dur:.2f}s | Success Rate: {success_cnt}/{len(stock_candidates)+len(etf_candidates)} ({success_cnt/(len(stock_candidates)+len(etf_candidates))*100:.1f}%)")

    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
