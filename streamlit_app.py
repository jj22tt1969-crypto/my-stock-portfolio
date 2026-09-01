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

# 2. 커스텀 CSS 디자인 (고급 다크 퀀트 테마)
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
    /* 상단 지수 전광판 카드 */
    .market-card {
        background: rgba(20, 28, 43, 0.8);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 12px 16px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .market-label {
        font-size: 0.82rem;
        color: #8A99AD;
        margin-bottom: 4px;
        font-weight: 500;
    }
    .market-val {
        font-size: 1.15rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    .market-change-up { color: #FF4D4D; font-size: 0.85rem; font-weight: 600; }
    .market-change-down { color: #4D94FF; font-size: 0.85rem; font-weight: 600; }
    
    /* 요약 메트릭 박스 */
    .summary-card-box {
        background: linear-gradient(135deg, rgba(20, 28, 43, 0.9) 0%, rgba(15, 22, 35, 0.9) 100%);
        border: 1px solid rgba(0, 229, 255, 0.2);
        border-radius: 14px;
        padding: 18px;
        text-align: center;
    }
    .summary-title { font-size: 0.85rem; color: #94A3B8; font-weight: 500; }
    .summary-value { font-size: 1.4rem; font-weight: 800; color: #F8FAFC; margin-top: 4px; }
    
    /* 세이프 스코어 태그 */
    .badge-buy { background: rgba(16, 185, 129, 0.2); color: #10B981; padding: 4px 8px; border-radius: 6px; font-weight: 600; }
    .badge-sell { background: rgba(239, 68, 68, 0.2); color: #EF4444; padding: 4px 8px; border-radius: 6px; font-weight: 600; }
    .badge-hold { background: rgba(245, 158, 11, 0.2); color: #F59E0B; padding: 4px 8px; border-radius: 6px; font-weight: 600; }

    /* 모바일 가시성 조절 */
    @media (max-width: 768px) {
        .summary-value { font-size: 1.1rem; }
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
    ("KOSPI", "코스피", col_m1),
    ("KOSDAQ", "코스닥", col_m2),
    ("USDKRW", "USD/KRW", col_m3),
    ("SP500", "S&P 500", col_m4),
    ("NASDAQ", "나스닥", col_m5)
]

for key, label, col in indices_config:
    with col:
        if key in market_data and market_data[key].get("price"):
            item = market_data[key]
            price_str = f"{item['price']:,}"
            change_rate = item.get('change_rate', 0.0)
            change_str = f"{'+' if change_rate > 0 else ''}{change_rate:.2f}%"
            delta_color = "normal" if change_rate == 0 else ("inverse" if key == "USDKRW" and change_rate > 0 else "normal")
            st.metric(label=label, value=price_str, delta=change_str, delta_color=delta_color)
        else:
            st.metric(label=label, value="-", delta="-")

# 지수 차트 보기 확장의
with st.expander("📈 주요 시장 지수 및 환율 6개월 추이 차트 보기"):
    sel_idx = st.selectbox("지수 선택", ["KOSPI", "KOSDAQ", "USDKRW", "SP500", "NASDAQ"])
    if sel_idx:
        hist = fetch_market_index_history(sel_idx, count=180)
        if hist.get("dates"):
            fig_idx = go.Figure()
            fig_idx.add_trace(go.Scatter(
                x=hist["dates"], y=hist["prices"],
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

# 5. 사이드바 메뉴 구현
st.sidebar.header("📁 ASSET PORTFOLIO")
main_tab = st.sidebar.radio(
    "메뉴 선택",
    ["📈 개별종목 포트폴리오", "🧺 ETF 포트폴리오", "🤖 AI Q&A 리포트", "➕ 종목 관리 & 물타기 계산기", "📅 주요 경제 일정"]
)

# ---------------------------------------------------------
# TAB 1 & TAB 2: 개별종목 및 ETF 포트폴리오
# ---------------------------------------------------------
if main_tab in ["📈 개별종목 포트폴리오", "🧺 ETF 포트폴리오"]:
    asset_type = "STOCK" if main_tab == "📈 개별종목 포트폴리오" else "ETF"
    
    st.subheader(f"{'📈 개별주식' if asset_type == 'STOCK' else '🧺 ETF'} 포트폴리오 현황")
    
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
        st.warning(f"등록된 {asset_type} 포트폴리오 종목이 없습니다. '➕ 종목 관리' 메뉴에서 종목을 추가해 주세요.")
    else:
        # 종목 데이터 테이블 표출
        df_display = []
        for s in stocks:
            ret_rate = s.get("return_rate", 0.0)
            df_display.append({
                "ID": s.get("id"),
                "종목명": s.get("name"),
                "종목코드": s.get("ticker"),
                "현재가": f"{s.get('current_price', 0):,}원",
                "매입단가": f"{s.get('avg_price', 0):,}원",
                "수량": f"{s.get('quantity', 0):,}주",
                "평가금액": f"{s.get('eval_amount', 0):,}원",
                "평가손익": f"{s.get('profit_loss', 0):,}원",
                "수익률": f"{ret_rate:+.2f}%",
                "수급 점수": s.get("flow_score", 0),
                "의사결정": s.get("decision_action", "HOLD"),
                "추천 사유": s.get("decision_reason", "")
            })
        
        st.dataframe(pd.DataFrame(df_display), use_container_width=True)

        st.subheader("📊 종목별 기술적 차트 & 외국인/기관 수급 상세 분석")
        selected_stock_name = st.selectbox(
            "상세 분석할 종목 선택",
            [s["name"] for s in stocks]
        )

        target_stock = next((s for s in stocks if s["name"] == selected_stock_name), None)
        if target_stock:
            t_code = target_stock["ticker"]
            chart_res = fetch_stock_chart_analysis(t_code, timeframe="day")
            
            if chart_res.get("dates"):
                # Plotly 차트 구현 (주가, 이동평균선, 거래량, MFI)
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                
                # 캔들스틱 / 종가선
                fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["close"], mode='lines', name='종가', line=dict(color='#00E5FF', width=2)), row=1, col=1)
                if chart_res.get("ma5"):
                    fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["ma5"], mode='lines', name='MA5', line=dict(color='#FFD700', width=1)), row=1, col=1)
                if chart_res.get("ma20"):
                    fig.add_trace(go.Scatter(x=chart_res["dates"], y=chart_res["ma20"], mode='lines', name='MA20', line=dict(color='#FF4500', width=1)), row=1, col=1)
                
                # 거래량
                fig.add_trace(go.Bar(x=chart_res["dates"], y=chart_res["volume"], name='거래량', marker_color='#3B82F6'), row=2, col=1)

                fig.update_layout(
                    title=f"{selected_stock_name} ({t_code}) 6개월 추이 차트",
                    template="plotly_dark",
                    height=450,
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)

            # 수급 및 종합 의사결정 결과
            flow_info = get_stock_flow_data(t_code, min_days=30)
            if flow_info.get("data_available"):
                dec_res = analyze_stock_decision(flow_info["df"], return_rate=target_stock.get("return_rate", 0.0))
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.success(f"🎯 **종합 AI 판단**: {dec_res.get('action')} (안전 스코어: {dec_res.get('safety_score')}점)")
                    st.write(f"**수급 점수**: {dec_res.get('flow_score')}점")
                    st.write(f"**기술적 점수**: {dec_res.get('tech_score')}점")
                with col_d2:
                    st.info(f"💡 **분석 요약**: {dec_res.get('summary')}")

# ---------------------------------------------------------
# TAB 3: AI Q&A 리포트
# ---------------------------------------------------------
elif main_tab == "🤖 AI Q&A 리포트":
    st.subheader("🤖 AI 주식/ETF 전문 Q&A 리포트")
    st.caption("실시간 증권 뉴스 및 DART 공시, ETF 운용사 공식 자료에 기반한 답변을 생성합니다.")

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
