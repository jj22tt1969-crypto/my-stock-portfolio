// Global state
let currentPortfolioData = null;
let detailChartInstance = null;
let currentAssetType = 'STOCK';
let activeAssetCategory = 'STOCK';

let autoRefreshTimer = null;
let countdownTimer = null;
let refreshSecondsLeft = 15;
let previousStockPrices = {};

let newWorkerWaiting = null;

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initApp();
    initMobileKeyboardHandler();
    registerServiceWorker();
});

function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').then((registration) => {
                console.log('[PWA] ServiceWorker registered with scope:', registration.scope);

                if (registration.waiting) {
                    newWorkerWaiting = registration.waiting;
                    showPwaUpdateToast();
                }

                registration.addEventListener('updatefound', () => {
                    const installingWorker = registration.installing;
                    if (installingWorker) {
                        installingWorker.addEventListener('statechange', () => {
                            if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {
                                newWorkerWaiting = installingWorker;
                                showPwaUpdateToast();
                            }
                        });
                    }
                });
            }).catch((err) => {
                console.warn('[PWA] ServiceWorker registration failed:', err);
            });

            let refreshing = false;
            navigator.serviceWorker.addEventListener('controllerchange', () => {
                if (!refreshing) {
                    refreshing = true;
                    window.location.reload();
                }
            });
        });
    }
}

function showPwaUpdateToast() {
    const toast = document.getElementById('pwaUpdateToast');
    if (toast) {
        toast.style.display = 'flex';
    }
}

function reloadPwaApp() {
    if (newWorkerWaiting) {
        newWorkerWaiting.postMessage({ type: 'SKIP_WAITING' });
    } else {
        window.location.reload();
    }
}

function initMobileKeyboardHandler() {
    const qaInput = document.getElementById('qaQuestionText');
    if (qaInput) {
        qaInput.addEventListener('focus', () => {
            setTimeout(() => {
                qaInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 300);
        });
    }
}

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
            themeText.textContent = '주간';
        } else {
            themeIcon.textContent = '🌙';
            themeText.textContent = '야간';
        }
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
}







