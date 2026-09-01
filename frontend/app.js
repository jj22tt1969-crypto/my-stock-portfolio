// Global state
let currentPortfolioData = null;
let detailChartInstance = null;

let autoRefreshTimer = null;
let countdownTimer = null;
let refreshSecondsLeft = 15;
let previousStockPrices = {};

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initApp();
});

// ==========================================
// 테마 관리 (다크 미드나잇 vs 회백색 아이케어 모드)
// ==========================================
function initTheme() {
    const savedTheme = localStorage.getItem('app-theme') || 'dark';
    setTheme(savedTheme);
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    localStorage.setItem('app-theme', theme);

    const themeIcon = document.getElementById('themeIcon');
    const themeText = document.getElementById('themeText');
    if (themeIcon && themeText) {
        if (theme === 'light') {
            themeIcon.textContent = '☀️';
            themeText.textContent = '회백색 모드';
        } else {
            themeIcon.textContent = '🌙';
            themeText.textContent = '다크 모드';
        }
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
}

async function initApp() {
    await fetchMarketOverview();
    await fetchPortfolioData();
    startAutoRefresh();
    initAddStockFormEvents();
}

// 1. 실시간 타이머 및 컨트롤 로직
function startAutoRefresh() {
    stopAutoRefresh();
    refreshSecondsLeft = 15;
    updateRefreshTimerUI();

    countdownTimer = setInterval(() => {
        refreshSecondsLeft -= 1;
        if (refreshSecondsLeft <= 0) {
            refreshSecondsLeft = 15;
            // QNA 탭에서는 portfolio API 자동 호출 건너뜀 (불필요한 서버 부하 방지)
            if (currentAssetType !== 'QNA') {
                fetchPortfolioData(true);
            }
            fetchMarketOverview();
        }
        updateRefreshTimerUI();
    }, 1000);
}

function stopAutoRefresh() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = null;
}

function toggleAutoRefresh(enabled) {
    const timerElem = document.getElementById('refreshTimer');
    if (enabled) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
        if (timerElem) timerElem.innerText = '⚡ 실시간 갱신 OFF';
    }
}

function updateRefreshTimerUI() {
    const timerElem = document.getElementById('refreshTimer');
    if (timerElem && countdownTimer) {
        timerElem.innerText = `⚡ 실시간 갱신 ON (${refreshSecondsLeft}s)`;
    }
}

async function manualRefreshPortfolio() {
    const btn = document.getElementById('btnRefresh');
    if (btn) {
        btn.classList.add('spin-anim');
        btn.innerText = '🔄 갱신 중...';
    }
    await fetchMarketOverview();
    await fetchPortfolioData(false);
    
    if (btn) {
        btn.classList.remove('spin-anim');
        btn.innerText = '🔄 실시간 새로고침';
    }
    
    const toggle = document.getElementById('autoRefreshToggle');
    if (toggle && toggle.checked) {
        refreshSecondsLeft = 15;
        updateRefreshTimerUI();
    }
}

// 2. 실시간 시장 지수 수집 및 바 업데이트
async function fetchMarketOverview() {
    try {
        const resp = await fetch('/api/market/overview');
        if (!resp.ok) return;
        const data = await resp.json();
        
        const indices = data.indices || {};
        if (indices.kospi && indices.kospi.value) {
            const c = indices.kospi.change || 0;
            const r = indices.kospi.rate !== undefined ? indices.kospi.rate : null;
            const rateStr = r !== null ? `, ${r >= 0 ? '+' : ''}${r.toFixed(2)}%` : '';
            document.getElementById('kospiVal').innerText = `${indices.kospi.value.toLocaleString()} (${c >= 0 ? '+' : ''}${c}${rateStr})`;
        }
        if (indices.kosdaq && indices.kosdaq.value) {
            const c = indices.kosdaq.change || 0;
            const r = indices.kosdaq.rate !== undefined ? indices.kosdaq.rate : null;
            const rateStr = r !== null ? `, ${r >= 0 ? '+' : ''}${r.toFixed(2)}%` : '';
            document.getElementById('kosdaqVal').innerText = `${indices.kosdaq.value.toLocaleString()} (${c >= 0 ? '+' : ''}${c}${rateStr})`;
        }
        if (indices.exchange_rate && indices.exchange_rate.value) {
            document.getElementById('usdVal').innerText = `${indices.exchange_rate.value.toLocaleString()} 원`;
        }
        if (indices.sp500 && indices.sp500.value) {
            const c = indices.sp500.change || 0;
            const r = indices.sp500.rate !== undefined ? indices.sp500.rate : null;
            const rateStr = r !== null ? `, ${r >= 0 ? '+' : ''}${r.toFixed(2)}%` : '';
            const el = document.getElementById('sp500Val');
            if (el) el.innerText = `${indices.sp500.value.toLocaleString()} (${c >= 0 ? '+' : ''}${c}${rateStr})`;
        }
        if (indices.nasdaq && indices.nasdaq.value) {
            const c = indices.nasdaq.change || 0;
            const r = indices.nasdaq.rate !== undefined ? indices.nasdaq.rate : null;
            const rateStr = r !== null ? `, ${r >= 0 ? '+' : ''}${r.toFixed(2)}%` : '';
            const el = document.getElementById('nasdaqVal');
            if (el) el.innerText = `${indices.nasdaq.value.toLocaleString()} (${c >= 0 ? '+' : ''}${c}${rateStr})`;
        }
    } catch (e) {
        console.warn("Market overview fetch failed:", e);
    }
}

let currentAssetType = 'STOCK';

function switchAssetType(assetType) {
    currentAssetType = assetType;
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    
    const portfolioView = document.getElementById('portfolioDashboardView');
    const qaView = document.getElementById('qaDashboardView');
    const navActionsGroup = document.getElementById('navActionsGroup');

    if (assetType === 'QNA') {
        const btn = document.getElementById('navQna');
        if (btn) btn.classList.add('active');
        if (portfolioView) portfolioView.style.display = 'none';
        if (qaView) qaView.style.display = 'block';
        if (navActionsGroup) navActionsGroup.style.display = 'none'; // AI Q&A 모드에서는 물타기계산기 & 종목추가 버튼 숨김
        // 경제 이벤트 캘린더 자동 로딩
        loadUpcomingCalendar();
        return;
    }

    if (navActionsGroup) navActionsGroup.style.display = 'flex'; // 개별종목/ETF 포트폴리오에서는 버튼 그룹 표시 유지
    if (portfolioView) portfolioView.style.display = 'block';
    if (qaView) qaView.style.display = 'none';

    if (assetType === 'STOCK') {
        const btn = document.getElementById('navStock');
        if (btn) btn.classList.add('active');
        const title = document.getElementById('currentDashboardTitle');
        if (title) title.innerHTML = '📊 개별종목 PORTFOLIO & TODAY ACTION';
    } else {
        const btn = document.getElementById('navEtf');
        if (btn) btn.classList.add('active');
        const title = document.getElementById('currentDashboardTitle');
        if (title) title.innerHTML = '🧺 ETF PORTFOLIO & TODAY ACTION';
    }

    // SWR (Stale-While-Revalidate): 이전에 받아둔 캐시 데이터가 있으면 0ms 즉시 화면 출력
    if (portfolioRenderCache[assetType]) {
        renderPortfolioUI(portfolioRenderCache[assetType]);
        fetchPortfolioData(true); // 비동기 백그라운드 최신화
    } else {
        fetchPortfolioData(false);
    }
}

// AI Q&A Stock / ETF Identification Engine Handlers
let currentQaTarget = { name: "삼성전자", code: "005930", market: "KOSPI", asset_type: "STOCK", manager: "", is_identified: true };
let qaSearchDebounceTimer = null;

function setQaContext(name, code, market = "KOSPI", assetType = "STOCK", manager = "") {
    currentQaTarget = { name, code, market, asset_type: assetType, manager, is_identified: true };
    
    const badge = document.getElementById('qaTargetBadge');
    if (badge) {
        if (code === 'MARKET') {
            badge.innerHTML = `🌐 <strong>[MACRO] ${name}</strong>`;
            badge.style.borderColor = "#fbbf24";
            badge.style.color = "#f59e0b";
        } else if (assetType === 'ETF') {
            badge.innerHTML = `🧺 <strong>[ETF] ${name}</strong> (${code}) | 운용사: ${manager || '기타'}`;
            badge.style.borderColor = "#a855f7";
            badge.style.color = "#c084fc";
        } else {
            badge.innerHTML = `📈 <strong>[${market}] ${name}</strong> (${code})`;
            badge.style.borderColor = "#38bdf8";
            badge.style.color = "#38bdf8";
        }
    }
    const title = document.getElementById('ansTargetTitle');
    if (title) {
        if (code === 'MARKET') {
            title.innerText = `[MACRO] 주요 시황 및 글로벌 동향 분석`;
        } else {
            title.innerText = `${name} (${code}) 수급 & 주가 동향 분석`;
        }
    }
    
    // 숨기기
    const listEl = document.getElementById('qaCandidateList');
    if (listEl) listEl.style.display = 'none';
}

