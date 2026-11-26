/**
 * Product Catalog - Public & Authenticated Viewer Client Layer
 * Strictly zero internal admin/editor API endpoints shipped in this bundle.
 * Enforces CSRF token attachment, CSP compliance (no inline handlers), and server-authoritative pricing display.
 */

window.CatalogApp = {
    products: [],
    filteredProducts: [],
    currentView: "grid",
    activeTab: "catalogExplorer",
    role: document.body.dataset.role || "guest",
    authenticated: document.body.dataset.authenticated === "true",
    selectedCheckoutProduct: null,
    selectedPaymentMethod: "Credit Card",
    pendingDeleteId: null
};

// ==============================================================================
// SECURITY HELPERS (CSRF, Escaping, Authenticated Gateway Calls)
// ==============================================================================

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
}

function setCsrfToken(token) {
    if (!token) return;
    let meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.setAttribute("content", token);
}

async function secureFetch(url, options = {}) {
    const opts = {
        credentials: "same-origin",
        ...options,
        headers: { ...(options.headers || {}) }
    };
    const method = (opts.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
        opts.headers["X-CSRF-Token"] = getCsrfToken();
    }
    const res = await fetch(url, opts);
    return res;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

const DEFAULT_PLACEHOLDER_SVG =
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="#0f172a"/><rect x="20" y="20" width="360" height="260" rx="16" fill="#1e293b" stroke="#334155" stroke-width="2"/><text x="200" y="145" font-family="sans-serif" font-size="18" font-weight="700" fill="#94a3b8" text-anchor="middle">PRODUCT CATALOG</text><text x="200" y="175" font-family="sans-serif" font-size="13" fill="#64748b" text-anchor="middle">Text-Generated Entry</text></svg>'
    );

function sanitizeImageUrl(url) {
    if (!url || typeof url !== "string") return "";
    if (url.startsWith("/static/uploads/")) return url;
    return "";
}

function pictureMarkup(imagePath, altText, className = "") {
    const safeJpg = sanitizeImageUrl(imagePath);
    const clsAttr = className ? `class="${escapeHtml(className)}"` : "";
    if (!safeJpg) {
        return `<img src="${DEFAULT_PLACEHOLDER_SVG}" ${clsAttr} loading="lazy" alt="${escapeHtml(altText)}">`;
    }
    const webpPath = safeJpg.replace(/\.(png|jpg|jpeg)$/i, ".webp");
    return `
        <picture>
            <source srcset="${escapeHtml(webpPath)}" type="image/webp">
            <img src="${escapeHtml(safeJpg)}" ${clsAttr} loading="lazy" alt="${escapeHtml(altText)}">
        </picture>
    `;
}

// ==============================================================================
// INITIALIZATION & EVENT BINDING
// ==============================================================================

document.addEventListener("DOMContentLoaded", () => {
    bindStaticControls();
    bindDelegatedHandlers();
    handleUrlParameters();
    loadCatalogData();
    if (window.CatalogApp.authenticated) {
        loadUserOrders();
    }
});

function handleUrlParameters() {
    const params = new URLSearchParams(window.location.search);
    const initialSearch = params.get("search");
    if (initialSearch) {
        const searchInput = document.getElementById("catalogSearchInput");
        if (searchInput) searchInput.value = initialSearch;
    }

    const hash = window.location.hash.replace("#", "");
    if (hash && document.getElementById(hash)) {
        switchTab(hash);
    } else if (hash === "contact") {
        switchTab("contactSection");
    }
}