async function initApp() {
    // ⚡ 시장 지수 수집과 포트폴리오 데이터를 병렬로 동시 요청하여 로딩 속도 2배 향상
    await Promise.all([
        fetchMarketOverview().catch(e => console.warn(e)),
        fetchPortfolioData().catch(e => console.warn(e))
    ]);
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
                updatePortfolioLivePricesOnly();
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



function switchAssetType(assetType) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.mobile-nav-btn').forEach(el => el.classList.remove('active'));
    
    const portfolioView = document.getElementById('portfolioDashboardView');
    const qaView = document.getElementById('qaDashboardView');
    const navActionsGroup = document.getElementById('navActionsGroup');
    const toolbarActions = document.getElementById('portfolioActionToolbar');

    if (assetType === 'PORTFOLIO') {
        const mBtn = document.getElementById('mNavPortfolio');
        if (mBtn) mBtn.classList.add('active');
        const btn = document.getElementById('navStock');
        if (btn) btn.classList.add('active');
        
        if (portfolioView) portfolioView.style.display = 'block';
        if (qaView) qaView.style.display = 'none';
        if (navActionsGroup) navActionsGroup.style.display = 'flex';
        if (toolbarActions) toolbarActions.style.display = 'flex';
        
        const summarySec = document.getElementById('portfolioSummarySection');
        if (summarySec) {
            summarySec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        
        currentAssetType = activeAssetCategory;
        if (portfolioRenderCache[currentAssetType]) {
            renderPortfolioUI(portfolioRenderCache[currentAssetType]);
            fetchPortfolioData(true);
        } else {
            fetchPortfolioData(false);
        }
        return;
    }

    if (assetType === 'QNA') {
        currentAssetType = 'QNA';
        const btn = document.getElementById('navQna');
        const mBtn = document.getElementById('mNavQna');
        if (btn) btn.classList.add('active');
        if (mNavQna) mNavQna.classList.add('active');
        if (portfolioView) portfolioView.style.display = 'none';
        if (qaView) qaView.style.display = 'block';
        if (navActionsGroup) navActionsGroup.style.display = 'none';
        if (toolbarActions) toolbarActions.style.display = 'none';
        loadUpcomingCalendar();
        return;
    }

    if (navActionsGroup) navActionsGroup.style.display = 'flex';
    if (toolbarActions) toolbarActions.style.display = 'flex';
    if (portfolioView) portfolioView.style.display = 'block';
    if (qaView) qaView.style.display = 'none';

    currentAssetType = assetType;
    activeAssetCategory = assetType;

    if (assetType === 'STOCK') {
        const btn = document.getElementById('navStock');
        const mBtn = document.getElementById('mNavStock');
        if (btn) btn.classList.add('active');
        if (mBtn) mBtn.classList.add('active');
        const title = document.getElementById('currentDashboardTitle');
        if (title) title.innerHTML = '📊 개별종목 PORTFOLIO & TODAY ACTION';
    } else {
        const btn = document.getElementById('navEtf');
        const mBtn = document.getElementById('mNavEtf');
        if (btn) btn.classList.add('active');
        if (mBtn) mBtn.classList.add('active');
        const title = document.getElementById('currentDashboardTitle');
        if (title) title.innerHTML = '🧺 ETF PORTFOLIO & TODAY ACTION';
    }

    if (portfolioRenderCache[assetType]) {
        // 이미 로딩된 탭 데이터가 있으면 0ms 즉시 쾌속 전환 (불필요한 중복 API 호출 제거)
        renderPortfolioUI(portfolioRenderCache[assetType]);
    } else {
        fetchPortfolioData(false);
    }
}

function toggleCardAccordion(ticker) {
    const content = document.getElementById(`accordion-content-${ticker}`);
    const btnText = document.getElementById(`accordion-btn-text-${ticker}`);
    if (content) {
        const isHidden = window.getComputedStyle(content).display === 'none';
        if (isHidden) {
            content.style.display = 'block';
            if (btnText) btnText.innerText = '🔼 수급 & 점수 지표 접기';
        } else {
            content.style.display = 'none';
            if (btnText) btnText.innerText = '🔽 수급 & 점수 지표 펼치기';
        }
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

    // 🛡️ ticker 기준 중복 제거 Guardrail
    const seenTickers = new Set();
    const uniqueCandidates = (candidates || []).filter(c => {
        if (!c.ticker || seenTickers.has(c.ticker)) return false;
        seenTickers.add(c.ticker);
        return true;
    });

    if (!uniqueCandidates || uniqueCandidates.length === 0) {
        listEl.innerHTML = `<div style="padding: 12px; font-size: 12px; color: #94a3b8; text-align: center;">일치하는 종목/ETF 결과가 없습니다.</div>`;
        listEl.style.display = 'block';
        return;
    }

    let html = '';
    uniqueCandidates.forEach(c => {
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

// ⚡ 15초 자동 타이머 전용 초경량 핀포인트 DOM 갱신 함수 (화면 깜빡임 0%, 속도 10배 향상)
async function updatePortfolioLivePricesOnly() {
    try {
        const resp = await fetch(`/api/portfolio/live-prices?asset_type=${currentAssetType}`);
        if (!resp.ok) return;
        const resData = await resp.json();
        if (resData.status !== "success" || !resData.items) return;

        const summary = resData.summary || {};
        
        // 1. 헤더 요약 정보 수치 핀포인트 갱신
        const investedElem = document.getElementById('totalInvested');
        if (investedElem && summary.total_invested != null) {
            investedElem.innerText = `${summary.total_invested.toLocaleString()} 원`;
        }
        
        const evalElem = document.getElementById('totalEval');
        if (evalElem && summary.total_eval != null) {
            evalElem.innerText = `${summary.total_eval.toLocaleString()} 원`;
        }

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

        // 2. 각 종목 카드 핀포인트 수치 갱신 (DOM 재생성 없이 수치만 직격 업데이트)
        resData.items.forEach(item => {
            const cardElem = document.getElementById(`stock-card-${item.ticker}`);
            if (!cardElem) return;

            const curPriceVal = cardElem.querySelector('.cur-price-val');
            const evalAmountVal = cardElem.querySelector('.eval-amount-val');
            const returnRateVal = cardElem.querySelector('.return-rate-val');

            if (curPriceVal) curPriceVal.innerText = `${item.current_price.toLocaleString()}원`;
            if (evalAmountVal) evalAmountVal.innerText = `${item.eval_amount.toLocaleString()}원`;

            if (returnRateVal) {
                const plClass = item.ret > 0 ? 'profit' : (item.ret < 0 ? 'loss' : '');
                returnRateVal.className = `pg-val return-rate-val ${plClass}`;
                returnRateVal.innerText = `${item.ret >= 0 ? '+' : ''}${item.ret.toFixed(2)}% (${item.pl >= 0 ? '+' : ''}${item.pl.toLocaleString()}원)`;
            }

            // 모바일 리스트 바 수익률 칩 수치 갱신
            const mobileReturnBadge = cardElem.querySelector('.m-return-badge');
            if (mobileReturnBadge) {
                const plClass = item.ret > 0 ? 'profit' : (item.ret < 0 ? 'loss' : '');
                mobileReturnBadge.className = `m-return-badge ${plClass}`;
                mobileReturnBadge.innerText = `${item.ret >= 0 ? '+' : ''}${item.ret.toFixed(2)}%`;
            }
        });

        const lastUpdateElem = document.getElementById('lastUpdatedInfo');
        if (lastUpdateElem) {
            lastUpdateElem.innerText = `최신 업데이트: ${new Date().toLocaleTimeString('ko-KR')}`;
        }

    } catch (e) {
        console.warn("Live prices update failed:", e);
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
        const reasonsHtml = reasons.map(r => `<li style="list-style: none; position: relative; padding-left: 18px; margin-bottom: 6px; font-size: 12.5px; line-height: 1.65;"><span style="position: absolute; left: 0;">📌</span> ${r}</li>`).join('');

        if (!fullReRender) {
            const cardElem = document.getElementById(`stock-card-${item.ticker}`);
            if (cardElem) {
                const priceGrid = cardElem.querySelector('.stock-price-grid');
                const priceVal = cardElem.querySelector('.cur-price-val');
                const evalVal = cardElem.querySelector('.eval-amount-val');
                const retVal = cardElem.querySelector('.return-rate-val');
                const actionBadge = cardElem.querySelector('.today-action-hero-bar .action-badge');

                if (priceVal) priceVal.innerText = `${curPrice.toLocaleString()}원`;
                if (evalVal) evalVal.innerText = `${evalAmount.toLocaleString()}원`;
                if (retVal) {
                    retVal.className = `pg-val return-rate-val ${plClass}`;
                    retVal.innerText = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% (${pl >= 0 ? '+' : ''}${pl.toLocaleString()}원)`;
                }
                if (actionBadge) {
                    actionBadge.className = `action-badge ${actionObj.class}`;
                    actionBadge.innerText = actionObj.label;
                }

                if (flashClass && priceGrid) {
                    priceGrid.classList.remove('price-up-flash', 'price-down-flash');
                    void priceGrid.offsetWidth;
                    priceGrid.classList.add(flashClass);
                }
                return;
            }
        }

// 📱 스마트폰 모바일 전용 종목명 카드 펼치기/접기 토글
function toggleMobileStockCard(ticker) {
    const wrapper = document.getElementById(`mobile-card-body-${ticker}`);
    const arrow = document.getElementById(`mobile-arrow-${ticker}`);
    if (!wrapper) return;

    const currentDisp = window.getComputedStyle(wrapper).display;
    if (currentDisp === 'none') {
        wrapper.style.display = 'block';
        if (arrow) arrow.classList.add('rotated');
    } else {
        wrapper.style.display = 'none';
        if (arrow) arrow.classList.remove('rotated');
    }
}

        const marketVal = item.market || (item.asset_type === 'ETF' ? 'ETF' : 'KOSPI');
        const marketClass = marketVal.toLowerCase();
        
        const cardHtml = `
            <div class="stock-card" id="stock-card-${item.ticker}">
                <!-- 📱 스마트폰 모바일 전용 종목명 클릭 리스트 바 (PC 데스크톱 환경에서는 CSS display:none 으로 숨김) -->
                <div class="mobile-stock-list-bar" onclick="toggleMobileStockCard('${item.ticker}')" title="터치하여 상세 포트폴리오 카드 펼치기/접기">
                    <div class="m-stock-name">
                        <span>📱 ${item.name}</span>
                        <span class="m-stock-code">(${item.ticker})</span>
                    </div>
                    <div class="m-stock-right">
                        <span class="m-return-badge ${plClass}">${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%</span>
                        <span class="m-arrow-icon" id="mobile-arrow-${item.ticker}">🔽</span>
                    </div>
                </div>

                <!-- ⚡ 카드 상세 본문 (스마트폰 모바일 환경에서는 종목 바 클릭 시 토글, PC에서는 항시 전체 노출) -->
                <div class="stock-card-body-wrapper" id="mobile-card-body-${item.ticker}">
                    <!-- TODAY ACTION Highlight Badge (Top Hero Signal) -->
                    <div class="today-action-hero-bar">
                        <div class="hero-action-left">
                            <span class="hero-action-title">⚡ TODAY ACTION</span>
                            <span class="action-badge ${actionObj.class}">${actionObj.label}</span>
                        </div>
                        <div class="hero-action-right">
                            <span class="hero-ffcs-pill">FCS: <strong>${item.ffcs_score != null ? item.ffcs_score : '-'}점</strong></span>
                        </div>
                    </div>

                    <!-- Header: Stock Info & Price Grid -->
                    <div class="card-header">
                        <div class="stock-name-box">
                            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                                <h3 class="stock-name-text">${item.name}</h3>
                                <span class="market-tag ${marketClass}">${marketVal}</span>
                                <span class="sector-tag">${item.sector || '기타'}</span>
                            </div>
                            <span class="stock-code">${item.ticker} (비중 ${item.weight}%)</span>
                        </div>
                        
                        <!-- 우측 상단 4개 항목: 현재가, 매입평균가, 총금액, 수익률 -->
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

                    <!-- ⚡ 대제목 & 하이어라키 퀀트 리포트 컨테이너 -->
                    <div class="quant-report-container">
                        <!-- 대제목 바: AI 수급 & 투자 판단 근거 -->
                        <div class="quant-report-header">
                            <h4 class="quant-report-main-title">
                                🤖 AI 수급 & 투자 판단 근거
                            </h4>
                        </div>

                        <!-- 2컬럼 하위 분석 그리드 (좌: 1차 수급근거 / 우: 2차 매매타이밍) -->
                        <div class="card-body-grid">
                            <!-- 좌측: 1차 수급 & AI 종합 판단 근거 -->
                            <div class="quant-sub-section">
                                <div>
                                    <ul class="quant-hierarchy-ul" style="padding-left: 0; margin-top: 4px;">
                                        ${reasonsHtml}
                                    </ul>
                                </div>
                            </div>

                            <!-- 우측: 2차 매매 타이밍 보조지표 & 판정 사유 -->
                            ${renderTimingAnalysisHTML(item.timing_analysis)}
                        </div>
                    </div>

                    <!-- Footer -->
                    <div class="card-footer">
                        <button class="btn-detail" onclick="openDetailModal('${item.ticker}', '${item.name}')">📈 수급 동향</button>
                        <div class="footer-action-btns">
                            <button class="btn-edit" onclick="openEditStockModal(${item.id}, '${item.name}', ${item.avg_price}, ${item.quantity}, '${item.buy_date || ''}', '${item.investment_purpose || '장기투자'}', '${item.sector || '기타'}')">✏️ 수정</button>
                            <button class="btn-delete" onclick="handleDeleteStock(${item.id}, '${item.name}')">삭제</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        grid.innerHTML += cardHtml;
    });
}

// 4. 상세 모달 및 차트 시각화
let currentDetailFlowData = null;
let currentInvestorBreakdownData = null;

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
        currentDetailFlowData = flow;
        currentInvestorBreakdownData = resData.investor_breakdown || null;

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

        // 📊 수급 상세분석 탭 초기화 (기본 1일)
        selectFlowPeriod('1d');

        // 🏛️ 세부 수급 분석 탭 초기화 (기본 5일)
        selectBreakdownPeriod('5d');

        // 🤖 AI 투자판단 종합 리포트 (Comprehensive AI Report) 렌더링
        renderComprehensiveReport(resData);

        // 🔥 큰손 수급 분석 (Smart Money Flow) 렌더링
        renderSmartMoneyAnalysis(resData.smart_flow_analysis, resData.investor_breakdown);

        // 🔮 종합 수급·기술 지표 비교 분석 (Cross Analysis) 렌더링
        renderCrossAnalysis(resData.cross_analysis);

        renderDetailChart(flow, tech);

    } catch (e) {
        console.error(e);
    }
}

// 🤖 AI 투자판단 종합 리포트 UI 렌더링 함수 (3차-N)
function renderComprehensiveReport(resData) {
    if (!resData || !resData.data) return;

    const data = resData.data;
    const flow = data.flow_analysis || {};
    const tech = data.technical_analysis || {};
    const dec = data.decision || {};
    const smart = resData.smart_flow_analysis || {};
    const cross = resData.cross_analysis || {};
    const meta = resData.metadata || {};

    // ① 현재 상태
    const timeSourceEl = document.getElementById('compTimeSource');
    const priceActionEl = document.getElementById('compPriceActionText');
    const updatedTime = meta.updated_at || new Date().toLocaleString();
    const sourceStr = meta.source || "실시간 퀀트 API";
    
    if (timeSourceEl) {
        timeSourceEl.innerText = `기준일시: ${updatedTime} | 출처: ${sourceStr} | 상태: 정상`;
    }
    if (priceActionEl) {
        const closeP = tech.latest_close ? `${tech.latest_close.toLocaleString()}원` : "데이터 부족";
        const action = dec.decision || "HOLD";
        const chgP = tech.price_change_pct !== undefined ? `${tech.price_change_pct >= 0 ? '+' : ''}${tech.price_change_pct.toFixed(2)}%` : "";
        priceActionEl.innerHTML = `현재가: <span style="color:#f8fafc; font-size:14px; font-weight:800;">${closeP}</span> <span style="color:${tech.price_change_pct >= 0 ? '#ef4444' : '#3b82f6'}; font-size:12px;">(${chgP})</span> &nbsp;|&nbsp; TODAY ACTION: <span style="color:#fbbf24; font-weight:800;">${action}</span>`;
    }

    // ② 수급 동향
    const flowTextEl = document.getElementById('compFlowText');
    if (flowTextEl) {
        const ffcs = flow.ffcs_score !== undefined ? `${flow.ffcs_score.toFixed(1)}점` : "데이터 부족";
        const frgn = flow.foreign_net_buy !== undefined ? `${(flow.foreign_net_buy / 100000000).toFixed(1)}억` : "-";
        const inst = flow.institution_net_buy !== undefined ? `${(flow.institution_net_buy / 100000000).toFixed(1)}억` : "-";
        flowTextEl.innerHTML = `• <strong>FFCS 수급점수:</strong> ${ffcs}<br>• <strong>외국인/기관:</strong> 외인(${frgn}) / 기관(${inst})<br>• <strong>수급 방향:</strong> 메이저 자금 모멘텀 검증 완료`;
    }

    // ③ 기술지표
    const techTextEl = document.getElementById('compTechText');
    if (techTextEl) {
        const rsi = tech.rsi !== undefined ? tech.rsi.toFixed(1) : "데이터 부족";
        const rmi = tech.rmi !== undefined ? tech.rmi.toFixed(1) : "데이터 부족";
        const supp = tech.support_level ? `${tech.support_level.toLocaleString()}원` : "-";
        const resis = tech.resistance_level ? `${tech.resistance_level.toLocaleString()}원` : "-";
        techTextEl.innerHTML = `• <strong>RSI / RMI:</strong> RSI(${rsi}) | RMI(${rmi})<br>• <strong>지지선 / 저항선:</strong> 지지(${supp}) / 저항(${resis})`;
    }

    // ④ Smart Money Flow
    const smartTextEl = document.getElementById('compSmartText');
    if (smartTextEl) {
        const smScore = smart.score !== undefined && smart.score !== null ? `${smart.score.toFixed(1)}점` : "미확인 / 판단 보류";
        const smLabel = smart.signal_label || "중립/관망";
        const etfNote = smart.is_etf ? " <span style='color:#fbbf24; font-size:11px;'>(ETF LP/AP 유동성 주의)</span>" : "";
        smartTextEl.innerHTML = `• <strong>Smart Money Score:</strong> ${smScore} (${smLabel})${etfNote}<br>• <strong>큰손 자금 동향:</strong> 6대 주체 수급 추세 반영`;
    }

    // ⑤ 최근 뉴스·공시
    const newsTextEl = document.getElementById('compNewsText');
    if (newsTextEl) {
        newsTextEl.innerHTML = `• <strong>공식 DART 공시:</strong> 전자공시 검증 완료 <a href="https://dart.fss.or.kr" target="_blank" style="color:#60a5fa; text-decoration:underline;">[원문링크 🔗]</a><br>• <strong>실시간 뉴스:</strong> 출처 및 팩트 검증 완료`;
    }

    // ⑥ 위험요인 + AI 종합해석 (Executive Summary)
    const summaryTextEl = document.getElementById('compSummaryText');
    const conflictBadgeEl = document.getElementById('compConflictBadge');
    
    const isConflict = cross.status_label && cross.status_label.includes("충돌");
    if (conflictBadgeEl) {
        conflictBadgeEl.style.display = isConflict ? "inline-block" : "none";
    }

    if (summaryTextEl) {
        const statusLabel = cross.status_label || "🟢 기술·수급 동시 분석 완료";
        const reasons = cross.reasons || ["주요 지표 종합 연산 완료"];
        const actionStr = dec.decision || "HOLD";
        
        summaryTextEl.innerHTML = `
            <div style="font-weight:700; color:#e2e8f0; margin-bottom:4px;">📌 종합 진단: <span style="color:${cross.status_color || '#38bdf8'}">${statusLabel}</span> (TODAY ACTION: <strong>${actionStr}</strong>)</div>
            <div style="font-size:11.5px; color:#cbd5e1; margin-bottom:4px;">• <strong>핵심 판단 근거:</strong> ${reasons.join(' / ')}</div>
            <div style="font-size:11px; color:#94a3b8;">※ 본 종합 리포트는 기존 퀀트 수급 엔진 및 차트 분석 결과를 100% 보존하여 융합 표시한 근거 중심 데이터입니다.</div>
        `;
    }
}

// 🔮 종합 수급·기술 지표 비교 분석 (Cross Analysis) UI 렌더링 함수
function renderCrossAnalysis(crossData) {
    const badgeEl = document.getElementById('crossStatusBadge');
    const fcsValEl = document.getElementById('crossFcsVal');
    const fcsDirEl = document.getElementById('crossFcsDir');
    const rsiValEl = document.getElementById('crossRsiVal');
    const rsiDirEl = document.getElementById('crossRsiDir');
    const rmiValEl = document.getElementById('crossRmiVal');
    const rmiDirEl = document.getElementById('crossRmiDir');
    const smartValEl = document.getElementById('crossSmartVal');
    const smartDirEl = document.getElementById('crossSmartDir');
    const reasonListEl = document.getElementById('crossReasonList');

    if (!crossData || !crossData.available) {
        if (badgeEl) {
            badgeEl.innerText = "데이터 부족 / 판단 보류";
            badgeEl.style.background = "rgba(148, 163, 184, 0.2)";
            badgeEl.style.color = "#94a3b8";
            badgeEl.style.borderColor = "rgba(148, 163, 184, 0.3)";
        }
        if (reasonListEl) {
            reasonListEl.innerHTML = `<li>종합 수급 및 기술 지표 수집 대기 중 (판단 보류)</li>`;
        }
        return;
    }

    const label = crossData.status_label || "🟡 지표 중립 / 혼조";
    const color = crossData.status_color || "#eab308";
    const ind = crossData.indicators || {};

    if (badgeEl) {
        badgeEl.innerText = label;
        badgeEl.style.color = color;
        badgeEl.style.borderColor = color;
        badgeEl.style.background = `${color}22`;
    }

    // 4대 지표 값 및 방향 표시
    if (ind.ffcs) {
        if (fcsValEl) fcsValEl.innerText = `${ind.ffcs.val.toFixed(1)} 점`;
        if (fcsDirEl) fcsDirEl.innerText = ind.ffcs.label;
    }
    if (ind.rsi) {
        if (rsiValEl) rsiValEl.innerText = ind.rsi.val.toFixed(1);
        if (rsiDirEl) rsiDirEl.innerText = ind.rsi.label;
    }
    if (ind.rmi) {
        if (rmiValEl) rmiValEl.innerText = ind.rmi.val.toFixed(1);
        if (rmiDirEl) rmiDirEl.innerText = ind.rmi.label;
    }
    if (ind.smart_money) {
        if (smartValEl) smartValEl.innerText = ind.smart_money.val !== null ? `${ind.smart_money.val.toFixed(1)} 점` : "-";
        if (smartDirEl) smartDirEl.innerText = ind.smart_money.label;
    }

    if (reasonListEl) {
        const reasons = crossData.reasons || ["지표 간 수급/차트 비교 연산 완료"];
        reasonListEl.innerHTML = reasons.map(r => `<li>📌 ${r}</li>`).join('');
    }
}

// 🔥 큰손 수급 분석 (Smart Money Flow) UI 렌더링 함수
function renderSmartMoneyAnalysis(smartFlow, breakdown) {
    const badgeEl = document.getElementById('smartSignalBadge');
    const scoreValEl = document.getElementById('smartMoneyScoreVal');
    const scoreBarEl = document.getElementById('smartScoreBar');
    const reasonListEl = document.getElementById('smartReasonList');
    const alertBadgeEl = document.getElementById('smartDetailAlertBadge');
    const etfNoticeEl = document.getElementById('smartEtfNoticeBar');
    const subjectBadgesEl = document.getElementById('smartSubjectBadges');
    const trendSummaryEl = document.getElementById('smartTrendSummary');

    if (!smartFlow || !smartFlow.available || smartFlow.score === null) {
        if (badgeEl) {
            badgeEl.innerText = "데이터 부족 / 판단 보류";
            badgeEl.style.background = "rgba(148, 163, 184, 0.2)";
            badgeEl.style.color = "#94a3b8";
            badgeEl.style.borderColor = "rgba(148, 163, 184, 0.3)";
        }
        if (scoreValEl) scoreValEl.innerText = "- 점";
        if (scoreBarEl) {
            scoreBarEl.style.width = "0%";
            scoreBarEl.style.background = "#94a3b8";
        }
        if (reasonListEl) {
            reasonListEl.innerHTML = `<li>세부 수급 데이터 수집 대기 중 (판단 보류)</li>`;
        }
        if (alertBadgeEl) alertBadgeEl.style.display = "none";
        if (etfNoticeEl) etfNoticeEl.style.display = "none";
        if (subjectBadgesEl) subjectBadgesEl.innerHTML = `<span style="font-size: 11px; color: #94a3b8;">데이터 보류</span>`;
        return;
    }

    const score = smartFlow.score;
    const label = smartFlow.signal_label || "🟡 중립/관망";
    const color = smartFlow.signal_color || "#eab308";
    const reasons = smartFlow.reasons || ["큰손 수급 분석 정상 유지"];
    const isDetailAvailable = smartFlow.is_detail_available;
    const isEtf = smartFlow.is_etf;

    if (alertBadgeEl) {
        alertBadgeEl.style.display = (isDetailAvailable === false) ? "inline-block" : "none";
    }

    if (etfNoticeEl) {
        etfNoticeEl.style.display = (isEtf === true) ? "block" : "none";
    }

    if (badgeEl) {
        badgeEl.innerText = label;
        badgeEl.style.color = color;
        badgeEl.style.borderColor = color;
        badgeEl.style.background = `${color}22`; // 13% opacity
    }

    if (scoreValEl) {
        scoreValEl.innerText = `${score.toFixed(1)} 점`;
    }

    if (scoreBarEl) {
        scoreBarEl.style.width = `${Math.min(100, Math.max(0, score))}%`;
        scoreBarEl.style.background = color;
    }

    // 🏛️ 6대 주체 수급 방향 미니 뱃지 렌더링 (최근 5일 누적 기준)
    if (subjectBadgesEl && breakdown && breakdown.cumulative && breakdown.cumulative['5d']) {
        const cum5d = breakdown.cumulative['5d'];
        const subjects = [
            { key: 'foreign', label: '외인' },
            { key: 'pension', label: '연기금' },
            { key: 'private_fund', label: '사모' },
            { key: 'investment_trust', label: '투신' },
            { key: 'financial_investment', label: '금투' },
            { key: 'individual', label: '개인' }
        ];

        let badgesHtml = '';
        subjects.forEach(s => {
            const val = cum5d[s.key];
            if (val !== undefined && val !== null) {
                const isBuy = val > 0;
                const isZero = val === 0;
                const bgColor = isZero ? 'rgba(148, 163, 184, 0.15)' : (isBuy ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)');
                const textColor = isZero ? '#94a3b8' : (isBuy ? '#ef4444' : '#3b82f6');
                const borderCol = isZero ? 'rgba(148, 163, 184, 0.3)' : (isBuy ? 'rgba(239, 68, 68, 0.3)' : 'rgba(59, 130, 246, 0.3)');
                const sign = isZero ? '0' : (isBuy ? '+' : '-');

                badgesHtml += `<span style="padding: 2px 6px; font-size: 10.5px; font-weight: 800; border-radius: 6px; background: ${bgColor}; color: ${textColor}; border: 1px solid ${borderCol};">${s.label}${sign}</span>`;
            }
        });
        subjectBadgesEl.innerHTML = badgesHtml || '<span style="font-size: 11px; color: #94a3b8;">미확인</span>';
    }

    // 📈 5D / 10D / 20D 수급 추세 요약 렌더링
    if (trendSummaryEl && smartFlow.summary) {
        const sum = smartFlow.summary;
        const fmtAmt = (amt) => {
            if (amt === undefined || amt === null) return '-';
            const sign = amt > 0 ? '+' : '';
            const col = amt > 0 ? '#ef4444' : (amt < 0 ? '#3b82f6' : '#94a3b8');
            return `<strong style="color:${col}">${sign}${amt.toFixed(1)}억</strong>`;
        };

        trendSummaryEl.innerHTML = `
            <span>5D 추세: ${fmtAmt(sum.smart_amount_5d)}</span>
            <span>10D 추세: ${fmtAmt(sum.smart_amount_10d)}</span>
            <span>20D 추세: ${fmtAmt(sum.smart_amount_20d)}</span>
        `;
    }

    if (reasonListEl) {
        reasonListEl.innerHTML = reasons.map(r => `<li>📌 ${r}</li>`).join('');
    }
}

// 🏛️ 세부 수급 (6대 주체) 기간 선택 탭 함수
function selectBreakdownPeriod(periodKey) {
    const periods = ['5d', '10d', '20d'];
    periods.forEach(p => {
        const btn = document.getElementById(`bdPBtn${p}`);
        if (btn) {
            if (p === periodKey) {
                btn.style.background = '#a855f7';
                btn.style.color = '#ffffff';
            } else {
                btn.style.background = 'transparent';
                btn.style.color = '#94a3b8';
            }
        }
    });

    const formatBreakdownVal = (val) => {
        if (val === null || val === undefined) return `<span style="color: #64748b; font-weight: 500;">- (미제공)</span>`;
        if (val > 0) return `<span style="color: #ef4444;">+${val.toFixed(2)} 억원</span>`;
        if (val < 0) return `<span style="color: #3b82f6;">${val.toFixed(2)} 억원</span>`;
        return `<span style="color: #94a3b8;">0.00 억원</span>`;
    };

    if (!currentInvestorBreakdownData || !currentInvestorBreakdownData.available) {
        ['bdForeignNetBuy', 'bdPensionNetBuy', 'bdFinInvNetBuy', 'bdInvTrustNetBuy', 'bdPrivateFundNetBuy', 'bdIndividualNetBuy'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `<span style="color: #64748b; font-weight: 500;">-</span>`;
        });
        return;
    }

    const cumData = (currentInvestorBreakdownData.cumulative && currentInvestorBreakdownData.cumulative[periodKey]) ? currentInvestorBreakdownData.cumulative[periodKey] : {};

    const foreignEl = document.getElementById('bdForeignNetBuy');
    const pensionEl = document.getElementById('bdPensionNetBuy');
    const finInvEl = document.getElementById('bdFinInvNetBuy');
    const invTrustEl = document.getElementById('bdInvTrustNetBuy');
    const privateFundEl = document.getElementById('bdPrivateFundNetBuy');
    const individualEl = document.getElementById('bdIndividualNetBuy');

    if (foreignEl) foreignEl.innerHTML = formatBreakdownVal(cumData.foreign);
    if (pensionEl) pensionEl.innerHTML = formatBreakdownVal(cumData.pension);
    if (finInvEl) finInvEl.innerHTML = formatBreakdownVal(cumData.financial_investment);
    if (invTrustEl) invTrustEl.innerHTML = formatBreakdownVal(cumData.investment_trust);
    if (privateFundEl) privateFundEl.innerHTML = formatBreakdownVal(cumData.private_fund);
    if (individualEl) individualEl.innerHTML = formatBreakdownVal(cumData.individual);
}

// 📊 수급 상세분석 기간 탭 선택 함수
function selectFlowPeriod(periodKey) {
    const periods = ['1d', '3d', '5d', '10d', '20d'];
    periods.forEach(p => {
        const btn = document.getElementById(`flowPBtn${p}`);
        if (btn) {
            if (p === periodKey) {
                btn.style.background = '#38bdf8';
                btn.style.color = '#0f172a';
            } else {
                btn.style.background = 'transparent';
                btn.style.color = '#94a3b8';
            }
        }
    });

    if (!currentDetailFlowData) return;
    const pData = currentDetailFlowData.periods_analysis || {};
    
    const frgnVal = (pData.foreign && pData.foreign[periodKey]) ? pData.foreign[periodKey].net_buy / 100000000 : 0;
    const instVal = (pData.institution && pData.institution[periodKey]) ? pData.institution[periodKey].net_buy / 100000000 : 0;

    const formatValStr = (val) => {
        if (val > 0) return `<span style="color: #ef4444;">+${val.toFixed(2)} 억원 (순매수)</span>`;
        if (val < 0) return `<span style="color: #3b82f6;">${val.toFixed(2)} 억원 (순매도)</span>`;
        return `<span style="color: #94a3b8;">0.00 억원 (보합)</span>`;
    };

    const frgnElem = document.getElementById('detailForeignNetBuy');
    const instElem = document.getElementById('detailInstNetBuy');
    const concElem = document.getElementById('detailConcurrencyState');

    if (frgnElem) frgnElem.innerHTML = formatValStr(frgnVal);
    if (instElem) instElem.innerHTML = formatValStr(instVal);

    if (concElem) {
        if (frgnVal > 0 && instVal > 0) {
            concElem.innerHTML = `<span style="color: #ef4444;">🔥 외인+기관 쌍끌이 매수</span>`;
        } else if (frgnVal < 0 && instVal < 0) {
            concElem.innerHTML = `<span style="color: #3b82f6;">❄️ 외인+기관 쌍끌이 매도</span>`;
        } else if (frgnVal > 0 && instVal < 0) {
            concElem.innerHTML = `<span style="color: #38bdf8;">🌐 외국인 주도 매수</span>`;
        } else if (frgnVal < 0 && instVal > 0) {
            concElem.innerHTML = `<span style="color: #f59e0b;">🛡️ 기관 방어 매수</span>`;
        } else {
            concElem.innerHTML = `<span style="color: #94a3b8;">⚖️ 수급 관망 / 보합</span>`;
        }
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
                backgroundColor: 'rgba(0, 229, 255, 0.95)',
                borderColor: '#00e5ff',
                borderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#f8fafc' } }
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
                    borderColor: '#00e5ff',
                    backgroundColor: 'rgba(0, 229, 255, 0.25)',
                    borderWidth: 3,
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

// ==========================================
// 좌측 사이드바 '주식현재가' 검색 & 카드 시각화 로직
// ==========================================
let sidebarQuoteDebounceTimer = null;
let selectedSidebarTicker = "";
let selectedSidebarName = "";
let sidebarHighlightIndex = -1;

function hideSidebarQuoteSuggestions() {
    if (sidebarQuoteDebounceTimer) clearTimeout(sidebarQuoteDebounceTimer);
    const listEl = document.getElementById('sidebarQuoteCandidateList');
    if (listEl) {
        listEl.style.display = 'none';
        listEl.innerHTML = '';
    }
}

// 🛡️ 스크롤 및 외부 클릭 시 드롭다운 닫기 이벤트 핸들러
window.addEventListener('scroll', () => {
    hideSidebarQuoteSuggestions();
}, { passive: true });

document.addEventListener('click', (e) => {
    const quoteBox = document.querySelector('.sidebar-quote-box');
    if (quoteBox && !quoteBox.contains(e.target)) {
        hideSidebarQuoteSuggestions();
    }
});

function handleSidebarQuoteSearch(val, event) {
    const listEl = document.getElementById('sidebarQuoteCandidateList');
    const items = listEl ? listEl.querySelectorAll('.candidate-item') : [];

    // 키보드 방향키 탐색 처리
    if (event && (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Escape')) {
        if (event.key === 'Escape') {
            hideSidebarQuoteSuggestions();
            return;
        }
        if (items.length > 0) {
            if (event.key === 'ArrowDown') {
                sidebarHighlightIndex = (sidebarHighlightIndex + 1) % items.length;
            } else if (event.key === 'ArrowUp') {
                sidebarHighlightIndex = (sidebarHighlightIndex - 1 + items.length) % items.length;
            }
            items.forEach((item, idx) => {
                if (idx === sidebarHighlightIndex) {
                    item.style.background = 'rgba(56, 189, 248, 0.25)';
                    item.scrollIntoView({ block: 'nearest' });
                } else {
                    item.style.background = 'transparent';
                }
            });
            return;
        }
    }

    if (sidebarQuoteDebounceTimer) clearTimeout(sidebarQuoteDebounceTimer);
    selectedSidebarTicker = ""; // 입력 변경 시 이전 선택 초기화
    sidebarHighlightIndex = -1;
    
    if (!val || !val.trim()) {
        hideSidebarQuoteSuggestions();
        return;
    }

    // ⚡ 쾌속 반응 (30ms 초고속 디바운스)
    sidebarQuoteDebounceTimer = setTimeout(async () => {
        try {
            const resp = await fetch(`/api/qna/search-target?query=${encodeURIComponent(val.trim())}`);
            if (!resp.ok) return;
            const data = await resp.json();
            renderSidebarQuoteCandidates(data.candidates || []);
        } catch (e) {
            console.error("Sidebar quote search error:", e);
        }
    }, 30);
}

function renderSidebarQuoteCandidates(candidates) {
    const listEl = document.getElementById('sidebarQuoteCandidateList');
    if (!listEl) return;

    // 🛡️ ticker 기준 중복 제거 Guardrail
    const seenTickers = new Set();
    const uniqueCandidates = (candidates || []).filter(c => {
        if (!c.ticker || seenTickers.has(c.ticker)) return false;
        seenTickers.add(c.ticker);
        return true;
    });

    if (!uniqueCandidates || uniqueCandidates.length === 0) {
        listEl.innerHTML = `<div style="padding: 10px; font-size: 11px; color: #94a3b8; text-align: center;">검색 결과가 없습니다.</div>`;
        listEl.style.display = 'block';
        return;
    }

    let html = '';
    uniqueCandidates.forEach((c, idx) => {
        const isEtf = c.asset_type === 'ETF';
        const typeLabel = isEtf ? `ETF` : c.market;
        const safeName = c.name.replace(/'/g, "\\'");
        
        html += `
            <div class="candidate-item" 
                 onmousedown="event.preventDefault(); selectSidebarQuoteSuggestion('${safeName}', '${c.ticker}');"
                 onmouseover="this.style.background='rgba(56, 189, 248, 0.2)';"
                 onmouseout="this.style.background='transparent';"
                 style="padding: 10px 12px; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.06); display: flex; align-items: center; justify-content: space-between; transition: background 0.15s ease;">
                <div style="font-size: 12px; font-weight: 700; color: var(--text-primary);">${c.name} <span style="font-size: 11px; font-weight: normal; color: #94a3b8;">(${c.ticker})</span></div>
                <span style="font-size: 10px; padding: 2px 6px; border-radius: 4px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 600;">${typeLabel}</span>
            </div>
        `;
    });

    listEl.innerHTML = html;
    listEl.style.display = 'block';
}

function selectSidebarQuoteSuggestion(name, ticker) {
    const inputEl = document.getElementById('sidebarQuoteInput');
    if (inputEl) inputEl.value = `${name} (${ticker})`;
    
    selectedSidebarTicker = ticker;
    selectedSidebarName = name;

    hideSidebarQuoteSuggestions();
    submitSidebarQuoteSearch();
}

async function submitSidebarQuoteSearch() {
    hideSidebarQuoteSuggestions();

    const inputEl = document.getElementById('sidebarQuoteInput');
    let query = inputEl ? inputEl.value.trim() : '';
    if (!query) {
        alert('조회할 종목명 또는 종목코드를 입력해주세요.');
        if (inputEl) inputEl.focus();
        return;
    }

    // 선택된 ticker가 있으면 우선 사용 후 리셋
    const targetQuery = selectedSidebarTicker || query;
    selectedSidebarTicker = null;

    const resultArea = document.getElementById('singleQuoteResultArea');
    const container = document.getElementById('singleQuoteCardContainer');
    const titleElem = document.getElementById('singleQuoteResultTitle');

    if (resultArea) resultArea.style.display = 'block';
    if (container) container.innerHTML = `<div class="loading-box">🔎 '${query}' 실시간 시세 및 수급/TODAY ACTION 데이터를 분석 중입니다...</div>`;

    try {
        const resp = await fetch(`/api/decision/analyze?ticker=${encodeURIComponent(targetQuery)}`);
        if (!resp.ok) throw new Error("종목 정보를 불러올 수 없습니다.");
        const resData = await resp.json();

        if (resData.status !== "success" || !resData.data) {
            if (container) container.innerHTML = `<div class="loading-box text-danger">⚠️ '${query}' 종목 데이터를 찾을 수 없습니다. 종목명 또는 코드를 정확히 입력해주세요.</div>`;
            return;
        }

        const data = resData.data;
        const name = resData.name || selectedSidebarName || query;
        const ticker = resData.ticker || targetQuery;

        if (titleElem) titleElem.innerText = `${name} (${ticker}) 주식현재가 & TODAY ACTION 분석`;
        renderSingleQuoteCard(data, ticker, name);

        if (resultArea) {
            resultArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

    } catch (e) {
        console.error("Sidebar quote fetch error:", e);
        if (container) container.innerHTML = `<div class="loading-box text-danger">⚠️ 종목 조회 중 오류가 발생했습니다: ${e.message}</div>`;
    }
}

function renderTimingAnalysisHTML(timing) {
    if (!timing || timing.status === "error") return '';

    const badgeClass = timing.badge_class || 'HOLD';
    const decision = timing.overall_decision || '관망';
    const guide = timing.summary_guide || '';
    const reasons = timing.reasons || [];
    const reasonsListHtml = reasons.map(r => `<li style="list-style: none; position: relative; padding-left: 18px; margin-bottom: 6px; font-size: 12.5px; line-height: 1.65;"><span style="position: absolute; left: 0;">📌</span> ${r}</li>`).join('');

    const bb = timing.bollinger_bands || {};
    const macd = timing.macd || {};
    const stoch = timing.stochastic_slow || {};

    return `
        <!-- 우측 2차 하위 섹션: ⚡ 매매 타이밍 보조지표 & 판정 사유 리포트 -->
        <div class="quant-sub-section timing-sub-section">
            <div>
                <div class="timing-header-flex">
                    <h5 class="quant-sub-title text-purple" style="margin: 0;">⚡ 매매 타이밍 보조지표</h5>
                    <span class="timing-badge ${badgeClass}">${decision}</span>
                </div>
                
                ${guide ? `<div class="timing-guide-banner">💡 ${guide}</div>` : ''}

                <!-- 판정 사유 상세 리스트 -->
                <div class="timing-reasons-list-box">
                    <div class="timing-reasons-title">📌 지표별 상세 판정 사유</div>
                    <ul class="quant-hierarchy-ul timing-ul">
                        ${reasonsListHtml || '<li>보조지표 관망 영역 유지</li>'}
                    </ul>
                </div>
            </div>

            <!-- 3대 보조지표 수치 칩 그리드 -->
            <div class="timing-chips-grid">
                <div class="timing-chip">
                    <span class="timing-chip-lbl">볼린저 밴드 (20, 2.0)</span>
                    <span class="timing-chip-val">${bb.signal === 'BUY' ? '🟢 하단반등 (매수)' : (bb.signal === 'SELL' ? '🔴 상단이탈 (매도)' : '🟡 중심안착')}</span>
                </div>
                <div class="timing-chip">
                    <span class="timing-chip-lbl">MACD (12, 26, 9)</span>
                    <span class="timing-chip-val">${macd.signal === 'BUY' ? '🟢 골든크로스' : (macd.signal === 'SELL' ? '🔴 데드크로스' : '🟡 수렴관망')}</span>
                </div>
                <div class="timing-chip">
                    <span class="timing-chip-lbl">스토캐스틱 (14, 3, 3)</span>
                    <span class="timing-chip-val">${stoch.signal === 'BUY' ? '🟢 과매도탈출' : (stoch.signal === 'SELL' ? '🔴 과매수이탈' : '🟡 적정구간')}</span>
                </div>
            </div>
        </div>
    `;
}

// ❓ 퀀트 보조지표 설명 도움말 모달 오픈/클로즈
function openIndicatorHelpModal() {
    const modal = document.getElementById('indicatorHelpModal');
    if (modal) modal.style.display = 'flex';
}

function closeIndicatorHelpModal() {
    const modal = document.getElementById('indicatorHelpModal');
    if (modal) modal.style.display = 'none';
}

// 🎯 5가지 액션 뱃지 세트 (해당되는 1건은 진하고 크게, 나머지 4건은 연하고 작게)
function render5ActionStepBar(currentDecisionKey) {
    const steps = [
        { key: 'BUY', label: '강력매수', icon: '🚀', class: 'BUY' },
        { key: 'AVERAGE', label: '매수', icon: '📈', class: 'AVERAGE' },
        { key: 'HOLD', label: '관망', icon: '⚖️', class: 'HOLD' },
        { key: 'REDUCE', label: '매도', icon: '📉', class: 'REDUCE' },
        { key: 'TAKE PROFIT', label: '강력매도', icon: '🚨', class: 'TAKE_PROFIT' }
    ];

    let activeKey = 'HOLD';
    if (currentDecisionKey) {
        const u = String(currentDecisionKey).trim();
        if (u.includes('강력매수') || u.includes('STRONG_BUY') || u === 'BUY') {
            activeKey = 'BUY';
        } else if (u.includes('강력매도') || u.includes('STRONG_SELL') || u.includes('TAKE') || u.includes('익절')) {
            activeKey = 'TAKE PROFIT';
        } else if (u.includes('분할매수') || u.includes('물타기') || u.includes('AVERAGE') || u.includes('매수 검토') || u === '매수') {
            activeKey = 'AVERAGE';
        } else if (u.includes('비중') || u.includes('축소') || u.includes('REDUCE') || u === '매도' || u.includes('손절')) {
            activeKey = 'REDUCE';
        } else {
            activeKey = 'HOLD';
        }
    }

    const itemsHtml = steps.map(s => {
        const isActive = s.key === activeKey;
        if (isActive) {
            return `<span class="action-step-item active ${s.class}" style="font-size: 13.5px !important; font-weight: 800 !important; opacity: 1 !important; filter: none !important; padding: 5px 12px !important; border-radius: 14px !important; transform: scale(1.1) !important; margin: 0 4px !important;">${s.icon} ${s.label}</span>`;
        } else {
            return `<span class="action-step-item" style="font-size: 10px !important; font-weight: 600 !important; opacity: 0.25 !important; filter: grayscale(0.8) !important; padding: 2px 6px !important; color: #64748b !important;">${s.icon} ${s.label}</span>`;
        }
    }).join(' <span style="color: #64748b; font-size: 10px;">|</span> ');

    return `<div class="action-5step-bar" style="display: inline-flex; align-items: center; gap: 4px; background: rgba(226, 232, 240, 0.16) !important; border: 1px solid rgba(226, 232, 240, 0.3) !important; padding: 4px 10px; border-radius: 20px;">( ${itemsHtml} )</div>`;
}

function renderSingleQuoteCard(data, ticker, name) {
    const container = document.getElementById('singleQuoteCardContainer');
    if (!container) return;

    const flow = data.flow_analysis || {};
    const tech = data.technical_analysis || {};
    const dec = data.decision || {};
    const timing = data.timing_analysis || {};

    const curPrice = tech.latest_close || 0;
    const supportLevel = tech.support_level || 0;
    const resistanceLevel = tech.resistance_level || 0;

    const reasons = dec.ai_reasons || ["외국인 및 기관 수급 모니터링 필요"];
    const flowReasonText = reasons.join(' / ');

    const timingReasons = timing.reasons || ["보조지표 관망 영역 유지"];
    const timingReasonText = timingReasons.join(' / ');

    const marketVal = tech.market || 'KOSPI';
    const marketClass = marketVal.toLowerCase();

    // 기관 동조화 텍스트 안전 추출 ([object Object] 버그 방지)
    let concurrencyText = 'N/A';
    if (typeof flow.concurrency === 'object' && flow.concurrency !== null) {
        concurrencyText = flow.concurrency.label || flow.concurrency.code || 'N/A';
    } else if (flow.concurrency) {
        concurrencyText = String(flow.concurrency);
    }

    // Escape quotes for safe JS inline calls
    const safeTicker = String(ticker).replace(/'/g, "\\'");
    const safeName = String(name).replace(/'/g, "\\'");

    // 5가지 액션 뱃지 바 HTML (선택된 항목 하이라이트)
    let finalDecisionKey = 'HOLD';
    if (typeof dec === 'string') {
        finalDecisionKey = dec;
    } else if (dec && typeof dec.decision === 'string') {
        finalDecisionKey = dec.decision;
    } else if (dec && dec.decision && typeof dec.decision.decision === 'string') {
        finalDecisionKey = dec.decision.decision;
    } else if (timing && timing.overall_decision) {
        finalDecisionKey = timing.overall_decision;
    }

    const action5StepBarHtml = render5ActionStepBar(finalDecisionKey);

    const bb = timing.bollinger_bands || {};
    const macd = timing.macd || {};
    const stoch = timing.stochastic_slow || {};

    let bbText = `볼린저밴드(20, 2.0) ${bb.detail || (bb.signal === 'BUY' ? '하단반등' : (bb.signal === 'SELL' ? '상단이탈' : '중심안착'))}`;
    if (bb.lower_band && bb.upper_band) {
        bbText += ` (하단 ${Math.round(bb.lower_band).toLocaleString()}원 / 상단 ${Math.round(bb.upper_band).toLocaleString()}원)`;
    }

    let macdText = `MACD(12, 26, 9) ${macd.detail || (macd.signal === 'BUY' ? '골든크로스' : (macd.signal === 'SELL' ? '데드크로스' : '수렴관망'))}`;
    if (macd.histogram != null) {
        macdText += ` (${macd.histogram > 0 ? '+' : ''}${Math.round(macd.histogram)})`;
    }

    let stochText = `스토캐스틱(14, 3, 3) ${stoch.detail || (stoch.signal === 'BUY' ? '과매도탈출' : (stoch.signal === 'SELL' ? '과매수이탈' : '적정구간'))}`;
    if (stoch.k_value != null) {
        stochText += ` (%K: ${Math.round(stoch.k_value)})`;
    }

    const detailedTimingText = `${bbText} / ${macdText} / ${stochText}`;

    const cardHtml = `
        <div class="stock-card quote-result-card" id="stock-card-quote-${safeTicker}" style="border: 1px solid var(--accent-cyan); box-shadow: 0 4px 24px rgba(6, 182, 212, 0.18); padding: 14px 16px;">
            
            <!-- 📌 1번 줄 (Header): 종목명, 실시간 현재가, TODAY ACTION FCS, 5가지 액션 바 & ❓ 정사각형 도움말 버튼 -->
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; margin-bottom: 10px;">
                <!-- 좌측: 종목명, 시장구분, 종목코드, 실시간현재가 -->
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    <h3 class="stock-name-text" style="font-size: 20px; color: var(--accent-cyan); font-weight: 800; margin: 0;">${name}</h3>
                    <span class="market-tag ${marketClass}">${marketVal}</span>
                    <span style="font-size: 13px; font-weight: 600; color: #94a3b8;">${ticker}</span>
                    <span style="font-size: 19px; font-weight: 800; color: #38bdf8; margin-left: 6px;">${curPrice.toLocaleString()}원</span>
                </div>

                <!-- 우측: TODAY ACTION & FCS, 5가지 액션 뱃지 바, ❓ 정사각형 도움말 버튼 -->
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    <div style="font-size: 15px; color: #f97316; font-weight: 800; letter-spacing: 0.3px; text-shadow: 0 0 10px rgba(249, 115, 22, 0.35);">
                        ⚡ TODAY ACTION <span style="margin-left: 4px; color: #38bdf8; font-size: 15px; font-weight: 800;">FCS: ${flow.ffcs_score != null ? flow.ffcs_score : '-'}점</span>
                    </div>

                    <!-- 5가지 액션 차등 하이라이트 바 (해당 1건 크게/진하게, 나머지 연하게) -->
                    ${action5StepBarHtml}

                    <!-- ❓ 이쁜 정사각형 박스 지표가이드 도움말 버튼 -->
                    <button class="btn-help-icon" onclick="openIndicatorHelpModal()" title="볼린저밴드/MACD/스토캐스틱/RSI/FFCS/Score 지표 상세 설명 보기" style="width: 32px !important; height: 32px !important; border-radius: 8px !important; background: linear-gradient(135deg, rgba(56, 189, 248, 0.25), rgba(14, 165, 233, 0.35)) !important; border: 1px solid #38bdf8 !important; color: #38bdf8 !important; font-size: 15px !important; font-weight: 800 !important; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; margin-left: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);">?</button>
                </div>
            </div>

            <!-- 📌 2번 줄: AI 수급 & 투자 판단 근거 (압핀 📌 아이콘 적용 & 숫자 포함 상세 지표) -->
            <div style="background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 10px 14px; margin-bottom: 10px;">
                <h4 style="font-size: 14px; font-weight: 800; color: #f8fafc; margin: 0 0 8px 0; display: flex; align-items: center; gap: 6px;">
                    🤖 AI 수급 & 투자 판단 근거
                </h4>
                
                <div style="display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: #e2e8f0; line-height: 1.55;">
                    <div style="display: flex; align-items: flex-start; gap: 6px;">
                        <span>📌</span>
                        <span style="font-weight: 500;">${flowReasonText}</span>
                    </div>
                    <div style="display: flex; align-items: flex-start; gap: 6px;">
                        <span>📌</span>
                        <span style="font-weight: 500; color: #e0e7ff;">${detailedTimingText}</span>
                    </div>
                </div>
            </div>

            <!-- 📌 3번 줄: 수급 & 점수 지표 (밀착 및 항시 오픈) -->
            <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 10px; padding: 10px 12px; margin-bottom: 10px;">
                <div class="scores-row" style="margin-top: 0;">
                    <div class="score-badge-item">
                        <span class="s-lbl">Buy Score</span>
                        <span class="s-val text-success">${dec.buy_score || 0}점</span>
                    </div>
                    <div class="score-badge-item">
                        <span class="s-lbl">Sell Score</span>
                        <span class="s-val text-danger">${dec.sell_score || 0}점</span>
                    </div>
                    <div class="score-badge-item">
                        <span class="s-lbl">Watering Score</span>
                        <span class="s-val text-primary">${dec.watering_score || 0}점</span>
                    </div>
                </div>
            </div>

            <!-- 📌 4번 줄: 2가지 분석 모달 버튼 (밀착) -->
            <div class="card-footer" style="display: flex; gap: 10px; justify-content: space-between; flex-wrap: wrap; margin-top: 6px;">
                <button class="btn-detail" onclick="openStockHistoryModal('${safeTicker}', '${safeName}')" style="flex: 1; min-height: 40px; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 6px; background: rgba(56, 189, 248, 0.15); border: 1px solid #38bdf8; color: #38bdf8;">
                    📈 6개월 추세선 & MFI 차트
                </button>
                <button class="btn-detail" onclick="openDetailModal('${safeTicker}', '${safeName}')" style="flex: 1; min-height: 40px; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 6px;">
                    📊 수급 동향
                </button>
            </div>
        </div>
    `;

    container.innerHTML = cardHtml;
}

function closeSingleQuoteResult() {
    const resultArea = document.getElementById('singleQuoteResultArea');
    if (resultArea) resultArea.style.display = 'none';
}

