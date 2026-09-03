import math
from typing import Dict, Any, List
from backend.db import database as db
from backend.data.collector import get_stock_flow_data
from backend.engine.flow_engine import analyze_stock_flow
from backend.engine.technical_engine import calculate_technical_indicators
from backend.engine.decision_engine import analyze_stock_decision

def calculate_additional_buy(
    current_price: float,
    current_avg_price: float,
    current_qty: int,
    add_price: float,
    add_qty: int = 0,
    add_amount: float = 0.0
) -> Dict[str, Any]:
    """
    추가매수(물타기/불타기) 시뮬레이션 계산기
    """
    if add_qty <= 0 and add_amount > 0 and add_price > 0:
        add_qty = math.floor(add_amount / add_price)

    if add_qty <= 0:
        return {
            "success": False,
            "error": "추가수량 또는 추가투자금액을 올바르게 입력해주세요."
        }

    total_current_invested = current_avg_price * current_qty
    total_additional_invested = add_price * add_qty
    
    new_total_qty = current_qty + add_qty
    new_total_invested = total_current_invested + total_additional_invested
    new_avg_price = new_total_invested / new_total_qty if new_total_qty > 0 else 0

    if current_price > 0:
        break_even_rate = ((new_avg_price - current_price) / current_price) * 100
    else:
        break_even_rate = 0.0

    prev_break_even_rate = ((current_avg_price - current_price) / current_price * 100) if current_price > 0 else 0.0
    break_even_improvement = prev_break_even_rate - break_even_rate

    return {
        "success": True,
        "current_price": current_price,
        "prev_avg_price": current_avg_price,
        "prev_qty": current_qty,
        "add_price": add_price,
        "add_qty": add_qty,
        "add_invested": total_additional_invested,
        "new_avg_price": round(new_avg_price, 2),
        "new_total_qty": new_total_qty,
        "new_total_invested": new_total_invested,
        "break_even_rate": round(break_even_rate, 2),
        "prev_break_even_rate": round(prev_break_even_rate, 2),
        "break_even_improvement": round(break_even_improvement, 2)
    }


import time

_PORTFOLIO_ANALYSIS_CACHE = {}
_PORTFOLIO_CACHE_TTL = 30

def invalidate_portfolio_cache(asset_type: str = None):
    """
    종목 추가/수정/삭제 시 포트폴리오 캐시 무효화
    """
    global _PORTFOLIO_ANALYSIS_CACHE
    if asset_type:
        _PORTFOLIO_ANALYSIS_CACHE.pop(asset_type.upper(), None)
    else:
        _PORTFOLIO_ANALYSIS_CACHE.clear()