function bindStaticControls() {
    // Mobile drawer
    const mobileBtn = document.getElementById("mobileMenuBtn");
    const mobileClose = document.getElementById("mobileDrawerCloseBtn");
    const mobileBackdrop = document.getElementById("mobileNavBackdrop");

    if (mobileBtn) mobileBtn.addEventListener("click", openMobileDrawer);
    if (mobileClose) mobileClose.addEventListener("click", closeMobileDrawer);
    if (mobileBackdrop) mobileBackdrop.addEventListener("click", closeMobileDrawer);

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeMobileDrawer();
            closeAllModals();
        }
    });

    // Tab navigation links
    document.querySelectorAll("[data-tab]").forEach(el => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            const target = el.getAttribute("data-tab");
            if (target) {
                switchTab(target);
                closeMobileDrawer();
            }
        });
    });

    // Security modal trigger
    document.querySelectorAll('[data-action="open-security"]').forEach(el => {
        el.addEventListener("click", () => {
            const modal = document.getElementById("securityModal");
            if (modal) modal.classList.add("active");
        });
    });

    // Auth modal triggers
    document.querySelectorAll('[data-action="open-auth"]').forEach(el => {
        el.addEventListener("click", () => {
            const mode = el.getAttribute("data-mode") || "login";
            closeMobileDrawer();
            openAuthModal(mode);
        });
    });

    document.querySelectorAll('[data-action="logout"]').forEach(el => {
        el.addEventListener("click", confirmLogout);
    });

    document.querySelectorAll('[data-action="verify-email-modal"]').forEach(el => {
        el.addEventListener("click", () => openAuthModal("verify"));
    });

    document.querySelectorAll('[data-action="resend-verification"]').forEach(el => {
        el.addEventListener("click", resendVerificationCode);
    });

    // Modal close buttons
    document.querySelectorAll("[data-close-modal]").forEach(btn => {
        btn.addEventListener("click", () => {
            const modalId = btn.getAttribute("data-close-modal");
            const m = document.getElementById(modalId);
            if (m) m.classList.remove("active");
        });
    });

    // Auth forms
    const loginForm = document.getElementById("loginForm");
    if (loginForm) loginForm.addEventListener("submit", handleLoginSubmit);

    const regForm = document.getElementById("registerForm");
    if (regForm) regForm.addEventListener("submit", handleRegisterSubmit);

    const verifyForm = document.getElementById("verifyEmailForm");
    if (verifyForm) verifyForm.addEventListener("submit", handleVerifyEmailSubmit);

    document.querySelectorAll("[data-switch-auth]").forEach(link => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            toggleAuthForm(link.getAttribute("data-switch-auth"));
        });
    });

    // Catalog toolbar filters & view toggles
    const searchInput = document.getElementById("catalogSearchInput");
    const catSelect = document.getElementById("categoryFilter");
    const brandSelect = document.getElementById("brandFilter");
    const sortSelect = document.getElementById("catalogSortSelect");
    const reloadBtn = document.getElementById("reloadCatalogBtn");

    if (searchInput) {
        searchInput.addEventListener("input", debounce(() => {
            applyFilters();
        }, 250));
    }
    if (catSelect) catSelect.addEventListener("change", applyFilters);
    if (brandSelect) brandSelect.addEventListener("change", applyFilters);
    if (sortSelect) sortSelect.addEventListener("change", applyFilters);
    if (reloadBtn) reloadBtn.addEventListener("click", loadCatalogData);

    const gridBtn = document.getElementById("viewGridBtn");
    const tableBtn = document.getElementById("viewTableBtn");
    if (gridBtn && tableBtn) {
        gridBtn.addEventListener("click", () => {
            window.CatalogApp.currentView = "grid";
            gridBtn.classList.add("active");
            tableBtn.classList.remove("active");
            renderCatalog();
        });
        tableBtn.addEventListener("click", () => {
            window.CatalogApp.currentView = "table";
            tableBtn.classList.add("active");
            gridBtn.classList.remove("active");
            renderCatalog();
        });
    }

    // Checkout form & controls
    const checkoutSelect = document.getElementById("checkoutProductSelect");
    const checkoutQty = document.getElementById("checkoutQuantity");
    const checkoutForm = document.getElementById("checkoutForm");
    const modalCheckoutBtn = document.getElementById("modalCheckoutBtn");
    const printReceiptBtn = document.getElementById("printReceiptBtn");

    if (checkoutSelect) checkoutSelect.addEventListener("change", updateCheckoutProductSummary);
    if (checkoutQty) checkoutQty.addEventListener("input", updateCheckoutProductSummary);
    if (checkoutForm) checkoutForm.addEventListener("submit", handleCheckoutSubmit);
    if (printReceiptBtn) printReceiptBtn.addEventListener("click", () => window.print());
    if (modalCheckoutBtn) {
        modalCheckoutBtn.addEventListener("click", () => {
            const vm = document.getElementById("productViewModal");
            if (vm) vm.classList.remove("active");
            switchTab("checkoutSection");
        });
    }

    document.querySelectorAll("[data-payment-method]").forEach(card => {
        card.addEventListener("click", () => {
            const method = card.getAttribute("data-payment-method");
            window.CatalogApp.selectedPaymentMethod = method;
            document.querySelectorAll(".payment-option-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            const cf = document.getElementById("cardPaymentFields");
            if (cf) cf.style.display = method === "Credit Card" ? "block" : "none";
        });
    });

    // Contact inquiry form
    const contactForm = document.getElementById("contactForm");
    if (contactForm) contactForm.addEventListener("submit", handleContactSubmit);
}