function handleQaSearch(val) {
    if (qaSearchDebounceTimer) clearTimeout(qaSearchDebounceTimer);
    
    const listEl = document.getElementById('qaCandidateList');
    if (!val || !val.trim()) {
        if (listEl) listEl.style.display = 'none';
        return;
    }

    // 검색어 변경 시 식별 미확정 상태로 전환 (Guardrail)
    currentQaTarget.is_identified = false;
    const badge = document.getElementById('qaTargetBadge');
    if (badge) {
        badge.innerHTML = `⏳ 검색 선택 중...`;
        badge.style.borderColor = "#f59e0b";
        badge.style.color = "#f59e0b";
    }

    qaSearchDebounceTimer = setTimeout(async () => {
        try {
            const resp = await fetch(`/api/qna/search-target?query=${encodeURIComponent(val.trim())}`);
            if (!resp.ok) return;
            const data = await resp.json();
            renderCandidateList(data.candidates || []);
        } catch (e) {
            console.error("QnA search error:", e);
        }
    }, 200);
}

function renderCandidateList(candidates) {
    const listEl = document.getElementById('qaCandidateList');
    if (!listEl) return;

    if (!candidates || candidates.length === 0) {
        listEl.innerHTML = `<div style="padding: 12px; font-size: 12px; color: #94a3b8; text-align: center;">일치하는 종목/ETF 결과가 없습니다.</div>`;
        listEl.style.display = 'block';
        return;
    }

    let html = '';
    candidates.forEach(c => {
        const isEtf = c.asset_type === 'ETF';
        const badgeClass = isEtf ? 'candidate-badge-etf' : 'candidate-badge-stock';
        const typeLabel = isEtf ? `ETF (${c.manager || '운용사'})` : c.market;
        
        // Escape quotes
        const safeName = c.name.replace(/'/g, "\\'");
        const safeManager = (c.manager || '').replace(/'/g, "\\'");
        
        html += `
            <div class="candidate-item" onclick="setQaContext('${safeName}', '${c.ticker}', '${c.market}', '${c.asset_type}', '${safeManager}')">
                <div class="candidate-name">${c.name} <span style="font-weight: normal; color: #94a3b8;">(${c.ticker})</span></div>
                <div class="candidate-meta">
                    <span class="${badgeClass}">${typeLabel}</span>
                </div>
            </div>
        `;
    });

    listEl.innerHTML = html;
    listEl.style.display = 'block';
}

function selectQuickPrompt(promptText) {
    const txtArea = document.getElementById('qaQuestionText');
    if (txtArea) {
        txtArea.value = promptText;
        txtArea.focus();
    }
}

async function submitQaQuestion() {
    // 🛡️ CRITICAL GUARDRAIL: 확실하게 종목이 식별되지 않으면 질문 전송 차단
    if (!currentQaTarget || !currentQaTarget.is_identified) {
        alert('⚠️ 질문 대상 종목/ETF가 명확히 확정 선택되지 않았습니다!\n\n검색어 입력 후 하단 후보 목록에서 정확한 종목/ETF를 클릭하여 선택해주세요.');
        const inputEl = document.getElementById('qaTickerInput');
        if (inputEl) inputEl.focus();
        return;
    }

    const txtArea = document.getElementById('qaQuestionText');
    const question = txtArea ? txtArea.value.trim() : '';
    if (!question) {
        alert('질문을 입력해주거나 추천 질문을 선택해주세요.');
        return;
    }
    
    // 식별 완료된 정보로 답변 헤더 갱신
    let detailLabel = "";
    if (currentQaTarget.code === 'MARKET') {
        detailLabel = `[MACRO] 전체 시황 및 글로벌 동향`;
    } else {
        detailLabel = currentQaTarget.asset_type === 'ETF' ? `[ETF] ${currentQaTarget.name} (${currentQaTarget.code}) | 운용사: ${currentQaTarget.manager}` : `[${currentQaTarget.market}] ${currentQaTarget.name} (${currentQaTarget.code})`;
    }

    document.getElementById('ansTargetTitle').innerText = `${detailLabel} Q&A 근거 기반 종합 리포트`;
    document.getElementById('ansText').innerText = `'${question}' 질문에 대한 근거 수집 및 분석을 진행 중입니다...`;
    
    // STEP 3 뉴스, STEP 4 공식자료, STEP 6 종합 답변 병렬 처리
    await Promise.all([
        fetchAndRenderQaNews(currentQaTarget.code, currentQaTarget.name, question),
        fetchAndRenderOfficialDocs(currentQaTarget.code, currentQaTarget.name, question, currentQaTarget.asset_type, currentQaTarget.manager || ''),
        fetchAndRenderGroundedAnswer(currentQaTarget.code, currentQaTarget.name, question, currentQaTarget.asset_type, currentQaTarget.manager || '')
    ]);
}

async function fetchAndRenderQaNews(ticker, name, query) {
    const container = document.getElementById('qaNewsContainer');
    if (!container) return;

    container.innerHTML = `<div class="loading-box" style="padding: 12px; font-size: 13px;">🔎 '${name}' 최신 뉴스를 실시간 검색 및 분류 중입니다...</div>`;

    try {
        const resp = await fetch(`/api/qna/news?ticker=${encodeURIComponent(ticker)}&name=${encodeURIComponent(name)}&query=${encodeURIComponent(query)}`);
        if (!resp.ok) throw new Error("뉴스 API 응답 실패");
        const data = await resp.json();

        // 🛡️ 실패 예외 처리 Guardrail: 수급 실패 시 임의 내용 주작 금지
        if (data.status !== "success" || !data.items || data.items.length === 0) {
            container.innerHTML = `<div style="padding: 16px; font-size: 13px; color: #ef4444; text-align: center; background: rgba(239, 68, 68, 0.1); border-radius: 8px;">⚠️ 뉴스 검색에 실패했습니다. (최신 관련 뉴스 데이터가 없거나 수집 지연)</div>`;
            return;
        }

        renderQaNewsItems(data.items);
    } catch (e) {
        console.error("News fetch error:", e);
        container.innerHTML = `<div style="padding: 16px; font-size: 13px; color: #ef4444; text-align: center; background: rgba(239, 68, 68, 0.1); border-radius: 8px;">⚠️ 뉴스 검색에 실패했습니다.</div>`;
    }
}

function renderQaNewsItems(items) {
    const container = document.getElementById('qaNewsContainer');
    if (!container) return;

    let html = '';
    items.forEach(item => {
        const impIcon = item.importance === '매우 중요' ? '🔥 매우 중요' : (item.importance === '중요' ? '⭐ 중요' : '📌 일반');
        const dupeBadge = item.duplicate_count > 1 ? `<span class="news-duplicate-tag">📰 외 ${item.duplicate_count - 1}개 매체 중복 보도</span>` : '';
        
        html += `
            <div class="news-card-item">
                <div class="news-card-header">
                    <div class="news-tags-group">
                        <span class="news-cat-badge cat-${item.category}">${item.category}</span>
                        ${dupeBadge}
                    </div>
                    <span class="news-imp-badge">${impIcon}</span>
                </div>
                <div class="news-card-title">
                    <a href="${item.url}" target="_blank" rel="noopener noreferrer">${item.title}</a>
                </div>
                <div class="news-card-summary">${item.summary || '상세 내용 없음'}</div>
                <div class="news-card-footer">
                    <span>출처: ${item.source}</span>
                    <span>발행일: ${item.pub_date}</span>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

// ─────────────────────────────────────────────────────────────
// STEP 4 — 공식자료 API 호출 및 렌더링
// ─────────────────────────────────────────────────────────────

async function fetchAndRenderOfficialDocs(ticker, name, query, assetType = 'STOCK', manager = '') {
    const container = document.getElementById('qaOfficialContainer');
    if (!container) return;

    container.innerHTML = `<div class="loading-box" style="padding: 12px; font-size: 13px;">📋 '${name}' 공식자료 검색 중... (DART · 정부기관 · ETF 운용사)</div>`;

    try {
        const params = new URLSearchParams({
            ticker: ticker,
            name: name,
            query: query,
            asset_type: assetType,
            manager: manager
        });
        const resp = await fetch(`/api/qna/official?${params.toString()}`);
        if (!resp.ok) throw new Error("공식자료 API 응답 실패");
        const data = await resp.json();

        // 🛡️ 실패 예외 처리 Guardrail
        if (data.status !== "success" || !data.items || data.items.length === 0) {
            container.innerHTML = `<div style="padding: 16px; font-size: 13px; color: #f59e0b; text-align: center; background: rgba(245, 158, 11, 0.08); border-radius: 8px;">⚠️ 공식자료 검색에 실패했습니다. (DART 또는 정부기관 자료를 직접 확인해주세요)</div>`;
            return;
        }

        renderOfficialDocItems(data.items, data.intent);
    } catch (e) {
        console.error("Official docs fetch error:", e);
        container.innerHTML = `<div style="padding: 16px; font-size: 13px; color: #f59e0b; text-align: center; background: rgba(245, 158, 11, 0.08); border-radius: 8px;">⚠️ 공식자료 검색에 실패했습니다.</div>`;
    }
}

function renderOfficialDocItems(items, intent) {
    const container = document.getElementById('qaOfficialContainer');
    if (!container) return;

    // 출처 타입별 아이콘/라벨 매핑
    const sourceConfig = {
        'DART':   { icon: '🏛️', label: 'DART', cssClass: 'type-DART' },
        '정부기관': { icon: '🏢', label: '정부',  cssClass: 'type-gov' },
        'ETF운용사':{ icon: '📦', label: 'ETF',   cssClass: 'type-etf' },
    };

    let html = '';
    items.forEach(item => {
        const src = sourceConfig[item.source_type] || { icon: '📄', label: 'DOC', cssClass: 'type-DART' };
        
        html += `
            <div class="official-card-item">
                <div class="official-source-badge ${src.cssClass}">
                    <span class="official-source-icon">${src.icon}</span>
                    <span class="official-source-label">${src.label}</span>
                </div>
                <div class="official-card-body">
                    <div class="official-card-meta">
                        <span class="official-doc-type-badge">${item.doc_type || '공시'}</span>
                        <span class="official-institution">${item.institution}</span>
                        <span class="official-pub-date">📅 ${item.pub_date}</span>
                    </div>
                    <div class="official-card-title">
                        <a href="${item.url}" target="_blank" rel="noopener noreferrer">${item.title}</a>
                    </div>
                    <div class="official-card-summary">${item.summary || ''}</div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

// ─────────────────────────────────────────────────────────────
// STEP 5 — 출처 및 인용 시스템 (Citations System) Handlers
// ─────────────────────────────────────────────────────────────

async function fetchAndRenderCitations(ticker, name, query, assetType = 'STOCK', manager = '') {
    const container = document.getElementById('qaCitationContainer');
    if (!container) return;

    container.innerHTML = `<div class="loading-box" style="padding: 12px; font-size: 13px;">📌 '${name}' 근거자료 및 출처 인용 목록을 생성 중입니다...</div>`;

    try {
        const params = new URLSearchParams({
            ticker: ticker,
            name: name,
            query: query,
            asset_type: assetType,
            manager: manager
        });
        const resp = await fetch(`/api/qna/citations?${params.toString()}`);
        if (!resp.ok) throw new Error("Citation API 응답 실패");
        const data = await resp.json();

        if (data.status !== "success" || !data.citations || data.citations.length === 0) {
            container.innerHTML = `<div style="padding: 14px; font-size: 13px; color: #94a3b8; text-align: center; background: rgba(148, 163, 184, 0.08); border-radius: 8px;">📌 검증 가능한 출처 자료가 없습니다. (수집된 원문 검색 결과 미존재)</div>`;
            return;
        }

        renderCitationItems(data.citations);
        attachInlineCitationsToAnswer(data.citations);
    } catch (e) {
        console.error("Citations fetch error:", e);
        container.innerHTML = `<div style="padding: 14px; font-size: 13px; color: #f59e0b; text-align: center; background: rgba(245, 158, 11, 0.08); border-radius: 8px;">⚠️ 출처 인용 목록 생성 중 오류가 발생했습니다.</div>`;
    }
}

function renderCitationItems(citations) {
    const container = document.getElementById('qaCitationContainer');
    if (!container) return;

    const relConfig = {
        '매우 높음': { css: 'very-high', label: '🛡️ 매우 높음 (공식/공시)' },
        '높음':     { css: 'high',      label: '⭐ 높음 (주요 언론)' },
        '중간':     { css: 'medium',    label: '📌 중간 (일반 언론)' },
        '참고':     { css: 'reference', label: '💡 참고 (커뮤니티/기타)' }
    };

    let html = '';
    citations.forEach((cit, idx) => {
        const num = idx + 1;
        const rel = relConfig[cit.reliability] || { css: 'medium', label: cit.reliability };
        
        // 주요 기관 및 플랫폼일 경우 메인 홈페이지 바로가기 URL 매핑
        let mainHomeUrl = '';
        if (cit.publisher.includes('금융위원회')) mainHomeUrl = 'https://www.fsc.go.kr';
        else if (cit.publisher.includes('금융감독원')) mainHomeUrl = 'https://www.fss.or.kr';
        else if (cit.publisher.includes('한국은행')) mainHomeUrl = 'https://www.bok.or.kr';
        else if (cit.publisher.includes('saveticker') || cit.publisher.includes('SAVE')) mainHomeUrl = 'https://saveticker.com';
        else if (cit.publisher.includes('SEIBro') || cit.publisher.includes('세이브로')) mainHomeUrl = 'https://seibro.or.kr';
        else if (cit.publisher.includes('Investing') || cit.publisher.includes('인베스팅')) mainHomeUrl = 'https://kr.investing.com';
        else if (cit.publisher.includes('연합뉴스')) mainHomeUrl = 'https://www.yna.co.kr';

        html += `
            <div class="citation-card-item" id="cit-item-${num}">
                <div class="cit-num-badge">[${num}]</div>
                <div class="cit-content-body">
                    <div class="cit-meta-row">
                        <span class="cit-type-badge cit-type-${cit.source_type}">${cit.source_type}</span>
                        <span class="cit-publisher">${cit.publisher}</span>
                        <span class="rel-badge ${rel.css}">${rel.label}</span>
                        <span class="cit-pub-date">📅 ${cit.published_at}</span>
                    </div>
                    <div class="cit-title-row" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
                        <a href="${cit.url}" target="_blank" rel="noopener noreferrer" class="cit-title-link">
                            ${cit.title} 🔗
                        </a>
                        ${mainHomeUrl ? `<a href="${mainHomeUrl}" target="_blank" rel="noopener noreferrer" style="font-size:12px; font-weight:600; color:#34d399; background:rgba(16,185,129,0.15); padding:3px 8px; border-radius:4px; text-decoration:none; white-space:nowrap; border:1px solid #10b981;">🏛️ 메인 홈페이지 (로그인) 🔗</a>` : ''}
                    </div>
                    ${cit.summary ? `<div class="cit-summary-text">${cit.summary}</div>` : ''}
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function attachInlineCitationsToAnswer(citations) {
    const ansTextEl = document.getElementById('ansText');
    if (!ansTextEl || citations.length === 0) return;

    let inlineBadges = '';
    const maxInline = Math.min(citations.length, 3);
    for (let i = 1; i <= maxInline; i++) {
        inlineBadges += `<a class="cite-badge" href="#cit-item-${i}" title="${citations[i-1].publisher}: ${citations[i-1].title}">[${i}]</a>`;
    }

    const baseText = ansTextEl.innerText;
    // 중복 부착 방지
    if (!baseText.includes('[1]')) {
        ansTextEl.innerHTML = `${baseText} ${inlineBadges}`;
    }
}

// ─────────────────────────────────────────────────────────────
// STEP 6 — 근거 기반 금융 Q&A LLM 파이프라인 핸들러
// ─────────────────────────────────────────────────────────────

async function fetchAndRenderGroundedAnswer(ticker, name, query, assetType = 'STOCK', manager = '') {
    const ansTextEl = document.getElementById('ansText');
    const ansFactsEl = document.getElementById('ansFacts');
    const ansAnalysisEl = document.getElementById('ansAnalysis');
    const ansCautionEl = document.getElementById('ansCaution');
    const ansOpinionEl = document.getElementById('ansActionOpinion');
    const ansConfEl = document.getElementById('ansConfidence');
    const crossValBadgeEl = document.getElementById('crossValStatusBadge');
    const appDataRowEl = document.getElementById('appDataRow');

    try {
        const params = new URLSearchParams({
            ticker: ticker,
            name: name,
            query: query,
            asset_type: assetType,
            manager: manager
        });
        const resp = await fetch(`/api/qna/answer?${params.toString()}`);
        if (!resp.ok) throw new Error("Q&A 종합 답변 API 호출 실패");
        const data = await resp.json();

        // 0. STEP 8 앱 보유 포트폴리오 데이터 배지
        if (appDataRowEl && data.app_user_data) {
            const ud = data.app_user_data;
            if (ud.has_user_stock) {
                const retClass = ud.return_rate >= 0 ? "profit" : "loss";
                const sign = ud.return_rate >= 0 ? "+" : "";
                appDataRowEl.innerHTML = `
                    <span class="app-data-item owned">📱 보유 종목 (${ud.quantity.toLocaleString()}주)</span>
                    <span class="app-data-item">평단가: ${ud.avg_price.toLocaleString()}원</span>
                    <span class="app-data-item ${retClass}">수익률: ${sign}${ud.return_rate.toFixed(2)}% (${sign}${ud.profit_loss.toLocaleString()}원)</span>
                `;
            } else {
                appDataRowEl.innerHTML = `
                    <span class="app-data-item unowned">📱 [앱 데이터] ${ud.message || "현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다."}</span>
                `;
            }
        }

        // 1. 3단계 신뢰도 배지 (높음, 중간, 낮음)
        if (ansConfEl) {
            const grade = data.reliability_grade || "중간";
            ansConfEl.innerText = grade;
            if (grade === "높음") ansConfEl.className = "conf-badge high";
            else if (grade === "중간") ansConfEl.className = "conf-badge medium";
            else ansConfEl.className = "conf-badge low";
        }

        // 2. STEP 7 교차검증 상태 배지
        if (crossValBadgeEl && data.cross_validation) {
            const cv = data.cross_validation;
            if (cv.conflict_detected) {
                crossValBadgeEl.className = "cross-val-status-badge status-conflict";
                crossValBadgeEl.innerHTML = "⚠️ 자료 간 내용에 차이가 있습니다.";
            } else if (cv.is_insufficient) {
                crossValBadgeEl.className = "cross-val-status-badge status-insufficient";
                crossValBadgeEl.innerHTML = "⚠️ 확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.";
            } else {
                crossValBadgeEl.className = "cross-val-status-badge status-success";
                crossValBadgeEl.innerHTML = `🛡️ 독립 출처 교차 검증 완료 (일치)`;
            }
        }

        // 3. 보조 의견 배지
        if (ansOpinionEl) {
            ansOpinionEl.innerText = data.action_opinion || "관망";
        }

        // 2. 핵심 답변 (Executive Summary)
        if (ansTextEl) {
            ansTextEl.innerText = data.executive_summary || "현재 확인 가능한 신뢰할 수 있는 자료만으로는 판단하기 어렵습니다.";
        }

        // 3. 확인된 사실 (Verified Facts) - AI의 해석과 절대로 섞지 않음
        if (ansFactsEl) {
            if (data.verified_facts && data.verified_facts.length > 0) {
                let factsHtml = '';
                data.verified_facts.forEach(f => {
                    factsHtml += `<li>${f}</li>`;
                });
                ansFactsEl.innerHTML = factsHtml;
            } else {
                ansFactsEl.innerHTML = `<li>확인된 원문 Facts 데이터가 없습니다.</li>`;
            }
        }

        // 4. AI 분석 (AI Quantitative Analysis)
        if (ansAnalysisEl) {
            if (data.ai_analysis) {
                const formattedAnalysis = data.ai_analysis.split('\n').map(p => `<p>${p}</p>`).join('');
                ansAnalysisEl.innerHTML = formattedAnalysis;
            } else {
                ansAnalysisEl.innerHTML = `<p>데이터 부족으로 기술적/수급 분석을 생략합니다.</p>`;
            }
        }

        // 5. 불확실한 부분 및 리스크 (Uncertainties & Risk)
        if (ansCautionEl) {
            ansCautionEl.innerText = data.uncertainties || "확인 가능한 자료가 부족하여 불확실성이 존재합니다.";
        }

        // Citation 인용 연동
        if (data.citations && data.citations.length > 0) {
            renderCitationItems(data.citations);
            attachInlineCitationsToAnswer(data.citations);
        }
    } catch (e) {
        console.error("Grounded Answer Fetch Error:", e);
        if (ansTextEl) ansTextEl.innerText = "현재 확인 가능한 신뢰할 수 있는 자료만으로는 판단하기 어렵습니다.";
    }
}

const portfolioRenderCache = {};

// 3. 포트폴리오 데이터 전체 조회 및 렌더링
async function fetchPortfolioData(isBackground = false) {
    const grid = document.getElementById('stockGrid');
    try {
        const resp = await fetch(`/api/portfolio?asset_type=${currentAssetType}`);
        if (!resp.ok) throw new Error("포트폴리오 조회가 실패했습니다.");
        const resData = await resp.json();
        
        if (resData.status !== "success") {
            if (!isBackground) {
                grid.innerHTML = `<div class="loading-box">포트폴리오 데이터를 불러올 수 없습니다.</div>`;
            }
            return;
        }

        const data = resData.data;
        portfolioRenderCache[currentAssetType] = data; // 캐시 보관
        renderPortfolioUI(data);

    } catch (e) {
        console.error(e);
        if (!isBackground && !portfolioRenderCache[currentAssetType]) {
            grid.innerHTML = `<div class="loading-box text-danger">서버 통신 중 오류가 발생했습니다: ${e.message}</div>`;
        }
    }
}

// 포트폴리오 UI 전체 렌더링 함수
function renderPortfolioUI(data) {
    const grid = document.getElementById('stockGrid');
    if (!data) return;

    currentPortfolioData = data;

    // 헤더 요약 정보 업데이트
    const summary = data.summary || {};
    const investedElem = document.getElementById('totalInvested');
    if (investedElem) investedElem.innerText = `${summary.total_invested ? summary.total_invested.toLocaleString() : 0} 원`;
    
    const evalElem = document.getElementById('totalEval');
    if (evalElem) evalElem.innerText = `${summary.total_eval ? summary.total_eval.toLocaleString() : 0} 원`;
    
    const pl = summary.total_profit_loss || 0;
    const plElem = document.getElementById('totalProfitLoss');
    if (plElem) {
        plElem.innerText = `${pl >= 0 ? '+' : ''}${pl.toLocaleString()} 원`;
        plElem.className = `card-val ${pl > 0 ? 'text-success' : (pl < 0 ? 'text-danger' : '')}`;
    }

    const ret = summary.total_return_rate || 0;
    const retElem = document.getElementById('totalReturnRate');
    if (retElem) {
        retElem.innerText = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)} %`;
        retElem.className = `card-val ${ret > 0 ? 'text-success' : (ret < 0 ? 'text-danger' : '')}`;
    }

    const todayPl = summary.today_profit_loss || 0;
    const todayElem = document.getElementById('todayProfitLoss');
    if (todayElem) {
        todayElem.innerText = `${todayPl >= 0 ? '+' : ''}${todayPl.toLocaleString()} 원`;
        todayElem.className = `card-val ${todayPl > 0 ? 'text-success' : (todayPl < 0 ? 'text-danger' : '')}`;
    }

    // 위험 분석 및 업종 태그
    const analysis = data.analysis || {};
    const risk = analysis.risk_concentration || {};
    const riskBadge = document.getElementById('riskLevelBadge');
    if (riskBadge) {
        riskBadge.innerText = risk.level || 'LOW';
        riskBadge.className = `risk-badge ${risk.level || 'LOW'}`;
    }
    const riskDescElem = document.getElementById('riskDesc');
    if (riskDescElem) riskDescElem.innerText = risk.description || '포트폴리오 비중이 분산되어 있습니다.';

    const sectorBox = document.getElementById('sectorInfo');
    if (sectorBox) {
        sectorBox.innerHTML = '';
        const sectorWeights = analysis.sector_weights || {};
        for (const [sec, w] of Object.entries(sectorWeights)) {
            sectorBox.innerHTML += `<span class="sector-tag">${sec}: ${w}%</span>`;
        }
    }

    const lastUpdateElem = document.getElementById('lastUpdatedInfo');
    if (lastUpdateElem) lastUpdateElem.innerText = `최신 업데이트: ${new Date().toLocaleTimeString('ko-KR')}`;

    // 포트폴리오 비어있음 처리
    if (data.portfolio_empty || !data.items || data.items.length === 0) {
        if (grid) {
            grid.innerHTML = `
                <div class="loading-box">
                    등록된 종목이 없습니다. 우측 상단의 '+ 종목 추가' 버튼을 눌러 첫 보유 종목을 등록해보세요!
                </div>`;
        }
        return;
    }

    // 종목 카드 그리드 렌더링
    renderStockCards(data.items);
    updateSimSelectOptions(data.items);
}


// 4. 종목 카드 그리드 생성 (우측 상단 4가지 가격 항목: 현재가, 매입평균가, 총금액, 수익률)
function renderStockCards(items) {
    const grid = document.getElementById('stockGrid');
    
    // 만약 이미 종목 수가 같다면 DOM을 매번 전부 날리지 않고 부분 갱신하여 깜빡임 방지
    const existingCards = grid.querySelectorAll('.stock-card');
    const fullReRender = existingCards.length !== items.length;

    if (fullReRender) {
        grid.innerHTML = '';
    }

    items.forEach(item => {
        const pl = item.profit_loss || 0;
        const ret = item.return_rate || 0;
        const plClass = pl > 0 ? 'text-success' : (pl < 0 ? 'text-danger' : '');
        const prevPrice = previousStockPrices[item.ticker];
        const curPrice = item.current_price;
        const evalAmount = item.eval_amount || (curPrice * item.quantity);

        let flashClass = '';
        if (prevPrice !== undefined && prevPrice !== curPrice) {
            flashClass = curPrice > prevPrice ? 'price-up-flash' : 'price-down-flash';
        }
        previousStockPrices[item.ticker] = curPrice;

        const decisionMap = {
            'BUY': { label: '매수', class: 'BUY' },
            'AVERAGE': { label: '분할매수(물타기)', class: 'AVERAGE' },
            'HOLD': { label: '보유 (관망)', class: 'HOLD' },
            'TAKE PROFIT': { label: '일부 익절', class: 'TAKE_PROFIT' },
            'REDUCE': { label: '비중 축소', class: 'REDUCE' }
        };
        const actionObj = decisionMap[item.final_decision] || { label: item.final_decision || '보유', class: 'HOLD' };

        const reasons = item.ai_reasons || ["수급 및 지지선 모니터링 필요"];
        const reasonsHtml = reasons.map(r => `<li>${r}</li>`).join('');

        if (!fullReRender) {
            const cardElem = document.getElementById(`stock-card-${item.ticker}`);
            if (cardElem) {
                const priceGrid = cardElem.querySelector('.stock-price-grid');
                const priceVal = cardElem.querySelector('.cur-price-val');
                const evalVal = cardElem.querySelector('.eval-amount-val');
                const retVal = cardElem.querySelector('.return-rate-val');

                if (priceVal) priceVal.innerText = `${curPrice.toLocaleString()}원`;
                if (evalVal) evalVal.innerText = `${evalAmount.toLocaleString()}원`;
                if (retVal) {
                    retVal.className = `pg-val return-rate-val ${plClass}`;
                    retVal.innerText = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% (${pl >= 0 ? '+' : ''}${pl.toLocaleString()}원)`;
                }

                if (flashClass && priceGrid) {
                    priceGrid.classList.remove('price-up-flash', 'price-down-flash');
                    void priceGrid.offsetWidth;
                    priceGrid.classList.add(flashClass);
                }
                return;
            }
        }

        const marketVal = item.market || (item.asset_type === 'ETF' ? 'ETF' : 'KOSPI');
        const marketClass = marketVal.toLowerCase();
        
        const cardHtml = `
            <div class="stock-card" id="stock-card-${item.ticker}">
                <!-- Header -->
                <div class="card-header">
                    <div class="stock-name-box">
                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                            <h3>${item.name}</h3>
                            <span class="market-tag ${marketClass}">${marketVal}</span>
                            <span class="sector-tag">${item.sector || '기타'}</span>
                        </div>
                        <span class="stock-code">${item.ticker} (비중 ${item.weight}%)</span>
                    </div>
                    
                    <!-- 우측 상단 4개 항목: 현재가, 매입평균가, 총금액, 수익률 (클릭 시 6개월 추세선/거래량/MFI 분석 차트 팝업) -->
                    <div class="stock-price-grid clickable-price ${flashClass}" onclick="openStockHistoryModal('${item.ticker}', '${item.name}')" title="클릭 시 최근 6개월 추세선, 거래량, MFI 분석 차트 보기">
                        <div class="price-grid-item">
                            <span class="pg-label">현재가</span>
                            <span class="pg-val cur-price-val">${curPrice.toLocaleString()}원</span>
                        </div>
                        <div class="price-grid-item">
                            <span class="pg-label">매입평균가</span>
                            <span class="pg-val">${item.avg_price.toLocaleString()}원</span>
                        </div>
                        <div class="price-grid-item">
                            <span class="pg-label">총금액</span>
                            <span class="pg-val eval-amount-val">${evalAmount.toLocaleString()}원</span>
                        </div>
                        <div class="price-grid-item">
                            <span class="pg-label">수익률</span>
                            <span class="pg-val return-rate-val ${plClass}">${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% (${pl >= 0 ? '+' : ''}${pl.toLocaleString()}원)</span>
                        </div>
                    </div>
                </div>

                <!-- TODAY ACTION -->
                <div class="today-action-box">
                    <div class="action-header">
                        <span class="action-label">⚡ TODAY ACTION</span>
                        <span class="action-badge ${actionObj.class}">${actionObj.label}</span>
                    </div>
                    <div class="action-reasons-summary">
                        <ul>${reasonsHtml}</ul>
                    </div>
                </div>

                <!-- 수급 & FFCS Info Grid -->
                <div class="flow-info-grid">
                    <div class="info-item">
                        <span class="lbl">외국인 수급 사이클</span>
                        <span class="val text-primary">[${item.cycle_stage}]</span>
                    </div>
                    <div class="info-item">
                        <span class="lbl">FFCS Score</span>
                        <span class="val ffcs-score-text">${item.ffcs_score != null ? item.ffcs_score : '-'}점</span>
                    </div>
                    <div class="info-item">
                        <span class="lbl">외국인 / 기관 방향</span>
                        <span class="val">${item.foreign_direction} / ${item.institution_direction}</span>
                    </div>
                    <div class="info-item">
                        <span class="lbl">기관 동조화</span>
                        <span class="val">${item.concurrency || 'N/A'}</span>
                    </div>
                </div>

                <!-- Buy/Sell/Watering Scores Row -->
                <div class="scores-row">
                    <div class="score-badge-item">
                        <span class="s-lbl">Buy Score</span>
                        <span class="s-val text-success">${item.buy_score}점</span>
                    </div>
                    <div class="score-badge-item">
                        <span class="s-lbl">Sell Score</span>
                        <span class="s-val text-danger">${item.sell_score}점</span>
                    </div>
                    <div class="score-badge-item">
                        <span class="s-lbl">Watering Score</span>
                        <span class="s-val text-primary">${item.watering_score}점</span>
                    </div>
                </div>

                <!-- Footer -->
                <div class="card-footer" style="display: flex; gap: 8px; justify-content: space-between; align-items: center;">
                    <button class="btn-detail" onclick="openDetailModal('${item.ticker}', '${item.name}')">📈 상세 차트 & 지표</button>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn-edit" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 6px 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" onclick="openEditStockModal(${item.id}, '${item.name}', ${item.avg_price}, ${item.quantity}, '${item.buy_date || ''}', '${item.investment_purpose || '장기투자'}', '${item.sector || '기타'}')">✏️ 수정</button>
                        <button class="btn-delete" onclick="handleDeleteStock(${item.id}, '${item.name}')">삭제</button>
                    </div>
                </div>
            </div>
        `;
        grid.innerHTML += cardHtml;
    });
}

// 4. 상세 모달 및 차트 시각화
async function openDetailModal(ticker, name) {
    const modal = document.getElementById('detailModal');
    modal.style.display = 'flex';

    document.getElementById('modalStockTitle').innerText = `${name} (${ticker}) 상세 수급 & 기술적 차트`;
    
    try {
        const resp = await fetch(`/api/decision/analyze?ticker=${ticker}`);
        if (!resp.ok) return;
        const resData = await resp.json();
        
        if (resData.status !== "success") return;
        const data = resData.data;

        const flow = data.flow_analysis || {};
        const tech = data.technical_analysis || {};
        const dec = data.decision || {};

        document.getElementById('modalStockSub').innerText = `최근 종가: ${tech.latest_close ? tech.latest_close.toLocaleString() : '-'}원 | 지지선: ${tech.support_level ? tech.support_level.toLocaleString() : '-'}원 | 저항선: ${tech.resistance_level ? tech.resistance_level.toLocaleString() : '-'}원`;

        document.getElementById('modalActionTag').innerText = dec.decision || 'HOLD';
        document.getElementById('modalFfcs').innerText = flow.ffcs_score || 0;
        document.getElementById('modalBuyScore').innerText = dec.buy_score || 0;
        document.getElementById('modalSellScore').innerText = dec.sell_score || 0;
        document.getElementById('modalWaterScore').innerText = dec.watering_score || 0;

        const reasonList = document.getElementById('modalReasonList');
        reasonList.innerHTML = '';
        (dec.ai_reasons || []).forEach(r => {
            reasonList.innerHTML += `<li>${r}</li>`;
        });

        renderDetailChart(flow, tech);

    } catch (e) {
        console.error(e);
    }
}

function renderDetailChart(flow, tech) {
    const ctx = document.getElementById('stockDetailChart').getContext('2d');
    
    if (detailChartInstance) {
        detailChartInstance.destroy();
    }

    const periods = ["1d", "3d", "5d", "10d", "20d"];
    const pData = flow.periods_analysis || {};
    const foreignFlows = periods.map(p => (pData.foreign && pData.foreign[p]) ? pData.foreign[p].net_buy / 100000000 : 0);
    const instFlows = periods.map(p => (pData.institution && pData.institution[p]) ? pData.institution[p].net_buy / 100000000 : 0);

    detailChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ["1일 추세", "3일 추세", "5일 추세", "10일 추세", "20일 누적"],
            datasets: [
                {
                    label: '외국인 순매수 (억원)',
                    data: foreignFlows,
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    borderColor: '#3b82f6',
                    borderWidth: 1
                },
                {
                    label: '기관 순매수 (억원)',
                    data: instFlows,
                    backgroundColor: 'rgba(139, 92, 246, 0.7)',
                    borderColor: '#8b5cf6',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } },
                title: { display: true, text: '기간별 외국인/기관 순매수 수급 동향 (억원)', color: '#f8fafc' }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

function closeDetailModal() {
    document.getElementById('detailModal').style.display = 'none';
}

let stockSearchDebounceTimer = null;

// 5. 종목 추가
function openAddStockModal() {
    hideTickerSuggestions();
    
    // 현재 포트폴리오 탭이 ETF인 경우 종목추가 모달의 자산 분류를 자동으로 ETF로 세팅
    if (typeof currentAssetType !== 'undefined' && currentAssetType === 'ETF') {
        const etfRadio = document.querySelector('input[name="addAssetType"][value="ETF"]');
        if (etfRadio) etfRadio.checked = true;
        const marketEl = document.getElementById('addMarketInput');
        if (marketEl) marketEl.value = 'ETF';
        const sectorEl = document.getElementById('addSectorInput');
        if (sectorEl) sectorEl.value = '기타';
    } else {
        const stockRadio = document.querySelector('input[name="addAssetType"][value="STOCK"]');
        if (stockRadio) stockRadio.checked = true;
        const marketEl = document.getElementById('addMarketInput');
        if (marketEl && marketEl.value === 'ETF') marketEl.value = 'KOSPI';
    }

    document.getElementById('addStockModal').style.display = 'flex';
}

function closeAddStockModal() {
    hideTickerSuggestions();
    document.getElementById('addStockModal').style.display = 'none';
}

function initAddStockFormEvents() {
    // 1. 자산 분류 (STOCK / ETF) 라디오 버튼 체인지 이벤트
    const radioBtns = document.querySelectorAll('input[name="addAssetType"]');
    radioBtns.forEach(radio => {
        radio.addEventListener('change', (e) => {
            const assetType = e.target.value;
            const marketEl = document.getElementById('addMarketInput');
            const sectorEl = document.getElementById('addSectorInput');
            
            if (assetType === 'ETF') {
                if (marketEl) marketEl.value = 'ETF';
                if (sectorEl) sectorEl.value = '기타';
            } else {
                if (marketEl && marketEl.value === 'ETF') marketEl.value = 'KOSPI';
            }
            
            const inputVal = document.getElementById('addTickerInput')?.value;
            if (inputVal && inputVal.trim()) {
                fetchTickerSuggestions(inputVal.trim());
            }
        });
    });

    // 2. 종목명/종목코드 실시간 입력 자동완성 이벤트
    const tickerInput = document.getElementById('addTickerInput');
    if (tickerInput) {
        tickerInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (stockSearchDebounceTimer) clearTimeout(stockSearchDebounceTimer);
            
            if (!query) {
                hideTickerSuggestions();
                return;
            }

            stockSearchDebounceTimer = setTimeout(() => {
                fetchTickerSuggestions(query);
            }, 200);
        });

        tickerInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hideTickerSuggestions();
            }
        });
    }

    // 3. 외부 클릭 시 연관 종목 드롭다운 닫기
    document.addEventListener('click', (e) => {
        const suggestionsBox = document.getElementById('addTickerSuggestions');
        const tickerInput = document.getElementById('addTickerInput');
        if (suggestionsBox && tickerInput) {
            if (!suggestionsBox.contains(e.target) && e.target !== tickerInput) {
                hideTickerSuggestions();
            }
        }
    });
}

const tickerSuggestionsCache = {};

// 실시간 연관 종목/ETF 검색 호출 (프론트엔드 캐싱 탑재)
async function fetchTickerSuggestions(query) {
    const suggestionsBox = document.getElementById('addTickerSuggestions');
    if (!suggestionsBox) return;

    const assetTypeRadio = document.querySelector('input[name="addAssetType"]:checked');
    const assetType = assetTypeRadio ? assetTypeRadio.value : 'ALL';
    const cacheKey = `${query.toLowerCase()}_${assetType}`;

    if (tickerSuggestionsCache[cacheKey]) {
        renderTickerSuggestions(tickerSuggestionsCache[cacheKey]);
        return;
    }

    try {
        const resp = await fetch(`/api/stock/search?query=${encodeURIComponent(query)}&asset_type=${assetType}`);
        if (!resp.ok) return;
        
        const data = await resp.json();
        const candidates = data.candidates || [];
        tickerSuggestionsCache[cacheKey] = candidates;
        renderTickerSuggestions(candidates);
    } catch (e) {
        console.error('Failed to fetch ticker suggestions:', e);
    }
}

function renderTickerSuggestions(candidates) {
    const suggestionsBox = document.getElementById('addTickerSuggestions');
    if (!suggestionsBox) return;

    if (candidates.length === 0) {
        suggestionsBox.innerHTML = `<div style="padding: 12px; font-size: 12px; color: #94a3b8; text-align: center;">일치하는 연관 종목/ETF가 없습니다.</div>`;
        suggestionsBox.style.display = 'block';
        return;
    }

    let html = '';
    candidates.forEach(c => {
        const isEtf = c.asset_type === 'ETF';
        const badgeClass = isEtf ? 'suggestion-badge etf' : 'suggestion-badge stock';
        const badgeLabel = isEtf ? `🧺 ETF (${c.manager || '운용사'})` : `📈 ${c.market || 'KOSPI'}`;
        const subLabel = isEtf ? `코드: ${c.ticker} | 운용사: ${c.manager || 'ETF'}` : `코드: ${c.ticker} | 시장: ${c.market}`;

        html += `
            <div class="suggestion-item" onclick="selectTickerSuggestion('${c.name}', '${c.ticker}', '${c.asset_type}', '${c.market}')">
                <div class="suggestion-info">
                    <span class="suggestion-name">${c.name} (${c.ticker})</span>
                    <span class="suggestion-sub">${subLabel}</span>
                </div>
                <span class="${badgeClass}">${badgeLabel}</span>
            </div>
        `;
    });

    suggestionsBox.innerHTML = html;
    suggestionsBox.style.display = 'block';
}

// 연관 종목 드롭다운 항목 클릭 처리
function selectTickerSuggestion(name, ticker, assetType, market) {
    const tickerInput = document.getElementById('addTickerInput');
    if (tickerInput) {
        tickerInput.value = `${name}(${ticker})`;
    }

    // 자산 분류 라디오 버튼 자동 동기화
    const targetType = assetType === 'ETF' ? 'ETF' : 'STOCK';
    const radioBtn = document.querySelector(`input[name="addAssetType"][value="${targetType}"]`);
    if (radioBtn) {
        radioBtn.checked = true;
    }

    // 시장 구분 자동 동기화
    const marketEl = document.getElementById('addMarketInput');
    if (marketEl) {
        if (targetType === 'ETF') {
            marketEl.value = 'ETF';
        } else if (market && (market === 'KOSPI' || market === 'KOSDAQ')) {
            marketEl.value = market;
        }
    }

    hideTickerSuggestions();
}

function hideTickerSuggestions() {
    const suggestionsBox = document.getElementById('addTickerSuggestions');
    if (suggestionsBox) {
        suggestionsBox.style.display = 'none';
        suggestionsBox.innerHTML = '';
    }
}

async function handleAddStock(event) {
    event.preventDefault();
    hideTickerSuggestions();

    const submitBtn = event.target.querySelector('button[type="submit"]');
    const origBtnText = submitBtn ? submitBtn.innerText : '포트폴리오에 저장';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = '💾 저장 중...';
    }

    const assetTypeRadio = document.querySelector('input[name="addAssetType"]:checked');
    const assetType = assetTypeRadio ? assetTypeRadio.value : 'STOCK';
    
    const marketEl = document.getElementById('addMarketInput');
    const market = marketEl ? marketEl.value : (assetType === 'ETF' ? 'ETF' : 'KOSPI');

    const query = document.getElementById('addTickerInput').value;
    const price = parseFloat(document.getElementById('addPriceInput').value);
    const qty = parseInt(document.getElementById('addQtyInput').value);
    const buyDate = document.getElementById('addDateInput').value;
    const purpose = document.getElementById('addPurposeInput').value;
    const sectorEl = document.getElementById('addSectorInput');
    const sector = sectorEl ? sectorEl.value : (assetType === 'ETF' ? 'ETF' : '기타');

    try {
        const resp = await fetch('/api/portfolio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ticker_or_name: query,
                avg_price: price,
                quantity: qty,
                buy_date: buyDate,
                investment_purpose: purpose,
                sector: sector,
                asset_type: assetType,
                market: market
            })
        });

        const data = await resp.json();
        if (resp.ok && data.status === "success") {
            alert(data.message);
            closeAddStockModal();
            fetchPortfolioData();
        } else {
            alert(`오류: ${data.detail || '종목 추가에 실패했습니다.'}`);
        }
    } catch (e) {
        alert(`통신 오류: ${e.message}`);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = origBtnText;
        }
    }
}



// 6. 종목 삭제
async function handleDeleteStock(itemId, name) {
    if (!confirm(`'${name}' 종목을 포트폴리오에서 삭제하시겠습니까?`)) return;

    try {
        const resp = await fetch(`/api/portfolio/${itemId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (resp.ok && data.status === "success") {
            fetchPortfolioData();
        } else {
            alert("삭제에 실패했습니다.");
        }
    } catch (e) {
        alert(`통신 오류: ${e.message}`);
    }
}

// 7. 물타기 시뮬레이션
function openSimModal() {
    document.getElementById('simModal').style.display = 'flex';
}
const openSimulateModal = openSimModal;

function closeSimModal() {
    document.getElementById('simModal').style.display = 'none';
}

function updateSimSelectOptions(items) {
    const sel = document.getElementById('simStockSelect');
    sel.innerHTML = '';
    items.forEach(item => {
        sel.innerHTML += `<option value="${item.id}">${item.name} (${item.ticker}) - 현재 평단 ${item.avg_price.toLocaleString()}원</option>`;
    });
}

function onSimStockChange() {
    document.getElementById('simResultBox').style.display = 'none';
}

async function handleSimulateAddBuy(event) {
    event.preventDefault();
    const itemId = parseInt(document.getElementById('simStockSelect').value);
    const addPrice = parseFloat(document.getElementById('simPriceInput').value);
    const addQty = parseInt(document.getElementById('simQtyInput').value);

    try {
        const resp = await fetch('/api/portfolio/simulate-add-buy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                item_id: itemId,
                add_price: addPrice,
                add_quantity: addQty
            })
        });

        const data = await resp.json();
        if (resp.ok && data.status === "success") {
            const sim = data.simulation;
            document.getElementById('simResultBox').style.display = 'flex';
            document.getElementById('simPrevRate').innerText = `+${sim.prev_break_even_rate.toFixed(2)}%`;
            document.getElementById('simNewAvg').innerText = `${sim.new_avg_price.toLocaleString()} 원 (총 ${sim.new_total_qty}주)`;
            document.getElementById('simNewRate').innerText = `+${sim.break_even_rate.toFixed(2)}%`;
            document.getElementById('simImprovement').innerText = `+${sim.break_even_improvement.toFixed(2)}%p 단축`;
        } else {
            alert(data.detail || "시뮬레이션 연산에 실패했습니다.");
        }
    } catch (e) {
        alert(`통신 오류: ${e.message}`);
    }
}

// ==========================================
// 8. 최상단 지수/환율 6개월 추이 차트 모달
// ==========================================
let indexHistoryChartInstance = null;

async function openIndexChartModal(symbol, name) {
    const modal = document.getElementById('indexChartModal');
    if (!modal) return;
    modal.style.display = 'flex';

    document.getElementById('indexModalTitle').innerText = `${name} (${symbol}) 최근 6개월 추이`;
    document.getElementById('indexModalSub').innerText = `데이터 수집 중...`;

    try {
        const resp = await fetch(`/api/market/index-history?symbol=${encodeURIComponent(symbol)}`);
        if (!resp.ok) throw new Error("지수 데이터를 가져올 수 없습니다.");
        const data = await resp.json();

        if (data.status !== "success") {
            document.getElementById('indexModalSub').innerText = data.message || "데이터 없음";
            return;
        }

        const rateStr = `${data.period_rate >= 0 ? '+' : ''}${data.period_rate}%`;
        const changeStr = `${data.period_change >= 0 ? '+' : ''}${data.period_change}`;
        document.getElementById('indexModalSub').innerText = `최저: ${data.min_val.toLocaleString()} | 최고: ${data.max_val.toLocaleString()} | 6개월 변동: ${changeStr} (${rateStr})`;

        renderIndexHistoryChart(data.dates, data.closes, name);

    } catch (e) {
        console.error(e);
        document.getElementById('indexModalSub').innerText = `오류: ${e.message}`;
    }
}

function renderIndexHistoryChart(dates, closes, name) {
    const ctx = document.getElementById('indexHistoryChart').getContext('2d');
    if (indexHistoryChartInstance) {
        indexHistoryChartInstance.destroy();
    }

    indexHistoryChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: `${name} 종가`,
                data: closes,
                borderColor: '#06b6d4',
                backgroundColor: 'rgba(6, 182, 212, 0.1)',
                borderWidth: 2,
                pointRadius: 1,
                pointHoverRadius: 5,
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

function closeIndexChartModal() {
    const modal = document.getElementById('indexChartModal');
    if (modal) modal.style.display = 'none';
}


// ==========================================
// 9. 개별 종목 6개월 가격/추세선/거래량/MFI/RMI 4단 차트 모달
// ==========================================
let currentStockHistoryTicker = null;
let currentStockHistoryName = null;
let currentStockTimeframe = 'day';

let stockPriceTrendChartInstance = null;
let stockVolumeChartInstance = null;
let stockMfiChartInstance = null;
let stockRmiChartInstance = null;

async function openStockHistoryModal(ticker, name, timeframe = 'day') {
    currentStockHistoryTicker = ticker;
    currentStockHistoryName = name;
    currentStockTimeframe = timeframe;

    const modal = document.getElementById('stockHistoryModal');
    if (!modal) return;
    modal.style.display = 'flex';

    document.getElementById('stockHistoryTitle').innerText = `${name} (${ticker}) 6개월 추세선 · 거래량 · MFI · RMI 차트`;
    
    // 탭 버튼 상태 업데이트
    ['day', 'month'].forEach(tf => {
        const btn = document.getElementById(`tfBtn${tf.charAt(0).toUpperCase() + tf.slice(1)}`);
        if (btn) {
            btn.className = `timeframe-btn ${tf === timeframe ? 'active' : ''}`;
        }
    });

    try {
        const resp = await fetch(`/api/stock/history-analysis?ticker=${ticker}&timeframe=${timeframe}`);
        if (!resp.ok) throw new Error("종목 이력 데이터를 가져올 수 없습니다.");
        const data = await resp.json();

        if (data.status !== "success") {
            alert(data.message || "차트 데이터 수집 실패");
            return;
        }

        setTimeout(() => {
            renderStockMultiCharts(data);
        }, 50);

    } catch (e) {
        console.error(e);
        alert(`차트 로딩 오류: ${e.message}`);
    }
}

function changeStockTimeframe(tf) {
    if (currentStockHistoryTicker) {
        openStockHistoryModal(currentStockHistoryTicker, currentStockHistoryName, tf);
    }
}

function renderStockMultiCharts(data) {
    const dates = data.dates || [];

    // 1. 주가 & 이동평균 추세선 차트 (MA5, MA20, MA60)
    const ctxPrice = document.getElementById('stockPriceTrendChart').getContext('2d');
    if (stockPriceTrendChartInstance) stockPriceTrendChartInstance.destroy();

    stockPriceTrendChartInstance = new Chart(ctxPrice, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: '종가 (Close)',
                    data: data.closes,
                    borderColor: '#f8fafc',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1
                },
                {
                    label: 'MA5 (5일 추세선)',
                    data: data.ma5,
                    borderColor: '#ec4899',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    borderDash: [2, 2]
                },
                {
                    label: 'MA20 (20일 추세선)',
                    data: data.ma20,
                    borderColor: '#f59e0b',
                    borderWidth: 1.5,
                    pointRadius: 0
                },
                {
                    label: 'MA60 (60일 추세선)',
                    data: data.ma60,
                    borderColor: '#3b82f6',
                    borderWidth: 1.5,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });

    // 2. 거래량 차트
    const ctxVol = document.getElementById('stockVolumeChart').getContext('2d');
    if (stockVolumeChartInstance) stockVolumeChartInstance.destroy();

    stockVolumeChartInstance = new Chart(ctxVol, {
        type: 'bar',
        data: {
            labels: dates,
            datasets: [{
                label: '거래량 (Volume)',
                data: data.volumes,
                backgroundColor: 'rgba(139, 92, 246, 0.6)',
                borderColor: '#8b5cf6',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });

    // 3. MFI (Money Flow Index) 자금흐름지수 차트
    const ctxMfi = document.getElementById('stockMfiChart').getContext('2d');
    if (stockMfiChartInstance) stockMfiChartInstance.destroy();

    const mfiOverbought = dates.map(() => 80);
    const mfiOversold = dates.map(() => 20);

    stockMfiChartInstance = new Chart(ctxMfi, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'MFI (14일 자금흐름지수)',
                    data: data.mfi,
                    borderColor: '#06b6d4',
                    backgroundColor: 'rgba(6, 182, 212, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    pointRadius: 0
                },
                {
                    label: '과매수 기준 (80)',
                    data: mfiOverbought,
                    borderColor: 'rgba(245, 158, 11, 0.7)',
                    borderWidth: 1,
                    borderDash: [4, 4],
                    pointRadius: 0
                },
                {
                    label: '과매도 기준 (20)',
                    data: mfiOversold,
                    borderColor: 'rgba(56, 189, 248, 0.7)',
                    borderWidth: 1,
                    borderDash: [4, 4],
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { min: 0, max: 100, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });

    // 4. RMI (Relative Momentum Index) 상대모멘텀지수 차트
    const ctxRmi = document.getElementById('stockRmiChart').getContext('2d');
    if (stockRmiChartInstance) stockRmiChartInstance.destroy();

    const rmiOverbought = dates.map(() => 70);
    const rmiOversold = dates.map(() => 30);

    stockRmiChartInstance = new Chart(ctxRmi, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'RMI (상대모멘텀지수 14일, 4일간격)',
                    data: data.rmi || [],
                    borderColor: '#a855f7',
                    backgroundColor: 'rgba(168, 85, 247, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    pointRadius: 0
                },
                {
                    label: '과매수 기준 (70)',
                    data: rmiOverbought,
                    borderColor: 'rgba(245, 158, 11, 0.7)',
                    borderWidth: 1,
                    borderDash: [4, 4],
                    pointRadius: 0
                },
                {
                    label: '과매도 기준 (30)',
                    data: rmiOversold,
                    borderColor: 'rgba(56, 189, 248, 0.7)',
                    borderWidth: 1,
                    borderDash: [4, 4],
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8' } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { min: 0, max: 100, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

function closeStockHistoryModal() {
    const modal = document.getElementById('stockHistoryModal');
    modal.style.display = 'none';
}

// 6. 개별 종목 정보(매입단가, 보유수량, 업종) 수정 모달 제어
function openEditStockModal(id, name, avgPrice, quantity, buyDate, purpose, sector) {
    document.getElementById('editItemId').value = id;
    document.getElementById('editStockName').value = name;
    document.getElementById('editAvgPrice').value = avgPrice;
    document.getElementById('editQuantity').value = quantity;
    document.getElementById('editBuyDate').value = buyDate || '';
    document.getElementById('editPurpose').value = purpose || '장기투자';
    document.getElementById('editSector').value = sector || '기타';
    
    document.getElementById('editStockModal').style.display = 'flex';
}

function closeEditStockModal() {
    document.getElementById('editStockModal').style.display = 'none';
}

async function submitEditStock() {
    const id = document.getElementById('editItemId').value;
    const avgPrice = parseFloat(document.getElementById('editAvgPrice').value);
    const quantity = parseInt(document.getElementById('editQuantity').value);
    const buyDate = document.getElementById('editBuyDate').value;
    const purpose = document.getElementById('editPurpose').value;
    const sector = document.getElementById('editSector').value || '기타';

    if (!avgPrice || avgPrice <= 0 || !quantity || quantity <= 0) {
        alert('평균 매수가와 보유 수량을 올바르게 입력해주세요.');
        return;
    }

    try {
        const resp = await fetch(`/api/portfolio/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                avg_price: avgPrice,
                quantity: quantity,
                buy_date: buyDate,
                investment_purpose: purpose,
                sector: sector
            })
        });

        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            alert(res.message || '종목 정보(평단가/수량/업종)가 수정되었습니다.');
            closeEditStockModal();
            fetchPortfolioData(); // 포트폴리오 대시보드 실시간 자동 갱신
        } else {
            alert(`수정 실패: ${res.detail || res.error || '오류 발생'}`);
        }
    } catch (e) {
        console.error(e);
        alert(`수정 처리 중 오류가 발생했습니다: ${e.message}`);
    }
}

// ─────────────────────────────────────────────────────────────
// 📅 주요 경제 이벤트 캘린더 (향후 7일)
// ─────────────────────────────────────────────────────────────

let _calendarAllEvents = [];   // 전체 이벤트 캐시
let _calendarLoaded = false;   // 중복 로딩 방지

async function loadUpcomingCalendar() {
    if (_calendarLoaded) return;  // 이미 로딩된 경우 재호출 방지

    const listEl = document.getElementById('calendarEventsList');
    const periodEl = document.getElementById('calendarPeriodLabel');
    if (!listEl) return;

    listEl.innerHTML = '<div class="calendar-loading">📡 경제 이벤트 일정을 불러오는 중...</div>';

    try {
        const resp = await fetch('/api/calendar/upcoming?days=14');
        if (!resp.ok) throw new Error('Calendar API 오류');
        const data = await resp.json();

        if (data.status !== 'success' || !data.events || data.events.length === 0) {
            listEl.innerHTML = '<div class="calendar-empty">📭 현재 등록된 예정 이벤트가 없습니다.</div>';
            return;
        }

        _calendarAllEvents = data.events;
        _calendarLoaded = true;

        if (periodEl) {
            periodEl.textContent = `${data.period_start} ~ ${data.period_end} · 총 ${data.total_count}건`;
        }

        renderCalendarEvents('ALL');

    } catch (e) {
        console.error('Calendar load failed:', e);
        if (listEl) listEl.innerHTML = '<div class="calendar-empty">⚠️ 이벤트 일정을 불러오지 못했습니다.</div>';
    }
}

function filterCalendarEvents(category) {
    // 탭 활성화
    document.querySelectorAll('.cal-tab').forEach(btn => {
        const btnCat = btn.getAttribute('onclick')?.match(/'([^']+)'/)?.[1];
        btn.classList.toggle('active', btnCat === category);
    });
    renderCalendarEvents(category);
}

function renderCalendarEvents(filterCategory) {
    const listEl = document.getElementById('calendarEventsList');
    if (!listEl) return;

    const events = filterCategory === 'ALL'
        ? _calendarAllEvents
        : _calendarAllEvents.filter(e => e.category === filterCategory);

    if (events.length === 0) {
        listEl.innerHTML = '<div class="calendar-empty">해당 카테고리의 예정 이벤트가 없습니다.</div>';
        return;
    }

    // 날짜 그룹핑
    const grouped = {};
    events.forEach(ev => {
        const key = ev.date || '미정';
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(ev);
    });

    const importanceCfg = {
        '매우 중요': { cls: 'imp-critical', label: '🔴 매우 중요' },
        '중요':      { cls: 'imp-high',     label: '🟡 중요' },
        '보통':      { cls: 'imp-medium',   label: '⚪ 보통' },
        '참고':      { cls: 'imp-low',      label: '🔵 참고' },
    };

    let html = '';
    Object.keys(grouped).sort().forEach(dateKey => {
        const dayEvents = grouped[dateKey];
        const firstEv = dayEvents[0];
        const dayLabel = firstEv.day_label || '';
        const isToday = dateKey === new Date().toISOString().slice(0, 10);
        const todayBadge = isToday ? '<span class="cal-today-badge">TODAY</span>' : '';

        html += `
        <div class="cal-date-group">
            <div class="cal-date-header">
                <span class="cal-date-label">${dateKey} (${dayLabel})</span>
                ${todayBadge}
            </div>
            <div class="cal-events-in-day">
        `;

        dayEvents.forEach(ev => {
            const imp = importanceCfg[ev.importance] || { cls: 'imp-medium', label: '⚪ 보통' };
            const linkHtml = ev.source_url
                ? `<a href="${ev.source_url}" target="_blank" rel="noopener noreferrer" class="cal-source-link">관련 뉴스 🔗</a>`
                : '';
            const expectedHtml = ev.expected
                ? `<span class="cal-expected">예상: ${ev.expected}</span>`
                : '';
            const publisherHtml = ev.publisher && ev.publisher !== '고정 캘린더'
                ? `<span class="cal-publisher">${ev.publisher}</span>`
                : '';

            html += `
            <div class="cal-event-item ${imp.cls}">
                <div class="cal-event-left">
                    <span class="cal-country">${ev.country || '🌐'}</span>
                    <span class="cal-imp-badge ${imp.cls}">${imp.label}</span>
                </div>
                <div class="cal-event-body">
                    <div class="cal-event-name">${ev.event_name}</div>
                    <div class="cal-event-meta">
                        <span class="cal-category-tag">${ev.category}</span>
                        ${expectedHtml}
                        ${publisherHtml}
                        ${linkHtml}
                    </div>
                </div>
            </div>`;
        });

        html += `</div></div>`;
    });

    listEl.innerHTML = html;
}

// 12. 지수/환율 6개월 추이 차트 모달 함수
let indexChartInstance = null;

async function openIndexChartModal(symbol, name) {
    const modal = document.getElementById('indexChartModal');
    if (!modal) return;
    
    modal.style.display = 'flex';
    document.getElementById('indexModalTitle').innerText = `${name || symbol} 최근 6개월 변동 차트`;
    document.getElementById('indexModalSub').innerText = '데이터를 불러오는 중...';

    try {
        const resp = await fetch(`/api/market/index-history?symbol=${encodeURIComponent(symbol)}`);
        if (!resp.ok) throw new Error('지수 이력 조회 실패');
        const resData = await resp.json();
        
        if (resData.status !== 'success' || !resData.data) {
            document.getElementById('indexModalSub').innerText = '지수 이력 데이터를 불러올 수 없습니다.';
            return;
        }

        const data = resData.data;
        const rateText = data.period_rate >= 0 ? `+${data.period_rate}%` : `${data.period_rate}%`;
        const changeText = data.period_change >= 0 ? `+${data.period_change}` : `${data.period_change}`;
        
        document.getElementById('indexModalSub').innerHTML = `
            최근 종가: <b style="color:#fff">${data.latest_val ? data.latest_val.toLocaleString() : '-'}</b> &nbsp;|&nbsp; 
            6개월 최저: <b style="color:#ef4444">${data.min_val ? data.min_val.toLocaleString() : '-'}</b> &nbsp;|&nbsp; 
            6개월 최고: <b style="color:#10b981">${data.max_val ? data.max_val.toLocaleString() : '-'}</b> &nbsp;|&nbsp; 
            기간 변동: <b class="${data.period_rate >= 0 ? 'text-success' : 'text-danger'}">${changeText} (${rateText})</b>
        `;

        const canvas = document.getElementById('indexHistoryChart');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (indexChartInstance) {
            indexChartInstance.destroy();
        }

        const isPositive = data.period_rate >= 0;
        const lineGradient = ctx.createLinearGradient(0, 0, 0, 350);
        if (isPositive) {
            lineGradient.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
            lineGradient.addColorStop(1, 'rgba(16, 185, 129, 0.0)');
        } else {
            lineGradient.addColorStop(0, 'rgba(239, 68, 68, 0.35)');
            lineGradient.addColorStop(1, 'rgba(239, 68, 68, 0.0)');
        }

        indexChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.dates || [],
                datasets: [{
                    label: `${name || symbol} 종가`,
                    data: data.closes || [],
                    borderColor: isPositive ? '#10b981' : '#ef4444',
                    borderWidth: 2,
                    fill: true,
                    backgroundColor: lineGradient,
                    tension: 0.25,
                    pointRadius: 0,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(context) {
                                return `종가: ${context.parsed.y ? context.parsed.y.toLocaleString() : 0}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', maxTicksLimit: 8 }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: { color: '#94a3b8' }
                    }
                }
            }
        });
    } catch (e) {
        console.error(e);
        document.getElementById('indexModalSub').innerText = `차트 데이터를 불러오는 중 오류가 발생했습니다: ${e.message}`;
    }
}

function closeIndexChartModal() {
    const modal = document.getElementById('indexChartModal');
    if (modal) modal.style.display = 'none';
}