def analyze_portfolio(asset_type: str = "STOCK") -> Dict[str, Any]:
    """
    사용자의 포트폴리오 분석 (asset_type: 'STOCK' 또는 'ETF' 지원, 30초 메모리 캐시 적용)
    """
    target_asset_type = asset_type.upper() if asset_type else "STOCK"
    now_ts = time.time()

    if target_asset_type in _PORTFOLIO_ANALYSIS_CACHE:
        cached_ts, cached_res = _PORTFOLIO_ANALYSIS_CACHE[target_asset_type]
        if now_ts - cached_ts < _PORTFOLIO_CACHE_TTL:
            return cached_res

    stocks = db.get_all_stocks(asset_type=target_asset_type)
    
    if not stocks:
        empty_res = {
            "portfolio_empty": True,
            "message": "등록된 포트폴리오 종목이 없습니다. 종목을 추가해보세요.",
            "summary": {
                "total_invested": 0,
                "total_eval": 0,
                "total_profit_loss": 0,
                "total_return_rate": 0.0,
                "today_profit_loss": 0
            },
            "items": [],
            "analysis": {}
        }
        _PORTFOLIO_ANALYSIS_CACHE[target_asset_type] = (now_ts, empty_res)
        return empty_res


    # 종목별 수급 및 실시간 주가 데이터 병렬 수집
    from concurrent.futures import ThreadPoolExecutor

    def process_single_stock(stock):
        ticker = stock["ticker"]
        avg_price = float(stock["avg_price"])
        flow_data = get_stock_flow_data(ticker, min_days=30)
        
        current_price = avg_price
        diff = 0.0
        decision_result = {}
        
        if flow_data.get("data_available", False):
            df = flow_data["df"]
            latest_row = df.iloc[-1]
            current_price = float(latest_row['close_price'])
            diff = float(latest_row['diff'])

            return_rate_tmp = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            decision_result = analyze_stock_decision(df, return_rate=return_rate_tmp)
            
        return {
            "stock": stock,
            "current_price": current_price,
            "diff": diff,
            "decision_result": decision_result
        }

    with ThreadPoolExecutor(max_workers=min(len(stocks), 16)) as executor:
        stock_results = list(executor.map(process_single_stock, stocks))


    items = []
    total_invested = 0.0
    total_eval = 0.0
    today_profit_loss = 0.0
    
    sector_invested_map = {}
    profit_stocks = []
    loss_stocks = []

    for res in stock_results:
        stock = res["stock"]
        ticker = stock["ticker"]
        name = stock["name"]
        avg_price = float(stock["avg_price"])
        quantity = int(stock["quantity"])
        invested = avg_price * quantity
        total_invested += invested

        current_price = res["current_price"]
        diff = res["diff"]
        decision_result = res["decision_result"]

        eval_amount = current_price * quantity
        total_eval += eval_amount
        
        profit_loss = eval_amount - invested
        return_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
        
        today_stock_pl = diff * quantity
        today_profit_loss += today_stock_pl

        sector = stock.get("sector") or "기타"
        sector_invested_map[sector] = sector_invested_map.get(sector, 0.0) + eval_amount

        flow_analysis = decision_result.get("flow_analysis", {})
        tech_analysis = decision_result.get("technical_analysis", {})
        decision_info = decision_result.get("decision", {})

        item_summary = {
            "id": stock["id"],
            "name": name,
            "ticker": ticker,
            "avg_price": avg_price,
            "quantity": quantity,
            "buy_date": stock.get("buy_date", ""),
            "investment_purpose": stock.get("investment_purpose", ""),
            "sector": sector,
            "current_price": current_price,
            "invested_amount": invested,
            "eval_amount": eval_amount,
            "profit_loss": profit_loss,
            "return_rate": round(return_rate, 2),
            "today_profit_loss": today_stock_pl,
            "weight": 0.0,
            
            # 수급 & 기술적 분석 데이터
            "ffcs_score": flow_analysis.get("ffcs_score", None),
            "cycle_stage": flow_analysis.get("cycle_stage", "데이터 없음"),
            "foreign_direction": flow_analysis.get("foreign_direction", "N/A"),
            "institution_direction": flow_analysis.get("institution_direction", "N/A"),
            "concurrency": flow_analysis.get("concurrency", {}).get("description", "N/A"),
            "divergence": flow_analysis.get("divergence", {}).get("title", "N/A"),
            
            # PHASE 4: 최종 판단 & Score 데이터
            "final_decision": decision_info.get("decision", "HOLD"),
            "final_decision_desc": decision_info.get("decision_desc", "보유 관망"),
            "buy_score": decision_info.get("buy_score", 50.0),
            "buy_grade": decision_info.get("buy_grade", "관망"),
            "sell_score": decision_info.get("sell_score", 0.0),
            "sell_grade": decision_info.get("sell_grade", "보유"),
            "watering_score": decision_info.get("watering_score", 50.0),
            "watering_action": decision_info.get("watering_action", "관망"),
            "ai_reasons": decision_info.get("ai_reasons", []),
            "technical": {
                "ma5": tech_analysis.get("ma5"),
                "ma20": tech_analysis.get("ma20"),
                "ma60": tech_analysis.get("ma60"),
                "rsi": tech_analysis.get("rsi"),
                "macd": tech_analysis.get("macd", {}).get("macd"),
                "support_level": tech_analysis.get("support_level"),
                "resistance_level": tech_analysis.get("resistance_level")
            }
        }
        
        if profit_loss > 0:
            profit_stocks.append(item_summary)
        elif profit_loss < 0:
            loss_stocks.append(item_summary)

        items.append(item_summary)

    # 비중 연산 (%)
    max_weight_stock = None
    max_weight = -1.0

    for item in items:
        weight = (item["eval_amount"] / total_eval * 100) if total_eval > 0 else 0.0
        item["weight"] = round(weight, 2)
        if weight > max_weight:
            max_weight = weight
            max_weight_stock = item

    # 업종별 비중 (%)
    sector_weights = {}
    for sector, eval_sum in sector_invested_map.items():
        sector_weights[sector] = round((eval_sum / total_eval * 100), 2) if total_eval > 0 else 0.0

    total_profit_loss = total_eval - total_invested
    total_return_rate = ((total_eval - total_invested) / total_invested * 100) if total_invested > 0 else 0.0

    # 위험 집중도 분석
    top3_weight_sum = sum(sorted([item["weight"] for item in items], reverse=True)[:3])
    risk_level = "LOW"
    risk_desc = "포트폴리오 비중이 안정적으로 분산되어 있습니다."
    if max_weight >= 40.0 or top3_weight_sum >= 70.0:
        risk_level = "HIGH"
        risk_desc = f"특정 종목 비중이 커서 변동성 위험이 높습니다. (최대비중: {max_weight:.1f}%)"
    elif max_weight >= 25.0:
        risk_level = "MEDIUM"
        risk_desc = f"주요 종목 비중이 높은 편입니다. (최대비중: {max_weight:.1f}%)"

    res = {
        "portfolio_empty": False,
        "summary": {
            "total_invested": round(total_invested, 0),
            "total_eval": round(total_eval, 0),
            "total_profit_loss": round(total_profit_loss, 0),
            "total_return_rate": round(total_return_rate, 2),
            "today_profit_loss": round(today_profit_loss, 0)
        },
        "items": items,
        "analysis": {
            "total_stock_count": len(items),
            "profit_stock_count": len(profit_stocks),
            "loss_stock_count": len(loss_stocks),
            "profit_stocks": profit_stocks,
            "loss_stocks": loss_stocks,
            "max_weight_stock": {
                "name": max_weight_stock["name"] if max_weight_stock else "N/A",
                "ticker": max_weight_stock["ticker"] if max_weight_stock else "N/A",
                "weight": max_weight_stock["weight"] if max_weight_stock else 0.0
            },
            "sector_weights": sector_weights,
            "risk_concentration": {
                "level": risk_level,
                "description": risk_desc,
                "top3_weight_sum": round(top3_weight_sum, 2)
            }
        }
    }
    _PORTFOLIO_ANALYSIS_CACHE[target_asset_type] = (now_ts, res)
    return res