function bindDelegatedHandlers() {
    document.addEventListener("click", (e) => {
        const target = e.target.closest("[data-item-action]");
        if (!target) return;
        const action = target.getAttribute("data-item-action");
        const prodId = parseInt(target.getAttribute("data-product-id"), 10);
        if (!prodId) return;

        if (action === "view") {
            openProductModal(prodId);
        } else if (action === "order") {
            const prod = window.CatalogApp.products.find(p => p.id === prodId);
            if (prod) window.CatalogApp.selectedCheckoutProduct = prod;
            switchTab("checkoutSection");
        } else if (action === "edit" && typeof window.openEditorModalForId === "function") {
            window.openEditorModalForId(prodId);
        } else if (action === "delete" && typeof window.openDeleteModalForId === "function") {
            const pname = target.getAttribute("data-product-name") || "this product";
            window.openDeleteModalForId(prodId, pname);
        }
    });
}

// ==============================================================================
// MOBILE DRAWER & SECTION ROUTING
// ==============================================================================

function openMobileDrawer() {
    const drawer = document.getElementById("mobileNavDrawer");
    const backdrop = document.getElementById("mobileNavBackdrop");
    if (drawer) drawer.classList.add("open");
    if (backdrop) backdrop.classList.add("open");
    document.body.style.overflow = "hidden";
}

function closeMobileDrawer() {
    const drawer = document.getElementById("mobileNavDrawer");
    const backdrop = document.getElementById("mobileNavBackdrop");
    if (drawer) drawer.classList.remove("open");
    if (backdrop) backdrop.classList.remove("open");
    document.body.style.overflow = "";
}

function switchTab(tabId) {
    const sec = document.getElementById(tabId);
    if (!sec) return;

    window.CatalogApp.activeTab = tabId;
    document.querySelectorAll("[data-tab]").forEach(el => {
        el.classList.toggle("active", el.getAttribute("data-tab") === tabId);
    });
    document.querySelectorAll(".content-section").forEach(el => {
        el.classList.toggle("active", el.id === tabId);
    });

    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tabId === "checkoutSection") {
        populateCheckoutDropdown();
        if (window.CatalogApp.authenticated) loadUserOrders();
    } else if (tabId === "settingsSection" && typeof window.refreshAdminPanel === "function") {
        window.refreshAdminPanel();
    }
}

function closeAllModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => m.classList.remove("active"));
}

// ==============================================================================
// AUTHENTICATION HANDLERS
// ==============================================================================

function openAuthModal(mode = "login") {
    const modal = document.getElementById("authModal");
    if (!modal) return;
    toggleAuthForm(mode);
    modal.classList.add("active");
}

function toggleAuthForm(formName) {
    const loginForm = document.getElementById("loginForm");
    const regForm = document.getElementById("registerForm");
    const verifyForm = document.getElementById("verifyEmailForm");
    const title = document.getElementById("authModalTitle");

    if (loginForm) loginForm.style.display = "none";
    if (regForm) regForm.style.display = "none";
    if (verifyForm) verifyForm.style.display = "none";

    if (formName === "login") {
        if (loginForm) loginForm.style.display = "block";
        if (title) title.textContent = "Sign In to Product Catalog";
    } else if (formName === "register") {
        if (regForm) regForm.style.display = "block";
        if (title) title.textContent = "Create Account";
    } else if (formName === "verify") {
        if (verifyForm) verifyForm.style.display = "block";
        if (title) title.textContent = "Email Verification";
    }
}

async function handleLoginSubmit(e) {
    e.preventDefault();
    const identifier = document.getElementById("loginIdentifier").value.trim();
    const password = document.getElementById("loginPassword").value;

    try {
        const res = await secureFetch("/gw/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (data.csrf_token) setCsrfToken(data.csrf_token);
            showToast(data.message || "Signed in! Loading authorized workspace...", "success");
            setTimeout(() => window.location.reload(), 450);
        } else {
            showToast(data.message || "Authentication failed", "error");
        }
    } catch (err) {
        showToast("Error reaching authentication gateway", "error");
    } finally {
        const pw = document.getElementById("loginPassword");
        if (pw) pw.value = "";
    }
}

