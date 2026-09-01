import os
import sys
import datetime
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# 프로젝트 루트 경로 등록
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 백엔드 엔진 모듈 가져오기
from backend.data.market_collector import fetch_market_indices, fetch_stock_news, fetch_market_index_history
from backend.data.collector import get_stock_flow_data, resolve_ticker, fetch_stock_chart_analysis
from backend.engine.flow_engine import analyze_stock_flow
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.stock_identifier import search_all_stock_or_etf, search_stock_or_etf
from backend.engine.calendar_engine import fetch_upcoming_events
from backend.engine import portfolio_engine as pe
from backend.db import database as db
from backend.engine.qna_llm_engine import generate_grounded_qna_answer
from backend.engine.official_engine import fetch_official_documents
from backend.engine.news_engine import fetch_qna_stock_news

# 1. 페이지 설정
st.set_page_config(
    page_title="QUANT AI PORTFOLIO",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# DB 초기화 검증
try:
    db.init_db()
except Exception:
    pass

# 2. 커스텀 CSS 디자인 (고급 퀀트 카드 다크 테마)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;500;600;700;800&display=swap');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    .stApp {
        background-color: #0A0E17;
        color: #E0E6ED;
    }
    /* 종목 고급 카드 스타일 */
    .stock-card {
        background: linear-gradient(145deg, #141C2B 0%, #0F172A 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .stock-card:hover {
        border-color: rgba(0, 229, 255, 0.4);
    }
    .stock-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }
    .stock-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #F8FAFC;
    }
    .stock-ticker {
        font-size: 0.85rem;
        color: #64748B;
        margin-left: 6px;
    }
    .badge-action {
        padding: 5px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.82rem;
        display: inline-block;
    }
    .act-buy { background: rgba(16, 185, 129, 0.2); color: #10B981; border: 1px solid #10B981; }
    .act-sell { background: rgba(239, 68, 68, 0.2); color: #EF4444; border: 1px solid #EF4444; }
    .act-water { background: rgba(59, 130, 246, 0.2); color: #3B82F6; border: 1px solid #3B82F6; }
    .act-hold { background: rgba(245, 158, 11, 0.2); color: #F59E0B; border: 1px solid #F59E0B; }
    
    .val-up { color: #FF4D4D; font-weight: 700; }
    .val-down { color: #4D94FF; font-weight: 700; }
    
    .info-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        background: rgba(10, 14, 23, 0.6);
        padding: 12px;
        border-radius: 10px;
        margin-top: 10px;
    }
    .info-item {
        text-align: center;
    }
    .info-lbl {
        font-size: 0.75rem;
        color: #94A3B8;
    }
    .info-val {
        font-size: 0.95rem;
        font-weight: 600;
        color: #E2E8F0;
        margin-top: 2px;
    }
</style>
""", unsafe_allow_html=True)

# 3. 데이터 캐싱 & 헬퍼 함수
@st.cache_data(ttl=60)
def load_market_overview():
    return fetch_market_indices()

@st.cache_data(ttl=300)
def load_portfolio_data(asset_type="STOCK"):
    return pe.analyze_portfolio(asset_type=asset_type)

# 헤더 타이틀
st.title("⚡ QUANT AI PORTFOLIO")
st.caption("외국인/기관 수급 사이클 & AI 주식 투자 의사결정 대시보드")

# 4. 상단 시장 지수 전광판 (KOSPI, KOSDAQ, 환율, S&P 500, NASDAQ)
market_data = load_market_overview()
col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)

indices_config = [
    ("kospi", "코스피", col_m1),
    ("kosdaq", "코스닥", col_m2),
    ("exchange_rate", "USD/KRW", col_m3),
    ("sp500", "S&P 500", col_m4),
    ("nasdaq", "나스닥", col_m5)
]

indices_dict = market_data.get("indices", {}) if isinstance(market_data, dict) else {}

for key, label, col in indices_config:
    with col:
        if key in indices_dict and indices_dict[key].get("value"):
            item = indices_dict[key]
            val = item['value']
            price_str = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
            change_rate = item.get('rate', 0.0)
            change_str = f"{'+' if change_rate > 0 else ''}{change_rate:.2f}%"
            delta_color = "normal" if change_rate == 0 else ("inverse" if key == "exchange_rate" and change_rate > 0 else "normal")
            st.metric(label=label, value=price_str, delta=change_str, delta_color=delta_color)
        else:
            st.metric(label=label, value="-", delta="-")

# 지수 차트 보기 확장의
with st.expander("📈 주요 시장 지수 및 환율 6개월 추이 차트 보기"):
    sel_idx = st.selectbox("지수 선택", ["KOSPI", "KOSDAQ", "USDKRW", "SP500", "NASDAQ"])
    if sel_idx:
        hist = fetch_market_index_history(sel_idx, count=180)
        if hist.get("status") == "success" and hist.get("dates") and hist.get("closes"):
            fig_idx = go.Figure()
            fig_idx.add_trace(go.Scatter(
                x=hist["dates"], y=hist["closes"],
                mode='lines', name=sel_idx,
                line=dict(color='#00E5FF', width=2)
            ))
            fig_idx.update_layout(
                title=f"{sel_idx} 최근 6개월 추이",
                template="plotly_dark",
                height=300,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig_idx, use_container_width=True)

st.divider()

# 5. 사이드바 메뉴 구현 (기본값: 개별종목 포트폴리오)
st.sidebar.header("📁 ASSET PORTFOLIO")
main_tab = st.sidebar.radio(
    "메뉴 선택",
    ["📈 개별종목 포트폴리오", "🧺 ETF 포트폴리오", "🤖 AI Q&A 리포트", "➕ 종목 관리 & 물타기 계산기", "📅 주요 경제 일정"],
    index=0
)

# ---------------------------------------------------------
# TAB 1 & TAB 2: 개별종목 및 ETF 포트폴리오
# ---------------------------------------------------------
if main_tab in ["📈 개별종목 포트폴리오", "🧺 ETF 포트폴리오"]:
    asset_type = "STOCK" if main_tab == "📈 개별종목 포트폴리오" else "ETF"
    
    st.subheader(f"{'📈 개별주식' if asset_type == 'STOCK' else '🧺 ETF'} 포트폴리오 현황")
    
    col_ref, col_info = st.columns([2, 8])
    with col_ref:
        if st.button("🔄 실시간 시세 새로고침"):
            pe.invalidate_portfolio_cache(asset_type)
            st.cache_data.clear()
            st.rerun()

    p_data = load_portfolio_data(asset_type)
    summary = p_data.get("summary", {})
    stocks = p_data.get("stocks", [])

    # 요약 메트릭 5개
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 투자금액", f"{summary.get('total_invested', 0):,} 원")
    c2.metric("총 평가금액", f"{summary.get('total_eval', 0):,} 원")
    
    profit_loss = summary.get('total_profit_loss', 0)
    c3.metric("총 평가손익", f"{profit_loss:,} 원", delta=f"{summary.get('total_return_rate', 0):.2f}%")
    c4.metric("총 수익률", f"{summary.get('total_return_rate', 0):.2f}%")
    
    today_pl = summary.get('today_profit_loss', 0)
    c5.metric("오늘 손익", f"{today_pl:,} 원", delta=f"{today_pl:,} 원")

    # 위험 집중도 경고 바
    risk_info = summary.get("risk_analysis", {})
    if risk_info:
        risk_level = risk_info.get("level", "보통")
        risk_color = "red" if risk_level == "위험" else ("orange" if risk_level == "경고" else "green")
        st.info(f"🛡️ **위험 집중도 평가**: :{risk_color}[{risk_level}] - {risk_info.get('description', '')}")

    st.markdown("---")

    if not stocks:
        st.warning(f"등록된 {asset_type} 포트폴리오 종목이 없습니다. 💡 좌측 메뉴의 **'➕ 종목 관리 & 물타기 계산기'**에서 원하는 종목을 추가해 보세요!")
    else:
        # 종목들을 예쁜 카드(Card) 그리드로 출력
        st.markdown(f"### 📊 보유 {asset_type} 종목 리스트 ({len(stocks)}개)")
        
        for s in stocks:
            ret_rate = s.get("return_rate", 0.0)
            ret_class = "val-up" if ret_rate > 0 else ("val-down" if ret_rate < 0 else "")
            ret_sign = "+" if ret_rate > 0 else ""
            
            act = s.get("decision_action", "HOLD").upper()
            act_css = "act-buy" if "BUY" in act else ("act-sell" if "SELL" in act else ("act-water" if "WATER" in act else "act-hold"))

            with st.container():
                st.markdown(f"""
                <div class="stock-card">
                    <div class="stock-header">
                        <div>
                            <span class="stock-title">{s.get('name')}</span>
                            <span class="stock-ticker">({s.get('ticker')}) · {s.get('sector', '기타')}</span>
                        </div>
                        <div>
                            <span class="badge-action {act_css}">AI 추천: {act}</span>
                        </div>
                    </div>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-lbl">현재가</div>
                            <div class="info-val">{s.get('current_price', 0):,} 원</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">매입단가</div>
                            <div class="info-val">{s.get('avg_price', 0):,} 원</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">보유수량</div>
                            <div class="info-val">{s.get('quantity', 0):,} 주</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">수익률</div>
                            <div class="info-val {ret_class}">{ret_sign}{ret_rate:.2f}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">평가금액</div>
                            <div class="info-val">{s.get('eval_amount', 0):,} 원</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">평가손익</div>
                            <div class="info-val {ret_class}">{s.get('profit_loss', 0):,} 원</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">수급 스코어</div>
                            <div class="info-val" style="color:#00E5FF;">{s.get('flow_score', 0)} 점</div>
                        </div>
                        <div class="info-item">
                            <div class="info-lbl">안전 스코어</div>
                            <div class="info-val" style="color:#10B981;">{s.get('safety_score', 0)} 점</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 각 종목별 상세 분석 및 차트 확장 영역
                with st.expander(f"🔍 [{s.get('name')}] 6개월 주가 차트 및 외국인/기관 수급 상세 분석 열기"):
                    t_code = s["ticker"]
                    chart_res = fetch_stock_chart_analysis(t_code, timeframe="day")
                    
                    if chart_res.get("dates"):
                        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                        fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["close"], mode='lines', name='종가', line=dict(color='#00E5FF', width=2)), row=1, col=1)
                        if chart_res.get("ma5"):
                            fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["ma5"], mode='lines', name='MA5', line=dict(color='#FFD700', width=1)), row=1, col=1)
                        if chart_res.get("ma20"):
                            fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["ma20"], mode='lines', name='MA20', line=dict(color='#FF4500', width=1)), row=1, col=1)
                        fig.add_trace(go.Bar(x=chart_res["dates"], y=chart_res["volume"], name='거래량', marker_color='#3B82F6'), row=2, col=1)

                        fig.update_layout(
                            title=f"{s.get('name')} 6개월 주가 & 거래량 추이",
                            template="plotly_dark",
                            height=400,
                            margin=dict(l=20, r=20, t=40, b=20)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    flow_info = get_stock_flow_data(t_code, min_days=30)
                    if flow_info.get("data_available"):
                        dec_res = analyze_stock_decision(flow_info["df"], return_rate=s.get("return_rate", 0.0))
                        st.success(f"💡 **AI 종합 의견**: {dec_res.get('summary')}")
                    
                    # 실시간 뉴스 3건
                    news_data = fetch_stock_news(t_code, s.get('name'), count=3)
                    news_list = news_data.get("news", [])
                    if news_list:
                        st.markdown("##### 📰 관련 최신 뉴스")
                        for nw in news_list:
                            st.write(f"- [{nw.get('title')}]({nw.get('url')}) ({nw.get('date')})")

# ---------------------------------------------------------
# TAB 3: AI Q&A 리포트
# ---------------------------------------------------------
elif main_tab == "🤖 AI Q&A 리포트":
    st.subheader("🤖 AI 주식/ETF 전문 Q&A 리포트")
    st.caption("실시간 증권 뉴스 및 DART 공시, ETF 운용사 공식 자료에 기반한 분석 보고서를 생성합니다.")

    query_stock = st.text_input("분석하고 싶은 종목명 또는 코드/주제 입력 (예: 삼성전자, HBM 전망, KODEX 200)", "삼성전자")
    
    if st.button("🚀 AI 리포트 생성"):
        with st.spinner("최신 뉴스 및 DART 공시 문서를 수집하여 종합 분석 보고서를 작성 중입니다..."):
            ticker_c, name_c = resolve_ticker(query_stock)
            ans = generate_grounded_qna_answer(ticker=ticker_c or "", name=name_c or query_stock, query=query_stock)
            
            st.markdown(ans.get("answer", "답변을 생성하지 못했습니다."))
            
            citations = ans.get("citations", [])
            if citations:
                st.divider()
                st.markdown("### 📚 참조된 실시간 출처 & 근거 문서")
                for idx, c in enumerate(citations, 1):
                    st.write(f"{idx}. [{c.get('source_type')}] **{c.get('title')}** ({c.get('date', '')}) - [링크]({c.get('url')})")

# ---------------------------------------------------------
# TAB 4: 종목 관리 & 물타기(추가매수) 계산기
# ---------------------------------------------------------
elif main_tab == "➕ 종목 관리 & 물타기 계산기":
    st.subheader("➕ 종목 추가 및 포트폴리오 관리")
    
    tab_add, tab_sim, tab_manage = st.tabs(["[종목 신규 등록]", "[물타기/추가매수 계산기]", "[기존 종목 수정/삭제]"])
    
    with tab_add:
        st.markdown("#### 포트폴리오 종목 등록")
        with st.form("add_stock_form"):
            stock_input = st.text_input("종목명 또는 6자리 종목코드", placeholder="예: 카카오, 035720")
            avg_p = st.number_input("평균 매입 단가 (원)", min_value=1.0, value=50000.0, step=100.0)
            qty = st.number_input("보유 수량 (주)", min_value=1, value=10, step=1)
            b_date = st.date_input("매수일", datetime.date.today())
            a_type = st.selectbox("자산 분류", ["STOCK", "ETF"])
            sec = st.text_input("업종/분류", value="IT/반도체")
            
            submitted = st.form_submit_button("포트폴리오에 추가")
            if submitted:
                if stock_input.strip():
                    ticker_code, name = resolve_ticker(stock_input, asset_type_hint=a_type)
                    if not ticker_code:
                        st.error("종목을 찾을 수 없습니다. 이름이나 코드를 확인해주세요.")
                    else:
                        res = db.add_stock(
                            name=name, ticker=ticker_code, avg_price=avg_p, quantity=qty,
                            buy_date=str(b_date), investment_purpose="장기투자", sector=sec,
                            asset_type=a_type, market="KOSPI"
                        )
                        if res.get("success"):
                            pe.invalidate_portfolio_cache(a_type)
                            st.success(f"[{name}] 종목이 성공적으로 추가되었습니다!")
                            st.rerun()

    with tab_sim:
        st.markdown("#### 💡 추가 매수(물타기) 평단가 단축 시뮬레이터")
        all_st = db.get_all_stocks()
        if all_st:
            sel_s = st.selectbox("물타기 시뮬레이션할 보유 종목", options=all_st, format_func=lambda x: f"{x['name']} (평단: {x['avg_price']:,}원, {x['quantity']}주)")
            
            if sel_s:
                add_price = st.number_input("추가 매수할 가격 (원)", min_value=1.0, value=float(sel_s['avg_price'] * 0.9), step=100.0)
                add_qty = st.number_input("추가 매수 수량 (주)", min_value=1, value=10, step=1)
                
                if st.button("계산하기"):
                    calc_res = pe.calculate_additional_buy(
                        current_price=add_price,
                        current_avg_price=sel_s['avg_price'],
                        current_qty=sel_s['quantity'],
                        add_price=add_price,
                        add_qty=add_qty
                    )
                    
                    st.success("📊 **시뮬레이션 결과**")
                    col_res1, col_res2, col_res3 = st.columns(3)
                    col_res1.metric("변경 후 평단가", f"{calc_res['new_avg_price']:,} 원", delta=f"{calc_res['avg_price_change']:,} 원")
                    col_res2.metric("총 수량", f"{calc_res['new_quantity']:,} 주", delta=f"+{add_qty} 주")
                    col_res3.metric("필요 반등률 (손익분기)", f"{calc_res['new_required_bounce']:.2f}%", delta=f"{calc_res['required_bounce_reduction']:.2f}%p 단축")

    with tab_manage:
        st.markdown("#### 보유 종목 삭제 및 관리")
        all_st = db.get_all_stocks()
        if all_st:
            for item in all_st:
                col_i1, col_i2, col_i3 = st.columns([3, 2, 1])
                col_i1.write(f"**{item['name']}** ({item['ticker']}) | {item['asset_type']}")
                col_i2.write(f"{item['avg_price']:,}원 / {item['quantity']}주")
                if col_i3.button("삭제", key=f"del_{item['id']}"):
                    db.delete_stock(item['id'])
                    pe.invalidate_portfolio_cache()
                    st.success(f"{item['name']} 삭제 완료")
                    st.rerun()

# ---------------------------------------------------------
# TAB 5: 주요 경제 일정
# ---------------------------------------------------------
elif main_tab == "📅 주요 경제 일정":
    st.subheader("📅 향후 주요 경제 지표 발표 & 빅테크 실적 일정")
    
    events_res = fetch_upcoming_events(days=7)
    events = events_res.get("events", [])
    
    if events:
        for ev in events:
            st.write(f"🗓️ **{ev.get('date')}** | [{ev.get('category')}] **{ev.get('event_name')}** ({ev.get('importance')} 중요도)")
            st.caption(f"설명: {ev.get('description')}")
            st.divider()
    else:
        st.info("예정된 주요 일정이 없습니다.")
