// HTML güvenliği: h`...` şablonları ${} içindeki her değeri otomatik kaçışlar.
// İç içe h`...` sonuçları (SafeHtml) ve bunların dizileri olduğu gibi geçer.
class SafeHtml {
    constructor(html) { this.html = html; }
    toString() { return this.html; }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, ch => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
}

function h(strings, ...values) {
    const render = v => {
        if (v === null || v === undefined || v === false) return "";
        if (v instanceof SafeHtml) return v.html;
        if (Array.isArray(v)) return v.map(render).join("");
        return escapeHtml(v);
    };
    return new SafeHtml(strings.reduce((out, str, i) => out + str + (i < values.length ? render(values[i]) : ""), ""));
}

// Application State
let currentAnnouncementId = null;
let currentResults = [];
let allCompanies = [];
let activeCompany = null;
let activeCategory = "all";
let isPdfViewOpen = false;
let activeMainTab = "gazette";
let activeCompanySummary = null;
let currentAiSummaryData = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    checkSystemStatus(true);
});

// Toast notification helper
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    
    let bg = "bg-slate-800 text-white";
    let icon = "fa-circle-info";
    if (type === "success") {
        bg = "bg-emerald-600 text-white";
        icon = "fa-circle-check";
    } else if (type === "error") {
        bg = "bg-red-600 text-white";
        icon = "fa-triangle-exclamation";
    } else if (type === "warning") {
        bg = "bg-amber-600 text-white";
        icon = "fa-circle-exclamation";
    }

    toast.className = `toast-item px-4 py-2.5 rounded-xl shadow-lg flex items-center space-x-2 text-xs font-medium ${bg}`;
    toast.innerHTML = h`<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Check Server and Login Status. firstRun: bilgiler hiç girilmemişse ayar penceresini kendiliğinden aç.
async function checkSystemStatus(firstRun = false) {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        
        const badge = document.getElementById("sessionStatusBadge");
        const dot = document.getElementById("sessionStatusDot");
        const text = document.getElementById("sessionStatusText");

        const aiLabel = data.has_gemini_key ? " • 🧠 AI Aktif" : "";
        if (data.is_logged_in) {
            dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
            text.innerText = `Oturum Açık (${data.email})${aiLabel}`;
            badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-700";
        } else if (data.has_credentials) {
            dot.className = "w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse";
            text.innerText = `Hesap Hazır (${data.email})${aiLabel}`;
            badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-blue-50 border border-blue-200 text-xs font-medium text-blue-700";
        } else {
            dot.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
            text.innerText = "Hesap bilgileri girilmedi";
            badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200 text-xs font-medium text-amber-700";
            if (firstRun) openSettingsModal();
        }
    } catch (e) {
        console.error("Status check failed:", e);
    }
}

// Handle Search Form Submission
async function handleSearch(event) {
    if (event) event.preventDefault();
    
    const unvan = document.getElementById("unvanInput").value.trim();
    const city = document.getElementById("cityInput").value.trim();
    const sicil_no = document.getElementById("sicilNoInput").value.trim();

    if (!unvan) {
        showToast("Lütfen şirket unvanını girin.", "warning");
        return;
    }

    startSearchWorkflow({
        unvan,
        city,
        sicil_no,
        is_demo: false
    });
}

// Handle Demo Search
function handleDemoSearch() {
    const defaultTitle = document.getElementById("unvanInput").value.trim() || "ANTİGRAVİTY BİLİŞİM VE TEKNOLOJİ ANONİM ŞİRKETİ";
    document.getElementById("unvanInput").value = defaultTitle;
    
    startSearchWorkflow({
        unvan: defaultTitle,
        city: "ANKARA",
        sicil_no: "458120",
        is_demo: true
    });
}

// Core Search Execution
async function startSearchWorkflow(payload) {
    const submitBtn = document.getElementById("searchSubmitBtn");
    const originalBtnHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = h`<i class="fa-solid fa-spinner animate-spin"></i> <span>Aranıyor...</span>`;

    showLoading("Gazete veritabanı taranıyor...");

    try {
        const response = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        let data;
        try {
            data = await response.json();
        } catch (parseErr) {
            hideLoading();
            showToast(`Sunucu yanıtı okunamadı (${response.status})`, "error");
            renderResults([]);
            return;
        }

        if (!response.ok || !data.success) {
            hideLoading();
            showToast(data.error || data.detail || "Arama sırasında bir sorun oluştu.", "error");
            renderResults([]);
            return;
        }

        currentResults = data.results || [];
        allCompanies = data.companies || [];

        // Check if multiple companies returned
        if (data.multiple_companies && allCompanies.length > 1) {
            hideLoading();
            showCompanySelectionModal(allCompanies);
            showToast(`Aramanızla eşleşen ${allCompanies.length} farklı şirket bulundu. Lütfen seçim yapın.`, "info");
        } else if (allCompanies.length > 0) {
            selectCompany(allCompanies[0].company_id);
            showToast(`${currentResults.length} adet gazete ilanı listelendi.`, "success");
        } else {
            hideLoading();
            renderResults([]);
            showToast("Eşleşen ilan bulunamadı.", "warning");
        }

    } catch (err) {
        console.error("Search error:", err);
        hideLoading();
        showToast("Bağlantı hatası oluştu.", "error");
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalBtnHtml;
    }
}

// Show Multiple Companies Selection Modal
function showCompanySelectionModal(companies) {
    const modal = document.getElementById("companySelectionModal");
    const container = document.getElementById("companyCardsContainer");
    container.innerHTML = "";

    companies.forEach(comp => {
        const card = document.createElement("div");
        card.className = "p-4 rounded-xl border border-slate-200 hover:border-blue-500 hover:bg-blue-50/40 transition cursor-pointer flex items-center justify-between group shadow-sm bg-white";
        card.onclick = () => selectCompany(comp.company_id);

        card.innerHTML = h`
            <div class="flex-1 pr-4">
                <span class="inline-block text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-600 mb-1">
                    ${comp.mudurluk || "Ticaret Sicili"} - Sicil No: ${comp.sicil_no || "-"}
                </span>
                <h4 class="text-xs font-bold text-slate-800 group-hover:text-blue-700 leading-snug">${comp.unvan}</h4>
                <div class="flex items-center gap-3 text-[11px] text-slate-500 mt-2">
                    <span><i class="fa-solid fa-list-check text-blue-500 mr-1"></i>${comp.announcements.length} İlan Bulundu</span>
                    <span><i class="fa-regular fa-clock text-slate-400 mr-1"></i>Son İlan: ${comp.latest_date || "-"}</span>
                </div>
            </div>
            <button class="px-3 py-1.5 rounded-lg bg-blue-600 group-hover:bg-blue-700 text-white text-xs font-semibold shrink-0 shadow-sm transition flex items-center space-x-1">
                <span>Bu Şirketi İncele</span>
                <i class="fa-solid fa-arrow-right text-[10px]"></i>
            </button>
        `;
        container.appendChild(card);
    });

    modal.classList.remove("hidden");
}

function showCompanySelectionView() {
    if (allCompanies.length > 1) {
        showCompanySelectionModal(allCompanies);
    }
}

// User Selects a Company
function selectCompany(companyId) {
    document.getElementById("companySelectionModal").classList.add("hidden");
    
    activeCompany = allCompanies.find(c => c.company_id === companyId);
    if (!activeCompany) return;

    // Show active company banner in sidebar
    const banner = document.getElementById("activeCompanyBar");
    banner.classList.remove("hidden");
    document.getElementById("activeCompanyName").innerText = activeCompany.unvan;
    
    // Switch company button visibility
    const switchBtn = document.getElementById("switchCompanyBtn");
    if (allCompanies.length > 1) {
        switchBtn.classList.remove("hidden");
    } else {
        switchBtn.classList.add("hidden");
    }

    // Reset category filter & render pills
    activeCategory = "all";
    const announcements = activeCompany.announcements || [];
    renderCategoryFilterPills(announcements);
    renderResults(announcements);

    // Reset summary cache for new company
    activeCompanySummary = null;

    // If currently on summary tab, load summary
    if (activeMainTab === "summary") {
        loadCompanySummary(companyId);
    }

    // Select first announcement in gazette tab
    if (announcements.length > 0) {
        selectAnnouncement(announcements[0].id);
    } else {
        hideLoading();
    }
}

// Category Classification Helper
function getAnnouncementCategory(tur) {
    const t = (tur || "").toUpperCase();
    if (t.includes("SERMAYE")) return "sermaye";
    if (t.includes("YÖNETİM") || t.includes("YONETIM") || t.includes("TEMSİL") || t.includes("TEMSIL") || t.includes("MÜDÜR") || t.includes("MUDUR") || t.includes("ORTAK")) return "yonetim";
    if (t.includes("GENEL KURUL")) return "genel_kurul";
    if (t.includes("TADİL") || t.includes("TADIL") || t.includes("SÖZLEŞME") || t.includes("SOZLESME") || t.includes("İÇ YÖNERGE") || t.includes("IC YONERGE")) return "tadil";
    if (t.includes("KURULUŞ") || t.includes("KURULUS")) return "kurulus";
    return "diger";
}

// Render Interactive Category Filter Pills
function renderCategoryFilterPills(announcements) {
    const filterBar = document.getElementById("categoryFilterBar");
    if (!announcements || announcements.length === 0) {
        filterBar.classList.add("hidden");
        return;
    }

    const counts = {
        all: announcements.length,
        sermaye: 0,
        yonetim: 0,
        genel_kurul: 0,
        tadil: 0,
        kurulus: 0,
        diger: 0
    };

    announcements.forEach(a => {
        const cat = getAnnouncementCategory(a.tur);
        if (counts[cat] !== undefined) counts[cat]++;
    });

    const pillConfigs = [
        { id: "all", label: "Tümü", icon: "fa-list", count: counts.all },
        { id: "sermaye", label: "Sermaye", icon: "fa-coins", count: counts.sermaye },
        { id: "yonetim", label: "Yönetim & Temsil", icon: "fa-users-gear", count: counts.yonetim },
        { id: "genel_kurul", label: "Genel Kurul", icon: "fa-building-columns", count: counts.genel_kurul },
        { id: "tadil", label: "Tadil / Sözleşme", icon: "fa-file-signature", count: counts.tadil },
        { id: "kurulus", label: "Kuruluş", icon: "fa-flag", count: counts.kurulus }
    ];

    let html = "";
    pillConfigs.forEach(p => {
        if (p.count > 0 || p.id === "all") {
            const isActive = activeCategory === p.id;
            const activeCls = isActive 
                ? "bg-blue-600 text-white font-bold shadow-xs border-blue-600" 
                : "bg-white text-slate-600 hover:bg-slate-100 border-slate-200 font-medium";
            html += h`
                <button type="button" onclick="setCategoryFilter('${p.id}')" 
                    class="category-pill px-2.5 py-1 rounded-lg border text-[11px] transition flex items-center space-x-1 shrink-0 ${activeCls} cursor-pointer">
                    <i class="fa-solid ${p.icon} text-[10px]"></i>
                    <span>${p.label}</span>
                    <span class="px-1.5 py-0.2 rounded-full ${isActive ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-500'} text-[10px] font-semibold">${p.count}</span>
                </button>
            `;
        }
    });

    filterBar.innerHTML = html;
    filterBar.classList.remove("hidden");
}

// User Clicks a Category Filter Pill
function setCategoryFilter(cat) {
    activeCategory = cat;
    if (!activeCompany) return;

    renderCategoryFilterPills(activeCompany.announcements || []);

    if (cat === "all") {
        renderResults(activeCompany.announcements || []);
    } else {
        const filtered = (activeCompany.announcements || []).filter(a => getAnnouncementCategory(a.tur) === cat);
        renderResults(filtered);
    }
}

// "24.10.2026" -> { day: "24", month: "Eki", year: "2026" } (biçim tanınmazsa ham değer)
const MONTHS_TR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
function splitDate(tarih) {
    const m = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/.exec((tarih || "").trim());
    if (!m || +m[2] < 1 || +m[2] > 12) return { day: tarih || "-", month: "", year: "" };
    return { day: m[1].padStart(2, "0"), month: MONTHS_TR[+m[2] - 1], year: m[3] };
}

// Render Announcements in Left Panel
function renderResults(results) {
    const container = document.getElementById("resultsList");
    const countBadge = document.getElementById("resultsCountBadge");
    countBadge.innerText = `${results.length} ilan`;

    if (!results || results.length === 0) {
        container.innerHTML = h`
            <div class="text-center py-16 px-4 text-slate-400">
                <i class="fa-regular fa-face-frown text-3xl mb-2 text-slate-300"></i>
                <p class="text-sm font-medium text-slate-500">Bu şirkete ait ilan bulunamadı</p>
                <p class="text-xs mt-0.5">Unvanı kısaltmayı veya müdürlüğü değiştirmeyi deneyin.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = "";
    results.forEach((item) => {
        const card = document.createElement("div");
        card.id = `card_${item.id}`;
        card.setAttribute("role", "button");
        card.tabIndex = 0;
        card.className = "result-card flex rounded-xl border border-slate-200 hover:border-blue-300 cursor-pointer bg-white";
        const open = () => {
            if (activeMainTab !== "gazette") {
                switchMainTab("gazette");
            }
            selectAnnouncement(item.id);
        };
        card.onclick = open;
        card.onkeydown = (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
        };

        const d = splitDate(item.tarih);
        card.innerHTML = h`
            <div class="date-block w-14 shrink-0 flex flex-col items-center justify-center py-2 bg-blue-50 text-blue-800 border-r border-dashed border-blue-200">
                <span class="text-xl font-bold leading-none">${d.day}</span>
                <span class="text-[11px] font-semibold mt-1">${d.month}</span>
                <span class="text-[10px] text-blue-600">${d.year}</span>
            </div>
            <div class="flex-1 min-w-0 p-3">
                <span class="inline-block text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-50 text-indigo-800 mb-1">
                    ${item.tur || "Ticaret sicil ilanı"}
                </span>
                <h4 class="text-[13px] font-semibold text-slate-900 line-clamp-2 leading-snug">${item.unvan}</h4>
                <div class="flex items-center gap-3 text-[11px] text-slate-500 mt-1.5">
                    <span><i class="fa-regular fa-file-lines text-slate-400 mr-1"></i>Sayı ${item.sayi || "-"}</span>
                    <span><i class="fa-regular fa-bookmark text-slate-400 mr-1"></i>Sayfa ${item.sayfa || "-"}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

// Select Announcement & Display Full-Page PDF Directly
async function selectAnnouncement(id) {
    currentAnnouncementId = id;

    // Reset AI summary box when switching announcements
    closeAiSummaryBox();

    document.querySelectorAll(".result-card").forEach(c => c.classList.remove("active"));
    const activeCard = document.getElementById(`card_${id}`);
    if (activeCard) activeCard.classList.add("active");

    const item = (activeCompany ? activeCompany.announcements : currentResults).find(r => r.id === id);
    if (!item) return;

    // Update Toolbar Details
    document.getElementById("previewToolbar").classList.remove("hidden");
    document.getElementById("toolbarTitle").innerText = item.unvan;
    document.getElementById("toolbarDate").innerHTML = h`<i class="fa-regular fa-calendar mr-1"></i> ${item.tarih || "-"}`;
    document.getElementById("toolbarNumber").innerHTML = h`<i class="fa-regular fa-file-lines mr-1"></i> Sayı: ${item.sayi || "-"}`;
    document.getElementById("toolbarPage").innerHTML = h`<i class="fa-regular fa-bookmark mr-1"></i> Sayfa: ${item.sayfa || "-"}`;
    document.getElementById("toolbarType").innerText = item.tur || "İlan";

    const pdfUrl = `/api/preview/pdf/${id}`;
    const openBtn = document.getElementById("openNewTabPdfBtn");
    if (openBtn) openBtn.href = pdfUrl;

    // Reset preview container and clear old iframe PDF immediately to prevent showing previous company
    const pdfIframe = document.getElementById("pdfIframe");
    if (pdfIframe) pdfIframe.src = "about:blank";
    document.getElementById("activePreviewContainer").classList.add("hidden");
    document.getElementById("noSelectionState").classList.add("hidden");
    document.getElementById("loadingState").classList.remove("hidden");
    document.getElementById("loadingText").innerText = "Gazete PDF sayfası yükleniyor...";

    try {
        const res = await fetch(`/api/announcement/${id}`);
        const data = await res.json();

        if (!res.ok || !data.success) {
            document.getElementById("loadingState").classList.add("hidden");
            document.getElementById("noSelectionState").classList.remove("hidden");
            showToast(data.error || "Gazete PDF belgesi getirilemedi.", "error");
            return;
        }

        pdfIframe.src = `${pdfUrl}?t=${Date.now()}`;

        document.getElementById("noSelectionState").classList.add("hidden");
        document.getElementById("loadingState").classList.add("hidden");
        document.getElementById("activePreviewContainer").classList.remove("hidden");

    } catch (e) {
        console.error("Announcement PDF load error:", e);
        document.getElementById("loadingState").classList.add("hidden");
        document.getElementById("noSelectionState").classList.remove("hidden");
        showToast("Gazete PDF belgesi yüklenirken hata oluştu.", "error");
    }
}

// Trigger On-Demand AI Announcement Summary
async function triggerCurrentAnnouncementAiSummary() {
    if (!currentAnnouncementId) {
        showToast("Lütfen önce incelenecek bir gazete ilanı seçin.", "warning");
        return;
    }

    const box = document.getElementById("aiSummaryBox");
    const content = document.getElementById("aiSummaryContent");
    const btnText = document.getElementById("aiSummaryBtnText");
    const cachedBadge = document.getElementById("aiSummaryCachedBadge");

    box.classList.remove("hidden");
    content.innerHTML = h`
        <div class="py-6 text-center text-indigo-600 flex flex-col items-center justify-center space-y-2">
            <i class="fa-solid fa-spinner animate-spin text-xl"></i>
            <span class="text-xs font-semibold">Google Gemini çok modlu yapay zeka ile gazete kararını çözümlüyor...</span>
            <span class="text-[10px] text-slate-400">PDF üzerindeki tescilli sermaye, yönetim ve ortaklık hükümleri taranıyor</span>
        </div>
    `;
    btnText.innerText = "İnceleniyor...";

    try {
        const res = await fetch(`/api/announcement/${currentAnnouncementId}/ai-summary`, { method: "POST" });
        const resData = await res.json();

        btnText.innerText = "Bu Kararı Özetle (AI)";

        if (!res.ok || !resData.success) {
            content.innerHTML = h`
                <div class="p-3.5 bg-amber-50 text-amber-900 rounded-xl border border-amber-200 text-xs space-y-2">
                    <div class="flex items-start space-x-2">
                        <i class="fa-solid fa-circle-exclamation text-amber-600 mt-0.5"></i>
                        <div>
                            <span class="font-bold block">Yapay Zeka Analizi Hazır Değil</span>
                            <p class="text-[11px] text-amber-800 mt-0.5">${resData.error || "Karar özeti alınamadı."}</p>
                        </div>
                    </div>
                    ${resData.needs_key ? h`
                        <div class="pt-1">
                            <button onclick="openSettingsModal()" class="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs shadow-xs transition flex items-center space-x-1.5">
                                <i class="fa-solid fa-key text-[10px]"></i>
                                <span>Gemini API Anahtarını Tanımla</span>
                            </button>
                        </div>
                    ` : ""}
                </div>
            `;
            return;
        }

        const data = resData.data;
        currentAiSummaryData = data;

        if (resData.cached) {
            cachedBadge.classList.remove("hidden");
        } else {
            cachedBadge.classList.add("hidden");
        }

        renderAiSummaryContent(data);

    } catch (e) {
        console.error("AI Summary error:", e);
        btnText.innerText = "Bu Kararı Özetle (AI)";
        content.innerHTML = h`<div class="p-3 bg-red-50 text-red-700 rounded-xl border border-red-200 text-xs">Sunucu ile bağlantı kurulamadı.</div>`;
    }
}

function renderAiSummaryContent(data) {
    const content = document.getElementById("aiSummaryContent");
    
    let html = `
        <!-- Narrative Executive Summary -->
        <div class="p-3.5 bg-indigo-50/80 rounded-xl border border-indigo-100 text-indigo-950 font-medium text-xs leading-relaxed">
            <i class="fa-solid fa-quote-left text-indigo-400 mr-1.5"></i>
            ${data.yonetici_ozeti || "Karar özeti oluşturulamadı."}
        </div>
    `;

    // Capital row if present
    if (data.sermaye_degisimi && (data.sermaye_degisimi.yeni_sermaye !== "-" || data.sermaye_degisimi.artis_tutari !== "-")) {
        const s = data.sermaye_degisimi;
        html += h`
            <div class="p-3 bg-emerald-50/80 rounded-xl border border-emerald-100 text-xs flex items-center justify-between">
                <div>
                    <span class="font-bold text-emerald-950 flex items-center gap-1.5"><i class="fa-solid fa-coins text-emerald-600"></i>Sermaye Değişimi:</span>
                    <span class="text-slate-700 text-[11px] mt-0.5 block">${s.eski_sermaye !== '-' ? h`${s.eski_sermaye} &rarr; ` : ''}<strong>${s.yeni_sermaye}</strong></span>
                    ${s.karsilama_sekli && s.karsilama_sekli !== '-' ? h`<span class="text-[10px] text-emerald-800 block mt-0.5">${s.karsilama_sekli}</span>` : ''}
                </div>
                ${s.artis_tutari && s.artis_tutari !== '-' ? h`<span class="px-2.5 py-1 rounded-full bg-emerald-200 text-emerald-900 font-extrabold text-[11px]">${s.artis_tutari}</span>` : ''}
            </div>
        `;
    }

    // Officers if present
    if (data.yonetim_ve_yetkililer) {
        const y = data.yonetim_ve_yetkililer;
        if ((y.goreve_secilenler && y.goreve_secilenler.length > 0) || (y.gorevden_ayrilanlar && y.gorevden_ayrilanlar.length > 0)) {
            html += h`
                <div class="p-3 bg-blue-50/80 rounded-xl border border-blue-100 text-xs space-y-1.5">
                    <span class="font-bold text-blue-950 flex items-center gap-1.5"><i class="fa-solid fa-users-gear text-blue-600"></i>Yönetim & Temsil Kararları:</span>
                    ${(y.goreve_secilenler || []).map(g => h`<div class="text-blue-950 text-[11px] flex items-center gap-1.5"><i class="fa-solid fa-user-plus text-emerald-600 text-[10px]"></i> <span>${g}</span></div>`)}
                    ${(y.gorevden_ayrilanlar || []).map(a => h`<div class="text-red-950 text-[11px] flex items-center gap-1.5"><i class="fa-solid fa-user-minus text-red-600 text-[10px]"></i> <span>${a}</span></div>`)}
                </div>
            `;
        }
    }

    // Share transfers if present
    if (data.ortaklar_ve_pay_devirleri && data.ortaklar_ve_pay_devirleri.length > 0) {
        html += h`
            <div class="p-3 bg-purple-50/80 rounded-xl border border-purple-100 text-xs space-y-1">
                <span class="font-bold text-purple-950 flex items-center gap-1.5"><i class="fa-solid fa-handshake text-purple-600"></i>Ortaklık & Pay Devirleri:</span>
                ${data.ortaklar_ve_pay_devirleri.map(p => h`<div class="text-purple-950 text-[11px]"><i class="fa-solid fa-arrow-right text-purple-500 text-[9px] mr-1"></i><strong>${p.islem}:</strong> ${p.detay}</div>`)}
            </div>
        `;
    }

    // New address
    if (data.yeni_adres_veya_merkez && data.yeni_adres_veya_merkez !== "-") {
        html += h`
            <div class="p-2.5 bg-slate-50 rounded-xl border border-slate-200 text-xs text-slate-700">
                <i class="fa-solid fa-location-dot text-red-500 mr-1.5"></i><strong>Tescil Edilen Adres:</strong> ${data.yeni_adres_veya_merkez}
            </div>
        `;
    }

    // Important notes
    if (data.onemli_notlar && data.onemli_notlar.length > 0) {
        html += h`
            <div class="pt-1 flex flex-wrap gap-1.5">
                ${data.onemli_notlar.map(n => h`<span class="px-2 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]"><i class="fa-solid fa-tag text-[8px] mr-1 text-slate-400"></i>${n}</span>`)}
            </div>
        `;
    }

    content.innerHTML = html;
}

function closeAiSummaryBox() {
    const box = document.getElementById("aiSummaryBox");
    if (box) box.classList.add("hidden");
}

function copyAiSummary() {
    if (!currentAiSummaryData) return;
    const txt = `${currentAiSummaryData.karar_turu}\n\nÖzet: ${currentAiSummaryData.yonetici_ozeti}`;
    navigator.clipboard.writeText(txt).then(() => {
        showToast("Karar özeti panoya kopyalandı!", "success");
    });
}

// Switch Main Tab (Gazette vs. Decision Summary)
function switchMainTab(tab) {
    activeMainTab = tab;
    const gazetteBtn = document.getElementById("tabGazetteBtn");
    const summaryBtn = document.getElementById("tabSummaryBtn");
    const gazetteContainer = document.getElementById("gazetteViewContainer");
    const summaryContainer = document.getElementById("summaryViewContainer");
    const gazetteActions = document.getElementById("gazetteActions");

    if (tab === "gazette") {
        gazetteBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center space-x-1.5 bg-blue-600 text-white shadow-sm";
        summaryBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center space-x-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700";
        gazetteContainer.classList.remove("hidden");
        summaryContainer.classList.add("hidden");
        gazetteActions.classList.remove("hidden");
    } else {
        summaryBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center space-x-1.5 bg-indigo-600 text-white shadow-sm";
        gazetteBtn.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center space-x-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700";
        gazetteContainer.classList.add("hidden");
        summaryContainer.classList.remove("hidden");
        gazetteActions.classList.add("hidden");

        if (activeCompany) {
            loadCompanySummary(activeCompany.company_id);
        } else {
            showToast("Lütfen önce sol panelden bir şirket aratın.", "warning");
        }
    }
}

// Fetch & Render Smart Decision Summary
async function loadCompanySummary(companyId) {
    if (activeCompanySummary && activeCompanySummary.company_id === companyId) {
        renderSummaryDashboard(activeCompanySummary.summary);
        return;
    }

    // Set initial loading state
    document.getElementById("sumAdres").innerText = "Gazete kararları taranıyor...";
    document.getElementById("sumQuickPartners").innerHTML = h`
        <span class="text-xs text-indigo-600 font-semibold flex items-center gap-1.5 py-0.5">
            <i class="fa-solid fa-spinner animate-spin text-[11px]"></i>
            <span>Yapay zeka ile ortaklık yapısı ve şirket künyesi çıkarılıyor...</span>
        </span>
    `;

    try {
        const res = await fetch(`/api/company/summary/${companyId}`);
        const data = await res.json();

        if (res.ok && data.success) {
            activeCompanySummary = data;
            renderSummaryDashboard(data.summary);
        } else {
            showToast(data.error || "Firma detayları alınamadı.", "error");
        }
    } catch (e) {
        console.error("Summary error:", e);
        showToast("Özet yüklenirken hata oluştu.", "error");
    }
}

// Render Summary Dashboard Elements
function renderSummaryDashboard(sum) {
    document.getElementById("sumUnvan").innerText = sum.unvan || "-";
    document.getElementById("sumSicilNo").innerText = sum.sicil_no || "-";
    document.getElementById("sumMudurluk").innerText = sum.mudurluk || "-";
    document.getElementById("sumMersis").innerText = sum.mersis || "-";
    document.getElementById("sumKurulus").innerText = sum.kurulus_tarihi || "-";
    document.getElementById("sumAdres").innerText = sum.guncel_adres || "-";

    // Quick Partners Summary
    const quickPartners = document.getElementById("sumQuickPartners");
    if (sum.ortaklar && sum.ortaklar.length > 0) {
        quickPartners.innerHTML = sum.ortaklar.slice(0, 4).map(o => h`
            <span class="px-2 py-0.5 rounded-md bg-indigo-100/80 text-indigo-800 text-[11px] font-bold flex items-center gap-1 shadow-xs">
                <i class="fa-solid fa-user-tie text-[9px] text-indigo-600"></i>
                <span>${o.ad}</span>
                <span class="font-normal text-[10px] text-indigo-600">(${o.pay})</span>
            </span>
        `).join("");
    } else if (sum.tek_pay_sahibi) {
        quickPartners.innerHTML = h`
            <span class="px-2.5 py-0.5 rounded-md bg-amber-50 border border-amber-200 text-amber-900 text-[11px] font-bold flex items-center gap-1.5">
                <i class="fa-solid fa-crown text-[10px] text-amber-500"></i>
                <span>${sum.tek_pay_sahibi}</span>
                <span class="font-medium text-[10px] text-amber-700">(Tek Pay Sahibi)</span>
            </span>
        `;
    } else {
        quickPartners.innerHTML = h`<span class="text-xs text-slate-500 font-medium">Ticaret sicil dosyasında kayıtlı ortak ve temsilciler</span>`;
    }

    // Detailed Partners List Card
    const partnersList = document.getElementById("sumPartnersList");
    let partnersHtml = "";
    if (sum.ortaklar && sum.ortaklar.length > 0) {
        partnersHtml += sum.ortaklar.map(o => h`
            <div class="p-2.5 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                <div>
                    <span class="text-xs font-bold text-slate-800 block">${o.ad}</span>
                    <span class="text-[10px] text-slate-500">${o.durum || "Tescilli Ortak"}</span>
                </div>
                <span class="px-2 py-0.5 rounded-md bg-purple-100 text-purple-800 text-[10px] font-bold">${o.pay}</span>
            </div>
        `).join("");
    }

    if (sum.pay_devirleri && sum.pay_devirleri.length > 0) {
        partnersHtml += h`
            <div class="pt-2 border-t border-slate-100">
                <span class="text-[10px] font-bold text-purple-700 block mb-1.5">Geçmiş Pay Devirleri</span>
                <div class="space-y-1.5">
                    ${sum.pay_devirleri.map(d => h`
                        <div class="p-2 rounded-lg bg-purple-50/60 border border-purple-100 text-[11px]">
                            <div class="flex items-center justify-between font-semibold text-purple-900">
                                <span>${d.devreden} <i class="fa-solid fa-arrow-right text-[9px] mx-1 text-purple-500"></i> ${d.devralan}</span>
                                <span class="text-[10px] text-purple-600">${d.tarih}</span>
                            </div>
                            <span class="text-[10px] text-slate-500 block mt-0.5">${d.pay} tescil edildi (Sayı: ${d.sayi})</span>
                        </div>
                    `)}
                </div>
            </div>
        `;
    }

    if (!partnersHtml) {
        partnersHtml = `<p class="text-xs text-slate-400 py-3 text-center">Ortaklık veya pay kaydı tespit edilemedi.</p>`;
    }
    partnersList.innerHTML = partnersHtml;

    // Capital List
    const capList = document.getElementById("sumCapitalList");
    if (sum.capital_history && sum.capital_history.length > 0) {
        capList.innerHTML = sum.capital_history.map(c => h`
            <div class="p-3 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                <div>
                    <div class="flex items-center space-x-2">
                        <span class="text-xs font-bold text-slate-800">${c.new}</span>
                        ${c.old !== "-" ? h`<span class="text-[11px] text-slate-400 line-through">${c.old}</span>` : ""}
                    </div>
                    <span class="text-[10px] text-slate-500 mt-0.5 block">Tescil: ${c.tarih} (Sayı: ${c.sayi})</span>
                </div>
                ${c.increase ? h`<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-bold">${c.increase}</span>` : ""}
            </div>
        `).join("");
    } else {
        capList.innerHTML = h`<p class="text-xs text-slate-400 py-3 text-center">Sermaye artırımı kaydı tespit edilemedi.</p>`;
    }

    // Management Changes List
    const mgmtList = document.getElementById("sumManagementList");
    if (sum.management_changes && sum.management_changes.length > 0) {
        mgmtList.innerHTML = sum.management_changes.map(m => h`
            <div class="p-3 rounded-xl bg-slate-50 border border-slate-100 space-y-1.5">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-bold text-slate-800">${m.tur}</span>
                    <span class="text-[10px] text-slate-400">${m.tarih}</span>
                </div>
                ${m.appointed && m.appointed.length > 0 ? h`
                    <div class="flex flex-wrap gap-1 pt-1">
                        ${m.appointed.map(a => h`<span class="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 text-[10px] font-semibold flex items-center gap-1"><i class="fa-solid fa-user-plus text-[9px]"></i> ${a}</span>`)}
                    </div>
                ` : ""}
                ${m.resigned && m.resigned.length > 0 ? h`
                    <div class="flex flex-wrap gap-1 pt-1">
                        ${m.resigned.map(r => h`<span class="px-2 py-0.5 rounded bg-red-50 text-red-700 text-[10px] font-semibold flex items-center gap-1"><i class="fa-solid fa-user-minus text-[9px]"></i> ${r}</span>`)}
                    </div>
                ` : ""}
                ${(!m.appointed || m.appointed.length === 0) && (!m.resigned || m.resigned.length === 0) ? h`
                    <p class="text-[11px] text-slate-500">Olağan/Olağanüstü genel kurul kararı tescil edilmiştir.</p>
                ` : ""}
            </div>
        `).join("");
    } else {
        mgmtList.innerHTML = h`<p class="text-xs text-slate-400 py-3 text-center">Yönetim değişikliği kaydı tespit edilemedi.</p>`;
    }

    // Timeline List
    const timeList = document.getElementById("sumTimelineList");
    if (sum.timeline && sum.timeline.length > 0) {
        timeList.innerHTML = sum.timeline.map((t, i) => h`
            <div class="relative pb-3">
                <span class="absolute -left-[23px] top-1 w-3 h-3 rounded-full bg-blue-600 border-2 border-white shadow-sm"></span>
                <div class="p-3.5 rounded-xl bg-slate-50 hover:bg-slate-100/80 border border-slate-100 transition flex items-center justify-between">
                    <div class="flex-1 pr-3">
                        <div class="flex items-center space-x-2">
                            <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-100 text-blue-800">${t.tur}</span>
                            <span class="text-[11px] font-semibold text-slate-500">${t.tarih}</span>
                            <span class="text-[10px] text-slate-400">Sayı: ${t.sayi} - Sayfa: ${t.sayfa}</span>
                        </div>
                        <p class="text-xs text-slate-700 mt-1 font-medium">${t.summary || t.tur}</p>
                    </div>
                    <div class="flex items-center space-x-1.5 shrink-0">
                        <button data-ann="${t.announcement_id}" onclick="viewAnnouncementFromSummary(this.dataset.ann, true)" 
                            class="px-2.5 py-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-semibold transition flex items-center space-x-1 cursor-pointer">
                            <i class="fa-solid fa-wand-magic-sparkles text-[10px]"></i>
                            <span>AI Özeti</span>
                        </button>
                        <button data-ann="${t.announcement_id}" onclick="viewAnnouncementFromSummary(this.dataset.ann, false)" 
                            class="px-2.5 py-1.5 rounded-lg bg-white border border-slate-200 hover:border-blue-400 text-blue-600 text-xs font-semibold shadow-xs transition flex items-center space-x-1 cursor-pointer">
                            <i class="fa-solid fa-file-pdf"></i>
                            <span>Gazete PDF</span>
                        </button>
                    </div>
                </div>
            </div>
        `).join("");
    } else {
        timeList.innerHTML = h`<p class="text-xs text-slate-400 py-3">Karar zaman çizelgesi bulunamadı.</p>`;
    }
}

// Navigate from Summary Timeline directly to Full Gazette PDF (optional trigger AI)
function viewAnnouncementFromSummary(annId, triggerAi = false) {
    switchMainTab("gazette");
    selectAnnouncement(annId);
    if (triggerAi) {
        setTimeout(() => {
            triggerCurrentAnnouncementAiSummary();
        }, 500);
    }
}

// Loading States
function showLoading(text = "Lütfen bekleyin...") {
    document.getElementById("noSelectionState").classList.add("hidden");
    document.getElementById("activePreviewContainer").classList.add("hidden");
    const loadingState = document.getElementById("loadingState");
    loadingState.classList.remove("hidden");
    document.getElementById("loadingText").innerText = text;
}

function hideLoading() {
    document.getElementById("loadingState").classList.add("hidden");
    if (!currentAnnouncementId) {
        document.getElementById("noSelectionState").classList.remove("hidden");
    } else {
        document.getElementById("activePreviewContainer").classList.remove("hidden");
    }
}

// Downloads
function downloadCurrentPdf() {
    if (!currentAnnouncementId) return;
    window.location.href = `/api/download/pdf/${currentAnnouncementId}`;
}

// Settings Modal
function openSettingsModal() {
    document.getElementById("settingsModal").classList.remove("hidden");
}

function closeSettingsModal() {
    document.getElementById("settingsModal").classList.add("hidden");
}

async function handleSaveSettings(event) {
    event.preventDefault();
    const email = document.getElementById("settingsEmail").value.trim();
    const password = document.getElementById("settingsPassword").value.trim();
    const geminiInput = document.getElementById("settingsGeminiKey");
    const gemini_api_key = geminiInput ? geminiInput.value.trim() : "";

    if (!email || !password) {
        showToast("Lütfen e-posta ve şifrenizi girin.", "warning");
        return;
    }

    const saveBtn = document.getElementById("saveSettingsBtn");
    saveBtn.disabled = true;
    saveBtn.innerText = "Kaydediliyor...";

    try {
        const payload = { email, password };
        if (gemini_api_key) {
            payload.gemini_api_key = gemini_api_key;
        }

        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (res.ok && data.success) {
            showToast(data.secure_storage === false ? "Kaydedildi (kimlik kasası yok, .env dosyasına yazıldı)." : "Bilgileriniz bilgisayarınızın kimlik kasasına kaydedildi.", "success");
            closeSettingsModal();
            checkSystemStatus();
        } else {
            showToast(data.detail || "Kaydedilemedi.", "error");
        }
    } catch (e) {
        showToast("Sunucuyla bağlantı kurulamadı.", "error");
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = "Kaydet";
    }
}