async function handleRegisterSubmit(e) {
    e.preventDefault();
    const username = document.getElementById("regUsername").value.trim();
    const email = document.getElementById("regEmail").value.trim();
    const password = document.getElementById("regPassword").value;

    try {
        const res = await secureFetch("/gw/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, email, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (data.csrf_token) setCsrfToken(data.csrf_token);
            showToast(data.message || "Account registered. Check your email verification inbox.", "success");
            toggleAuthForm("verify");
        } else {
            showToast(data.message || "Registration failed", "error");
        }
    } catch (err) {
        showToast("Registration error", "error");
    } finally {
        const pw = document.getElementById("regPassword");
        if (pw) pw.value = "";
    }
}

async function handleVerifyEmailSubmit(e) {
    e.preventDefault();
    const code = document.getElementById("verifyEmailCode").value.trim();
    try {
        const res = await secureFetch("/gw/auth/verify-email", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || "Email verified!", "success");
            setTimeout(() => window.location.reload(), 450);
        } else {
            showToast(data.message || "Verification failed", "error");
        }
    } catch (err) {
        showToast("Verification request error", "error");
    } finally {
        const codeEl = document.getElementById("verifyEmailCode");
        if (codeEl) codeEl.value = "";
    }
}

async function resendVerificationCode() {
    try {
        const res = await secureFetch("/gw/auth/resend-verification", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "Verification email dispatched", res.ok ? "success" : "error");
    } catch (err) {
        showToast("Failed to queue verification code", "error");
    }
}

async function confirmLogout() {
    if (!confirm("Sign out of your Product Catalog session?")) return;
    try {
        await secureFetch("/gw/auth/logout", { method: "POST" });
        window.location.href = "/";
    } catch (err) {
        showToast("Sign out failed", "error");
    }
}

// ==============================================================================
// CATALOG LOADING & RENDERING (Public + Role-Safe)
// ==============================================================================

async function loadCatalogData() {
    try {
        const [prodRes, statsRes] = await Promise.all([
            secureFetch("/gw/catalog"),
            secureFetch("/gw/stats")
        ]);

        if (prodRes.ok) {
            window.CatalogApp.products = await prodRes.json();
            window.CatalogApp.filteredProducts = [...window.CatalogApp.products];
        }

        if (statsRes.ok) {
            const stats = await statsRes.json();
            updateStatsUI(stats);
            populateFilterOptions(stats.categories, stats.brands);
        }

        applyFilters();
    } catch (err) {
        console.error("Catalog load error:", err);
        showToast("Unable to retrieve catalog data", "error");
    }
}

window.loadCatalogData = loadCatalogData;
window.switchTab = switchTab;
window.secureFetch = secureFetch;
window.showToast = showToast;
window.escapeHtml = escapeHtml;

function updateStatsUI(stats) {
    const map = {
        statTotalProducts: stats.total_products,
        statTotalBrands: stats.total_brands,
        statTotalCategories: stats.total_categories,
        statExportReady: stats.export_ready_count
    };
    Object.entries(map).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val ?? 0;
    });
}

function populateFilterOptions(categories, brands) {
    const catSelect = document.getElementById("categoryFilter");
    const brandSelect = document.getElementById("brandFilter");

    if (catSelect) {
        const curr = catSelect.value;
        catSelect.innerHTML = `<option value="all">All Categories</option>`;
        (categories || []).forEach(c => {
            const opt = document.createElement("option");
            opt.value = c;
            opt.textContent = c;
            if (c === curr) opt.selected = true;
            catSelect.appendChild(opt);
        });
    }

    if (brandSelect) {
        const curr = brandSelect.value;
        brandSelect.innerHTML = `<option value="all">All Brands</option>`;
        (brands || []).forEach(b => {
            const opt = document.createElement("option");
            opt.value = b;
            opt.textContent = b;
            if (b === curr) opt.selected = true;
            brandSelect.appendChild(opt);
        });
    }
}

function applyFilters() {
    const searchVal = (document.getElementById("catalogSearchInput")?.value || "").toLowerCase().trim();
    const catVal = document.getElementById("categoryFilter")?.value || "all";
    const brandVal = document.getElementById("brandFilter")?.value || "all";
    const sortVal = document.getElementById("catalogSortSelect")?.value || "newest";

    let result = [...window.CatalogApp.products];

    if (searchVal) {
        result = result.filter(p => {
            const blob = [
                p.product_name, p.brand, p.category, p.description,
                (p.tags || []).join(" "), (p.features || []).join(" ")
            ].join(" ").toLowerCase();
            return blob.includes(searchVal);
        });
    }
    if (catVal !== "all") result = result.filter(p => p.category === catVal);
    if (brandVal !== "all") result = result.filter(p => p.brand === brandVal);

    result.sort((a, b) => {
        if (sortVal === "name_asc") return (a.product_name || "").localeCompare(b.product_name || "");
        if (sortVal === "name_desc") return (b.product_name || "").localeCompare(a.product_name || "");
        if (sortVal === "price_asc" || sortVal === "price_desc") {
            const pa = parseFloat((a.price || "").replace(/[^0-9.]/g, "")) || 0;
            const pb = parseFloat((b.price || "").replace(/[^0-9.]/g, "")) || 0;
            return sortVal === "price_asc" ? pa - pb : pb - pa;
        }
        return (b.id || 0) - (a.id || 0);
    });

    window.CatalogApp.filteredProducts = result;
    renderCatalog();
}