def get_portfolio_live_prices(asset_type: str = "STOCK") -> Dict[str, Any]:
    """
    15초 실시간 자동 타이머 전용 초경량 주가/수익률/손익 수치 반환 함수
    - 180일 일봉 파싱 및 복잡한 기술 지표 분석 없이 0.01초 내에 현재가 수치만 반환하여 10배 이상 빠름.
    """
    target_asset_type = asset_type.upper() if asset_type else "STOCK"
    stocks = db.get_all_stocks(asset_type=target_asset_type)
    if not stocks:
        return {"status": "success", "summary": {}, "items": []}

    from concurrent.futures import ThreadPoolExecutor

    def fetch_live_price_single(stock):
        ticker = stock["ticker"]
        avg_price = float(stock["avg_price"])
        quantity = int(stock["quantity"])
        
        flow_data = get_stock_flow_data(ticker, min_days=5)
        current_price = avg_price
        diff = 0.0
        
        if flow_data.get("data_available", False):
            df = flow_data["df"]
            latest_row = df.iloc[-1]
            current_price = float(latest_row['close_price'])
            diff = float(latest_row['diff'])
            
        eval_amount = current_price * quantity
        invested_amount = avg_price * quantity
        pl = eval_amount - invested_amount
        ret = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
        
        return {
            "id": stock["id"],
            "ticker": ticker,
            "name": stock["name"],
            "current_price": current_price,
            "diff": diff,
            "eval_amount": eval_amount,
            "invested_amount": invested_amount,
            "pl": pl,
            "ret": ret,
            "today_pl": diff * quantity
        }

    with ThreadPoolExecutor(max_workers=min(len(stocks), 16)) as executor:
        item_results = list(executor.map(fetch_live_price_single, stocks))

    total_invested = sum(r["invested_amount"] for r in item_results)
    total_eval = sum(r["eval_amount"] for r in item_results)
    total_pl = total_eval - total_invested
    total_ret = (total_pl / total_invested * 100) if total_invested > 0 else 0.0
    today_pl = sum(r["today_pl"] for r in item_results)

    return {
        "status": "success",
        "asset_type": target_asset_type,
        "summary": {
            "total_invested": round(total_invested, 0),
            "total_eval": round(total_eval, 0),
            "total_profit_loss": round(total_pl, 0),
            "total_return_rate": round(total_ret, 2),
            "today_profit_loss": round(today_pl, 0)
        },
        "items": item_results
    }