function renderCatalog() {
    const grid = document.getElementById("productsGrid");
    const tableWrap = document.getElementById("productsTableWrapper");
    const empty = document.getElementById("catalogEmptyState");
    if (!grid || !tableWrap || !empty) return;

    if (window.CatalogApp.filteredProducts.length === 0) {
        grid.style.display = "none";
        tableWrap.style.display = "none";
        empty.style.display = "flex";
        return;
    }

    empty.style.display = "none";
    if (window.CatalogApp.currentView === "grid") {
        grid.style.display = "grid";
        tableWrap.style.display = "none";
        renderGridView(window.CatalogApp.filteredProducts, grid);
    } else {
        grid.style.display = "none";
        tableWrap.style.display = "block";
        renderTableView(window.CatalogApp.filteredProducts, tableWrap);
    }
}

function canEditRole() {
    return window.CatalogApp.role === "admin" || window.CatalogApp.role === "editor";
}

function renderGridView(products, container) {
    container.innerHTML = "";
    const editable = canEditRole();

    products.forEach(p => {
        const card = document.createElement("div");
        card.className = "product-card";

        const specs = p.specifications || {};
        const specChips = Object.keys(specs).slice(0, 3)
            .map(k => `<span class="spec-chip"><b>${escapeHtml(k)}:</b> ${escapeHtml(specs[k])}</span>`)
            .join("");

        const editBtns = editable
            ? `<button type="button" class="btn btn-secondary btn-sm" data-item-action="edit" data-product-id="${p.id}">Edit</button>
               <button type="button" class="btn btn-danger btn-sm" data-item-action="delete" data-product-id="${p.id}" data-product-name="${escapeHtml(p.product_name)}">Delete</button>`
            : "";

        card.innerHTML = `
            <div class="card-image-box">
                ${pictureMarkup(p.image_path, p.product_name)}
            </div>
            <div class="card-body">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.45rem;">
                    <span class="card-brand" style="margin-bottom:0;">${escapeHtml(p.brand || "Unspecified")}</span>
                    <span class="badge badge-verified" style="font-size:0.7rem;padding:0.15rem 0.45rem;">✓ Verified</span>
                </div>
                <h3 class="card-title" title="${escapeHtml(p.product_name)}">${escapeHtml(p.product_name)}</h3>
                <div style="margin-bottom:0.45rem;">
                    <span class="spec-chip">${escapeHtml(p.category || "General")}</span>
                </div>
                <div class="card-price-row">
                    <span class="card-price">${escapeHtml(p.price || "Custom Quote")}</span>
                </div>
                <p class="card-desc">${escapeHtml(p.short_description || p.description || "")}</p>
                <div class="card-specs-preview">${specChips}</div>
                <div class="card-footer-actions">
                    <button type="button" class="btn btn-secondary btn-sm" data-item-action="view" data-product-id="${p.id}">View</button>
                    <button type="button" class="btn btn-success btn-sm" data-item-action="order" data-product-id="${p.id}">Order</button>
                    <a href="/export/pdf/${p.id}" class="btn btn-secondary btn-sm" download>PDF</a>
                    ${editBtns}
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderTableView(products, container) {
    const editable = canEditRole();
    const tbody = products.map(p => {
        const editBtns = editable
            ? `<button type="button" class="btn btn-secondary btn-sm" data-item-action="edit" data-product-id="${p.id}">Edit</button>
               <button type="button" class="btn btn-danger btn-sm" data-item-action="delete" data-product-id="${p.id}" data-product-name="${escapeHtml(p.product_name)}">Delete</button>`
            : "";
        return `
            <tr>
                <td style="width:64px;">${pictureMarkup(p.image_path, p.product_name, "table-thumb")}</td>
                <td>
                    <div style="font-weight:700;">${escapeHtml(p.product_name)}</div>
                    <div style="font-size:0.78rem;color:#64748b;">ID: #${p.id}${p.model ? ` • Model: ${escapeHtml(p.model)}` : ""}</div>
                </td>
                <td><b>${escapeHtml(p.brand || "—")}</b></td>
                <td><span class="badge badge-verified">${escapeHtml(p.category || "General")}</span></td>
                <td><span style="font-weight:700;color:#059669;">${escapeHtml(p.price || "—")}</span></td>
                <td>${escapeHtml(p.dimensions || "—")}</td>
                <td>
                    <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                        <button type="button" class="btn btn-secondary btn-sm" data-item-action="view" data-product-id="${p.id}">View</button>
                        <button type="button" class="btn btn-success btn-sm" data-item-action="order" data-product-id="${p.id}">Order</button>
                        <a href="/export/pdf/${p.id}" class="btn btn-secondary btn-sm" download>PDF</a>
                        ${editBtns}
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    container.innerHTML = `
        <div class="table-card">
            <div class="table-responsive">
                <table class="custom-table">
                    <thead>
                        <tr>
                            <th>Image</th><th>Product Name</th><th>Brand</th>
                            <th>Category</th><th>Price</th><th>Dimensions</th><th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>${tbody}</tbody>
                </table>
            </div>
        </div>
    `;
}

// ==============================================================================
// PRODUCT MODAL
// ==============================================================================

async function openProductModal(productId) {
    try {
        const res = await secureFetch(`/gw/catalog/item/${productId}`);
        if (!res.ok) throw new Error("Not found");
        const p = await res.json();
        window.CatalogApp.selectedCheckoutProduct = p;

        const modal = document.getElementById("productViewModal");
        const body = document.getElementById("productViewModalBody");
        const title = document.getElementById("productViewModalTitle");
        const pdfLink = document.getElementById("modalPdfDownloadLink");

        if (title) title.textContent = p.product_name;
        if (pdfLink) pdfLink.href = `/export/pdf/${p.id}`;

        const specRows = Object.entries(p.specifications || {}).map(([k, v]) => `
            <tr>
                <td style="padding:0.4rem 0.6rem;font-weight:600;border-bottom:1px solid #edf2f7;width:35%;">${escapeHtml(k)}</td>
                <td style="padding:0.4rem 0.6rem;border-bottom:1px solid #edf2f7;">${escapeHtml(v)}</td>
            </tr>
        `).join("");

        const features = (p.features || []).map(f => `<li style="margin-bottom:0.3rem;">${escapeHtml(f)}</li>`).join("");
        const usps = (p.selling_points || []).map(u => `<div style="font-size:0.88rem;color:#059669;margin-bottom:0.25rem;">✓ <b>${escapeHtml(u)}</b></div>`).join("");

        body.innerHTML = `
            <div style="border-radius:8px;overflow:hidden;border:1px solid #e2e8f0;margin-bottom:1rem;aspect-ratio:4/3;max-height:320px;margin-left:auto;margin-right:auto;">
                ${pictureMarkup(p.image_path, p.product_name)}
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
                <div>
                    <span class="badge badge-category">${escapeHtml(p.category)}</span>
                    <span style="font-size:0.85rem;color:#64748b;margin-left:0.5rem;">Brand: <b>${escapeHtml(p.brand)}</b></span>
                </div>
                <div style="font-size:1.35rem;font-weight:800;color:#059669;">${escapeHtml(p.price || "Custom Quote")}</div>
            </div>
            ${p.short_description ? `<div style="background:#f8fafc;padding:0.75rem 1rem;border-left:3px solid #2563eb;border-radius:4px;font-style:italic;margin-bottom:1rem;">${escapeHtml(p.short_description)}</div>` : ""}
            ${p.description ? `<div style="font-size:0.92rem;line-height:1.6;margin-bottom:1.25rem;color:#334155;">${escapeHtml(p.description)}</div>` : ""}
            ${usps ? `<div style="margin-bottom:1.25rem;"><b>Selling Highlights:</b><div style="margin-top:0.4rem;">${usps}</div></div>` : ""}
            ${features ? `<div style="margin-bottom:1.25rem;"><b>Key Features:</b><ul style="padding-left:1.2rem;margin-top:0.4rem;font-size:0.9rem;">${features}</ul></div>` : ""}
            ${specRows ? `<div style="margin-bottom:1.25rem;"><b>Specifications:</b><table style="width:100%;border-collapse:collapse;margin-top:0.5rem;font-size:0.88rem;"><tbody>${specRows}</tbody></table></div>` : ""}
            <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:0.75rem;">
                <span>Dimensions: ${escapeHtml(p.dimensions || "N/A")}</span>
                <span>SKU #${p.id}</span>
            </div>
        `;
        if (modal) modal.classList.add("active");
    } catch (err) {
        showToast("Failed to load product details", "error");
    }
}

// ==============================================================================
// CHECKOUT (SERVER-AUTHORITATIVE PRICING PREVIEW + LUHN ORDER)
// ==============================================================================

function populateCheckoutDropdown() {
    const select = document.getElementById("checkoutProductSelect");
    if (!select) return;
    select.innerHTML = "";

    window.CatalogApp.products.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.product_name} (${p.price || "Quote Only"})`;
        select.appendChild(opt);
    });

    if (window.CatalogApp.selectedCheckoutProduct) {
        select.value = window.CatalogApp.selectedCheckoutProduct.id;
    }
    updateCheckoutProductSummary();
}

function updateCheckoutProductSummary() {
    const select = document.getElementById("checkoutProductSelect");
    const qtyInput = document.getElementById("checkoutQuantity");
    if (!select) return;

    const prodId = parseInt(select.value, 10);
    const prod = window.CatalogApp.products.find(p => p.id === prodId) || window.CatalogApp.products[0];
    if (!prod) return;

    window.CatalogApp.selectedCheckoutProduct = prod;
    const qty = Math.max(1, Math.min(50, parseInt(qtyInput?.value || "1", 10) || 1));

    const nameEl = document.getElementById("summaryProductName");
    const baseEl = document.getElementById("summaryBasePrice");
    const taxEl = document.getElementById("summaryTaxAmount");
    const totalEl = document.getElementById("summaryTotalAmount");
    const thumbBox = document.getElementById("checkoutProductThumbnailBox");

    if (nameEl) nameEl.textContent = `${prod.product_name} (x${qty})`;
    if (thumbBox) thumbBox.innerHTML = pictureMarkup(prod.image_path, prod.product_name);

    const rawPrice = (prod.price || "").trim();
    const cleaned = rawPrice.replace(/\(.*?\)/g, "");
    const match = cleaned.match(/([0-9][0-9,]*(?:\.[0-9]+)?)/);
    const unitNum = match ? parseFloat(match[1].replace(/,/g, "")) : NaN;
    const sym = rawPrice.includes("$") ? "$" : (rawPrice.includes("€") ? "€" : "₹");

    if (isNaN(unitNum) || unitNum <= 0) {
        if (baseEl) baseEl.textContent = "Custom Quote";
        if (taxEl) taxEl.textContent = "—";
        if (totalEl) totalEl.textContent = "Request via Support";
    } else {
        const subtotal = unitNum * qty;
        const tax = subtotal * 0.18;
        const total = subtotal + tax;
        if (baseEl) baseEl.textContent = `${sym}${subtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        if (taxEl) taxEl.textContent = `${sym}${tax.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        if (totalEl) totalEl.textContent = `${sym}${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
}

async function handleCheckoutSubmit(e) {
    e.preventDefault();
    if (!window.CatalogApp.authenticated) {
        openAuthModal("login");
        showToast("Please sign in to place a verified commercial order", "warning");
        return;
    }

    const prod = window.CatalogApp.selectedCheckoutProduct;
    if (!prod) {
        showToast("Please select a product", "warning");
        return;
    }

    // Notice: Never transmit client price/amount — backend derives exact price from DB
    const payload = {
        product_id: prod.id,
        quantity: parseInt(document.getElementById("checkoutQuantity")?.value || "1", 10) || 1,
        customer_name: document.getElementById("checkoutCustomerName").value.trim(),
        customer_email: document.getElementById("checkoutCustomerEmail").value.trim(),
        billing_address: document.getElementById("checkoutAddress").value.trim(),
        payment_method: window.CatalogApp.selectedPaymentMethod,
        card_number: document.getElementById("checkoutCardNumber")?.value || "",
        card_expiry: document.getElementById("checkoutCardExpiry")?.value || "",
        card_cvv: document.getElementById("checkoutCardCvv")?.value || ""
    };

    const btn = document.getElementById("checkoutSubmitBtn");
    if (btn) { btn.disabled = true; btn.textContent = "Verifying with Server..."; }

    try {
        const res = await secureFetch("/gw/checkout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
            openOrderConfirmationModal(data);
            showToast(data.message, "success");
            loadUserOrders();
        } else {
            showToast(data.message || "Payment authorization declined", "error");
        }
    } catch (err) {
        showToast("Error communicating with checkout service", "error");
    } finally {
        // Clear sensitive payment card inputs immediately from browser DOM memory
        ["checkoutCardNumber", "checkoutCardExpiry", "checkoutCardCvv"].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });
        if (btn) { btn.disabled = false; btn.textContent = "🔒 Complete Verified Payment"; }
    }
}

function openOrderConfirmationModal(orderData) {
    const modal = document.getElementById("orderConfirmationModal");
    const body = document.getElementById("orderConfirmationModalBody");
    if (!modal || !body) return;
    body.innerHTML = `
        <div style="text-align:center;margin-bottom:1.25rem;">
            <div style="font-size:2rem;font-weight:900;color:#059669;">${escapeHtml(orderData.amount)}</div>
            <div style="font-size:0.85rem;color:#64748b;">Order Reference: <b>${escapeHtml(orderData.order_number)}</b></div>
        </div>
        <div style="background:#f8fafc;padding:1rem;border-radius:8px;border:1px solid #e2e8f0;font-size:0.88rem;line-height:1.7;">
            <div><b>Item:</b> ${escapeHtml(orderData.product_name)} &times; ${escapeHtml(orderData.quantity)}</div>
            <div><b>Unit Price:</b> ${escapeHtml(orderData.unit_price)} &bull; <b>Tax (18%):</b> ${escapeHtml(orderData.tax_amount)}</div>
            <div><b>Payment:</b> ${escapeHtml(orderData.payment_method)} ${escapeHtml(orderData.card_last4 || "")}</div>
            <div><b>Status:</b> <span class="badge badge-verified">Server Verified</span></div>
            <div><b>Date:</b> ${escapeHtml(orderData.created_at)}</div>
        </div>
    `;
    modal.classList.add("active");
}

async function loadUserOrders() {
    const box = document.getElementById("userOrdersHistoryBox");
    if (!box || !window.CatalogApp.authenticated) return;
    try {
        const res = await secureFetch("/gw/orders");
        if (!res.ok) return;
        const orders = await res.json();
        if (!orders.length) {
            box.innerHTML = `<p style="font-size:0.85rem;color:#64748b;">No orders recorded on this account yet.</p>`;
            return;
        }
        const rows = orders.slice(0, 10).map(o => `
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:0.5rem;"><b>${escapeHtml(o.order_number)}</b></td>
                <td style="padding:0.5rem;">${escapeHtml(o.product_name)} (${o.quantity || 1})</td>
                <td style="padding:0.5rem;font-weight:700;color:#059669;">${escapeHtml(o.amount)}</td>
                <td style="padding:0.5rem;">${escapeHtml(o.payment_method)} ${o.card_last4 ? `(${escapeHtml(o.card_last4)})` : ""}</td>
                <td style="padding:0.5rem;">${escapeHtml(o.created_at)}</td>
            </tr>
        `).join("");
        box.innerHTML = `
            <div class="table-responsive">
                <table class="custom-table" style="min-width:520px;">
                    <thead><tr><th>Order #</th><th>Product</th><th>Total</th><th>Method</th><th>Date</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    } catch (err) {
        console.debug("Orders load skip:", err);
    }
}

// ==============================================================================
// CONTACT SUPPORT INQUIRIES
// ==============================================================================

async function handleContactSubmit(e) {
    e.preventDefault();
    const payload = {
        name: document.getElementById("contactName").value.trim(),
        email: document.getElementById("contactEmail").value.trim(),
        company: document.getElementById("contactCompany").value.trim(),
        category: document.getElementById("contactCategory").value,
        subject: document.getElementById("contactSubject").value.trim(),
        message: document.getElementById("contactMessage").value.trim()
    };

    const btn = document.getElementById("contactSubmitBtn");
    if (btn) { btn.disabled = true; btn.textContent = "Sending..."; }

    try {
        const res = await secureFetch("/gw/contact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message, "success");
            document.getElementById("contactForm").reset();
        } else {
            showToast(data.message || "Failed to send inquiry", "error");
        }
    } catch (err) {
        showToast("Error submitting contact form", "error");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "✉️ Send Inquiry"; }
    }
}

// ==============================================================================
// TOAST & DEBOUNCE UTILITIES
// ==============================================================================

function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const icon = type === "success" ? "✓" : (type === "error" ? "✕" : (type === "warning" ? "⚠️" : "ℹ️"));

    toast.innerHTML = `<span style="font-weight:700;">${icon}</span><div class="toast-message">${escapeHtml(message)}</div>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(-100%)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function debounce(fn, wait) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}
