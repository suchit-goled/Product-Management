/**
 * Suchit Product Catalog Generator — Modern Responsive Client Application
 * Features: Mobile drawer navigation, Auth & RBAC, Safe API key management,
 * Commercial checkout, Contact support, Google Analytics 4, Backups, and Exports.
 */

const API_BASE = "";

// Global Application State
let appState = {
    products: [],
    filteredProducts: [],
    categories: [],
    brands: [],
    currentView: "grid", // 'grid' | 'table'
    activeTab: "catalogExplorer",
    currentUser: null,
    currentDraft: null,
    selectedFile: null,
    selectedCheckoutProduct: null,
    selectedPaymentMethod: "Credit Card"
};

// ==============================================================================
// INITIALIZATION
// ==============================================================================

document.addEventListener("DOMContentLoaded", () => {
    initMobileNavigation();
    initNavigationTabs();
    initToolbarFilters();
    initDropzone();
    initSettingsAndBackups();
    checkAuthStatus();
    loadCatalogData();
    loadBackupsList();
});

// ==============================================================================
// MOBILE NAVIGATION & DRAWER
// ==============================================================================

function initMobileNavigation() {
    const menuBtn = document.getElementById("mobileMenuBtn");
    const drawer = document.getElementById("mobileNavDrawer");
    const backdrop = document.getElementById("mobileNavBackdrop");

    if (menuBtn && drawer && backdrop) {
        menuBtn.addEventListener("click", () => {
            drawer.classList.add("open");
            backdrop.style.display = "block";
            document.body.style.overflow = "hidden"; // Prevent background scroll
        });
    }

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeMobileDrawer();
            closeAllModals();
        }
    });
}

function closeMobileDrawer() {
    const drawer = document.getElementById("mobileNavDrawer");
    const backdrop = document.getElementById("mobileNavBackdrop");
    if (drawer) drawer.classList.remove("open");
    if (backdrop) backdrop.style.display = "none";
    document.body.style.overflow = "";
}

// ==============================================================================
// NAVIGATION TABS & SPA ROUTING
// ==============================================================================

function initNavigationTabs() {
    const navLinks = document.querySelectorAll(".nav-link[data-tab]");
    navLinks.forEach(link => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            const targetTab = link.getAttribute("data-tab");
            switchTab(targetTab);
            closeMobileDrawer();
        });
    });
}

function switchTab(tabId) {
    appState.activeTab = tabId;

    // Update active nav links across desktop and mobile
    document.querySelectorAll(".nav-link[data-tab]").forEach(link => {
        if (link.getAttribute("data-tab") === tabId) {
            link.classList.add("active");
        } else {
            link.classList.remove("active");
        }
    });

    // Update visible section
    document.querySelectorAll(".content-section").forEach(sec => {
        if (sec.id === tabId) {
            sec.classList.add("active");
        } else {
            sec.classList.remove("active");
        }
    });

    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tabId === "catalogExplorer") {
        loadCatalogData();
    } else if (tabId === "checkoutSection") {
        populateCheckoutDropdown();
    } else if (tabId === "settingsSection") {
        loadSettingsHealth();
        loadBackupsList();
    }
}

function handleNewProductClick() {
    if (!canEdit()) {
        openAuthModal("login");
        showToast("Please sign in as Editor or Admin to add new products", "warning");
        return;
    }
    switchTab("aiStudio");
}

// ==============================================================================
// AUTHENTICATION & ROLE-BASED ACCESS CONTROL (RBAC)
// ==============================================================================

async function checkAuthStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/me`);
        if (res.ok) {
            const data = await res.json();
            if (data.authenticated) {
                appState.currentUser = data.user;
            } else {
                appState.currentUser = null;
            }
            renderAuthUI();
        }
    } catch (err) {
        console.error("Auth check error:", err);
    }
}

function renderAuthUI() {
    const headerContainer = document.getElementById("authHeaderContainer");
    const mobileAuthContainer = document.getElementById("mobileAuthControls");

    if (appState.currentUser) {
        const u = appState.currentUser;
        const initial = (u.username || "U")[0].toUpperCase();

        const html = `
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <div class="user-account-badge" onclick="confirmLogout()" title="Click to Sign Out">
                    <div class="user-avatar-circle">${escapeHtml(initial)}</div>
                    <span style="font-weight:600;">${escapeHtml(u.username)}</span>
                    <span class="role-pill ${escapeHtml(u.role)}">${escapeHtml(u.role)}</span>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="confirmLogout()" style="padding:0.25rem 0.5rem;font-size:0.75rem;">Exit</button>
            </div>
        `;
        if (headerContainer) headerContainer.innerHTML = html;

        if (mobileAuthContainer) {
            mobileAuthContainer.innerHTML = `
                <div style="font-size:0.85rem;margin-bottom:0.75rem;">
                    Signed in as <b>${escapeHtml(u.username)}</b> <span class="role-pill ${escapeHtml(u.role)}">${escapeHtml(u.role)}</span>
                </div>
                <button class="btn btn-secondary btn-sm" style="width:100%;" onclick="confirmLogout()">Sign Out</button>
            `;
        }
    } else {
        const guestHtml = `
            <div style="display:flex;gap:0.4rem;">
                <button class="btn btn-secondary btn-sm" onclick="openAuthModal('login')">Sign In</button>
                <button class="btn btn-primary btn-sm" onclick="openAuthModal('register')">Register</button>
            </div>
        `;
        if (headerContainer) headerContainer.innerHTML = guestHtml;

        if (mobileAuthContainer) {
            mobileAuthContainer.innerHTML = `
                <div style="display:flex;gap:0.5rem;">
                    <button class="btn btn-secondary btn-sm" style="flex:1;" onclick="openAuthModal('login'); closeMobileDrawer();">Sign In</button>
                    <button class="btn btn-primary btn-sm" style="flex:1;" onclick="openAuthModal('register'); closeMobileDrawer();">Register</button>
                </div>
            `;
        }
    }
}

function canEdit() {
    if (!appState.currentUser) return false;
    return appState.currentUser.role === "admin" || appState.currentUser.role === "editor";
}

function isAdmin() {
    if (!appState.currentUser) return false;
    return appState.currentUser.role === "admin";
}

function openAuthModal(mode = "login") {
    const modal = document.getElementById("authModal");
    if (!modal) return;
    toggleAuthForm(mode);
    modal.classList.add("active");
}

function closeAuthModal() {
    const modal = document.getElementById("authModal");
    if (modal) modal.classList.remove("active");
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
        if (title) title.textContent = "Sign In to Suchit";
    } else if (formName === "register") {
        if (regForm) regForm.style.display = "block";
        if (title) title.textContent = "Create an Account";
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
        const res = await fetch(`${API_BASE}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ identifier, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            appState.currentUser = data.user;
            renderAuthUI();
            closeAuthModal();
            showToast(data.message || "Logged in successfully!", "success");
            trackAnalyticsEvent("user_login", { username: data.user.username });
        } else {
            showToast(data.message || "Login failed", "error");
        }
    } catch (err) {
        showToast("Error connecting to auth service", "error");
    }
}

async function handleRegisterSubmit(e) {
    e.preventDefault();
    const username = document.getElementById("regUsername").value.trim();
    const email = document.getElementById("regEmail").value.trim();
    const password = document.getElementById("regPassword").value;

    try {
        const res = await fetch(`${API_BASE}/api/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, email, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            appState.currentUser = { id: data.user_id, username: data.username, email: data.email, role: data.role, is_verified: false };
            renderAuthUI();
            showToast(`Account created! Your verification code is ${data.verification_code}`, "info");
            toggleAuthForm("verify");
        } else {
            showToast(data.message || "Registration failed", "error");
        }
    } catch (err) {
        showToast("Error registering account", "error");
    }
}

async function handleVerifyEmailSubmit(e) {
    e.preventDefault();
    const code = document.getElementById("verifyEmailCode").value.trim();

    try {
        const res = await fetch(`${API_BASE}/api/auth/verify-email`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (appState.currentUser) appState.currentUser.is_verified = true;
            renderAuthUI();
            closeAuthModal();
            showToast(data.message || "Email verified successfully!", "success");
        } else {
            showToast(data.message || "Invalid code", "error");
        }
    } catch (err) {
        showToast("Error verifying email", "error");
    }
}

async function confirmLogout() {
    if (!confirm("Are you sure you want to sign out of Suchit?")) return;
    try {
        await fetch(`${API_BASE}/api/auth/logout`, { method: "POST" });
        appState.currentUser = null;
        renderAuthUI();
        showToast("Signed out successfully", "info");
    } catch (err) {
        console.error("Logout error:", err);
    }
}

// ==============================================================================
// CATALOG DATA & EXPLORER
// ==============================================================================

async function loadCatalogData() {
    try {
        const [prodRes, statsRes] = await Promise.all([
            fetch(`${API_BASE}/products`),
            fetch(`${API_BASE}/api/stats`)
        ]);

        if (prodRes.ok) {
            appState.products = await prodRes.json();
            appState.filteredProducts = [...appState.products];
        }

        if (statsRes.ok) {
            const stats = await statsRes.json();
            updateStatsUI(stats);
            populateFilterOptions(stats.categories, stats.brands);
        }

        applyFilters();
    } catch (err) {
        console.error("Error loading catalog data:", err);
        showToast("Failed to load catalog records from server", "error");
    }
}

function updateStatsUI(stats) {
    const elProd = document.getElementById("statTotalProducts");
    const elBrand = document.getElementById("statTotalBrands");
    const elCat = document.getElementById("statTotalCategories");
    const elExp = document.getElementById("statExportReady");

    if (elProd) elProd.textContent = stats.total_products ?? 0;
    if (elBrand) elBrand.textContent = stats.total_brands ?? 0;
    if (elCat) elCat.textContent = stats.total_categories ?? 0;
    if (elExp) elExp.textContent = stats.export_ready_count ?? 0;
}

function populateFilterOptions(categories, brands) {
    const catSelect = document.getElementById("categoryFilter");
    const brandSelect = document.getElementById("brandFilter");

    if (catSelect) {
        const currentCat = catSelect.value;
        catSelect.innerHTML = `<option value="all">All Categories</option>`;
        (categories || []).forEach(c => {
            const opt = document.createElement("option");
            opt.value = c;
            opt.textContent = c;
            if (c === currentCat) opt.selected = true;
            catSelect.appendChild(opt);
        });
    }

    if (brandSelect) {
        const currentBrand = brandSelect.value;
        brandSelect.innerHTML = `<option value="all">All Brands</option>`;
        (brands || []).forEach(b => {
            const opt = document.createElement("option");
            opt.value = b;
            opt.textContent = b;
            if (b === currentBrand) opt.selected = true;
            brandSelect.appendChild(opt);
        });
    }
}

function initToolbarFilters() {
    const searchInput = document.getElementById("catalogSearchInput");
    const catSelect = document.getElementById("categoryFilter");
    const brandSelect = document.getElementById("brandFilter");
    const sortSelect = document.getElementById("catalogSortSelect");

    if (searchInput) {
        searchInput.addEventListener("input", debounce(() => {
            applyFilters();
            trackAnalyticsEvent("catalog_search", { query: searchInput.value });
        }, 250));
    }
    if (catSelect) catSelect.addEventListener("change", applyFilters);
    if (brandSelect) brandSelect.addEventListener("change", applyFilters);
    if (sortSelect) sortSelect.addEventListener("change", applyFilters);

    // View toggles
    const gridBtn = document.getElementById("viewGridBtn");
    const tableBtn = document.getElementById("viewTableBtn");

    if (gridBtn && tableBtn) {
        gridBtn.addEventListener("click", () => {
            appState.currentView = "grid";
            gridBtn.classList.add("active");
            tableBtn.classList.remove("active");
            renderCatalog();
        });

        tableBtn.addEventListener("click", () => {
            appState.currentView = "table";
            tableBtn.classList.add("active");
            gridBtn.classList.remove("active");
            renderCatalog();
        });
    }
}

function applyFilters() {
    const searchVal = (document.getElementById("catalogSearchInput")?.value || "").toLowerCase().trim();
    const catVal = document.getElementById("categoryFilter")?.value || "all";
    const brandVal = document.getElementById("brandFilter")?.value || "all";
    const sortVal = document.getElementById("catalogSortSelect")?.value || "newest";

    let result = [...appState.products];

    if (searchVal) {
        result = result.filter(p => {
            const name = (p.product_name || "").toLowerCase();
            const brand = (p.brand || "").toLowerCase();
            const cat = (p.category || "").toLowerCase();
            const desc = (p.description || "").toLowerCase();
            const tags = (p.tags || []).join(" ").toLowerCase();
            const feats = (p.features || []).join(" ").toLowerCase();
            return name.includes(searchVal) || brand.includes(searchVal) ||
                   cat.includes(searchVal) || desc.includes(searchVal) ||
                   tags.includes(searchVal) || feats.includes(searchVal);
        });
    }

    if (catVal !== "all") {
        result = result.filter(p => p.category === catVal);
    }

    if (brandVal !== "all") {
        result = result.filter(p => p.brand === brandVal);
    }

    result.sort((a, b) => {
        if (sortVal === "name_asc") return (a.product_name || "").localeCompare(b.product_name || "");
        if (sortVal === "name_desc") return (b.product_name || "").localeCompare(a.product_name || "");
        if (sortVal === "price_asc") {
            const pa = parseFloat((a.price || "").replace(/[^0-9.]/g, "")) || 0;
            const pb = parseFloat((b.price || "").replace(/[^0-9.]/g, "")) || 0;
            return pa - pb;
        }
        if (sortVal === "price_desc") {
            const pa = parseFloat((a.price || "").replace(/[^0-9.]/g, "")) || 0;
            const pb = parseFloat((b.price || "").replace(/[^0-9.]/g, "")) || 0;
            return pb - pa;
        }
        return (b.id || 0) - (a.id || 0);
    });

    appState.filteredProducts = result;
    renderCatalog();
}

function renderCatalog() {
    const gridContainer = document.getElementById("productsGrid");
    const tableContainer = document.getElementById("productsTableWrapper");
    const emptyState = document.getElementById("catalogEmptyState");

    if (!gridContainer || !tableContainer || !emptyState) return;

    if (appState.filteredProducts.length === 0) {
        gridContainer.style.display = "none";
        tableContainer.style.display = "none";
        emptyState.style.display = "flex";
        return;
    }

    emptyState.style.display = "none";

    if (appState.currentView === "grid") {
        gridContainer.style.display = "grid";
        tableContainer.style.display = "none";
        renderGridView(appState.filteredProducts, gridContainer);
    } else {
        gridContainer.style.display = "none";
        tableContainer.style.display = "block";
        renderTableView(appState.filteredProducts, tableContainer);
    }
}

function renderGridView(products, container) {
    container.innerHTML = "";

    products.forEach(p => {
        const card = document.createElement("div");
        card.className = "product-card";

        const imageSrc = p.image_path || "/static/uploads/suchit_asset_4_boat.jpg";
        const imageHtml = `<img src="${escapeHtml(imageSrc)}" loading="lazy" alt="${escapeHtml(p.product_name)}" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'card-image-placeholder\\'>Product Asset Ready</div>';">`;

        const isAi = (p.extraction_source || "").toLowerCase().includes("gemini");
        const aiBadge = isAi
            ? `<span class="badge badge-ai">✨ AI Enriched</span>`
            : `<span class="badge badge-verified">Verified</span>`;

        const specs = p.specifications || {};
        const specKeys = Object.keys(specs).slice(0, 3);
        const specChips = specKeys.map(k => `<span class="spec-chip"><b>${escapeHtml(k)}:</b> ${escapeHtml(specs[k])}</span>`).join("");

        // Authorization checks for Edit/Delete buttons
        const editActions = canEdit()
            ? `<button class="btn btn-secondary btn-sm" onclick="openEditModal(${p.id})">Edit</button>
               <button class="btn btn-danger btn-sm" onclick="confirmDeleteProduct(${p.id}, '${escapeJs(p.product_name)}')">Delete</button>`
            : "";

        card.innerHTML = `
            <div class="card-image-box">
                ${imageHtml}
                <div class="card-badges">
                    <span class="badge badge-category">${escapeHtml(p.category || "General")}</span>
                    ${aiBadge}
                </div>
            </div>
            <div class="card-body">
                <div class="card-brand">${escapeHtml(p.brand || "Unspecified")}</div>
                <h3 class="card-title" title="${escapeHtml(p.product_name)}">${escapeHtml(p.product_name)}</h3>
                <div class="card-price-row">
                    <span class="card-price">${escapeHtml(p.price || "N/A")}</span>
                </div>
                <p class="card-desc">${escapeHtml(p.short_description || p.description || "No description provided.")}</p>
                <div class="card-specs-preview">
                    ${specChips}
                </div>
                <div class="card-footer-actions">
                    <button class="btn btn-secondary btn-sm" onclick="openProductModal(${p.id})">View</button>
                    <button class="btn btn-success btn-sm" onclick="openCheckoutForProductById(${p.id})">Order / License</button>
                    <a href="/export/pdf/${p.id}" class="btn btn-secondary btn-sm" title="Download PDF Spec Sheet" download>PDF</a>
                    ${editActions}
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderTableView(products, container) {
    let tbodyHtml = products.map(p => {
        const imageSrc = p.image_path || "/static/uploads/suchit_asset_4_boat.jpg";
        const imgHtml = `<img src="${escapeHtml(imageSrc)}" loading="lazy" class="table-thumb" alt="${escapeHtml(p.product_name)}">`;

        const editActions = canEdit()
            ? `<button class="btn btn-secondary btn-sm" onclick="openEditModal(${p.id})">Edit</button>
               <button class="btn btn-danger btn-sm" onclick="confirmDeleteProduct(${p.id}, '${escapeJs(p.product_name)}')">Delete</button>`
            : "";

        return `
            <tr>
                <td style="width: 50px;">${imgHtml}</td>
                <td>
                    <div style="font-weight:700;">${escapeHtml(p.product_name)}</div>
                    <div style="font-size:0.78rem;color:#64748b;">ID: #${p.id} ${p.model ? `• Model: ${escapeHtml(p.model)}` : ''}</div>
                </td>
                <td><b>${escapeHtml(p.brand || "—")}</b></td>
                <td><span class="badge badge-category" style="background:#f1f5f9;color:#334155;border:1px solid #cbd5e1;">${escapeHtml(p.category || "General")}</span></td>
                <td><span style="font-weight:700;color:#059669;">${escapeHtml(p.price || "—")}</span></td>
                <td>${escapeHtml(p.dimensions || "—")}</td>
                <td>
                    <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                        <button class="btn btn-secondary btn-sm" onclick="openProductModal(${p.id})">View</button>
                        <button class="btn btn-success btn-sm" onclick="openCheckoutForProductById(${p.id})">Order</button>
                        <a href="/export/pdf/${p.id}" class="btn btn-secondary btn-sm" download>PDF</a>
                        ${editActions}
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
                            <th>Image</th>
                            <th>Product Name</th>
                            <th>Brand</th>
                            <th>Category</th>
                            <th>Price</th>
                            <th>Dimensions</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${tbodyHtml}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

// ==============================================================================
// COMMERCIAL CHECKOUT & ORDER
// ==============================================================================

function populateCheckoutDropdown() {
    const select = document.getElementById("checkoutProductSelect");
    if (!select) return;

    select.innerHTML = "";
    appState.products.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.product_name} (${p.price || 'N/A'})`;
        select.appendChild(opt);
    });

    if (appState.selectedCheckoutProduct) {
        select.value = appState.selectedCheckoutProduct.id;
    }

    updateCheckoutProductSummary();
}

function updateCheckoutProductSummary() {
    const select = document.getElementById("checkoutProductSelect");
    if (!select) return;

    const prodId = parseInt(select.value);
    const prod = appState.products.find(p => p.id === prodId) || appState.products[0];
    if (!prod) return;

    appState.selectedCheckoutProduct = prod;

    const nameEl = document.getElementById("summaryProductName");
    const baseEl = document.getElementById("summaryBasePrice");
    const taxEl = document.getElementById("summaryTaxAmount");
    const totalEl = document.getElementById("summaryTotalAmount");
    const thumbImg = document.getElementById("checkoutThumbImg");

    if (nameEl) nameEl.textContent = prod.product_name;

    // Parse price safely
    const numPrice = parseFloat((prod.price || "1499").replace(/[^0-9.]/g, "")) || 1499;
    const tax = numPrice * 0.18;
    const total = numPrice + tax;

    const symbol = (prod.price || "").includes("$") ? "$" : "₹";

    if (baseEl) baseEl.textContent = `${symbol}${numPrice.toFixed(2)}`;
    if (taxEl) taxEl.textContent = `${symbol}${tax.toFixed(2)}`;
    if (totalEl) totalEl.textContent = `${symbol}${total.toFixed(2)}`;

    if (thumbImg) {
        thumbImg.src = prod.image_path || "/static/uploads/suchit_asset_4_boat.jpg";
    }
}

function selectPaymentMethod(method, el) {
    appState.selectedPaymentMethod = method;
    document.querySelectorAll(".payment-option-card").forEach(c => c.classList.remove("selected"));
    if (el) el.classList.add("selected");

    const cardFields = document.getElementById("cardPaymentFields");
    if (cardFields) {
        cardFields.style.display = method === "Credit Card" ? "block" : "none";
    }
}

function fillTestCardDetails() {
    const num = document.getElementById("checkoutCardNumber");
    const exp = document.getElementById("checkoutCardExpiry");
    const cvv = document.getElementById("checkoutCardCvv");

    if (num) num.value = "4242 4242 4242 4242";
    if (exp) exp.value = "12/28";
    if (cvv) cvv.value = "123";
    showToast("Test card details pre-filled!", "info");
}

async function handleCheckoutSubmit(e) {
    e.preventDefault();
    const prod = appState.selectedCheckoutProduct;
    if (!prod) {
        showToast("Please select a product to checkout", "warning");
        return;
    }

    const name = document.getElementById("checkoutCustomerName").value.trim();
    const email = document.getElementById("checkoutCustomerEmail").value.trim();
    const address = document.getElementById("checkoutAddress").value.trim();
    const totalText = document.getElementById("summaryTotalAmount").textContent;

    const payload = {
        product_id: prod.id,
        product_name: prod.product_name,
        customer_name: name,
        customer_email: email,
        billing_address: address,
        amount: totalText,
        payment_method: appState.selectedPaymentMethod,
        card_number: document.getElementById("checkoutCardNumber")?.value || ""
    };

    const submitBtn = document.getElementById("checkoutSubmitBtn");
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Processing Secure Payment...";
    }

    try {
        const res = await fetch(`${API_BASE}/api/checkout/process`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (res.ok && data.success) {
            trackAnalyticsEvent("purchase", { order_number: data.order_number, value: totalText });
            openOrderConfirmationModal(data, prod);
            showToast("Payment processed successfully!", "success");
        } else {
            showToast(data.message || "Payment authorization failed", "error");
        }
    } catch (err) {
        showToast("Error communicating with payment gateway", "error");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "🔒 Complete Secure Payment";
        }
    }
}

function openCheckoutForProductById(prodId) {
    const prod = appState.products.find(p => p.id === prodId);
    if (prod) {
        appState.selectedCheckoutProduct = prod;
    }
    switchTab("checkoutSection");
}

function openOrderConfirmationModal(orderData, prod) {
    const modal = document.getElementById("orderConfirmationModal");
    const body = document.getElementById("orderConfirmationModalBody");
    if (!modal || !body) return;

    body.innerHTML = `
        <div style="text-align:center;margin-bottom:1.25rem;">
            <div style="font-size:2rem;font-weight:900;color:#059669;margin-bottom:0.25rem;">
                ${escapeHtml(orderData.amount)}
            </div>
            <div style="font-size:0.85rem;color:#64748b;">
                Order Reference: <b>${escapeHtml(orderData.order_number)}</b>
            </div>
        </div>

        <div style="background:#f8fafc;padding:1rem;border-radius:8px;border:1px solid #e2e8f0;font-size:0.88rem;line-height:1.7;margin-bottom:1rem;">
            <div><b>Item:</b> ${escapeHtml(prod.product_name)}</div>
            <div><b>Brand:</b> ${escapeHtml(prod.brand)}</div>
            <div><b>Status:</b> <span class="badge badge-verified">Payment Authorized</span></div>
            <div><b>Receipt Date:</b> ${escapeHtml(orderData.created_at)}</div>
        </div>
        <p style="font-size:0.82rem;color:#64748b;text-align:center;">
            A confirmation receipt and digital license package has been registered for your catalog order.
        </p>
    `;
    modal.classList.add("active");
}

function closeOrderModal() {
    const modal = document.getElementById("orderConfirmationModal");
    if (modal) modal.classList.remove("active");
}

// ==============================================================================
// CONTACT INQUIRIES
// ==============================================================================

async function handleContactSubmit(e) {
    e.preventDefault();
    const name = document.getElementById("contactName").value.trim();
    const email = document.getElementById("contactEmail").value.trim();
    const company = document.getElementById("contactCompany").value.trim();
    const category = document.getElementById("contactCategory").value;
    const subject = document.getElementById("contactSubject").value.trim();
    const message = document.getElementById("contactMessage").value.trim();

    const submitBtn = document.getElementById("contactSubmitBtn");
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Sending Inquiry...";
    }

    try {
        const res = await fetch(`${API_BASE}/api/contact`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email, company, category, subject, message })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || "Inquiry sent successfully!", "success");
            document.getElementById("contactForm").reset();
            trackAnalyticsEvent("contact_inquiry_sent", { category });
        } else {
            showToast(data.message || "Failed to submit inquiry", "error");
        }
    } catch (err) {
        showToast("Error connecting to server", "error");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "✉️ Send Inquiry";
        }
    }
}

// ==============================================================================
// AI STUDIO / UPLOAD WORKFLOW
// ==============================================================================

function initDropzone() {
    const dropzone = document.getElementById("uploadDropzone");
    const fileInput = document.getElementById("catalogImageInput");
    if (!dropzone || !fileInput) return;

    dropzone.addEventListener("click", () => {
        if (!canEdit()) {
            openAuthModal("login");
            showToast("Please sign in as Editor or Admin to upload images", "warning");
            return;
        }
        fileInput.click();
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add("dragover");
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove("dragover");
        });
    });

    dropzone.addEventListener("drop", (e) => {
        if (!canEdit()) {
            openAuthModal("login");
            return;
        }
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            handleImageSelection(files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleImageSelection(e.target.files[0]);
        }
    });

    const clearBtn = document.getElementById("clearSelectedImageBtn");
    if (clearBtn) clearBtn.addEventListener("click", resetStudioUploadState);

    const startBtn = document.getElementById("startAiAnalysisBtn");
    if (startBtn) startBtn.addEventListener("click", runAiCatalogExtraction);
}

function handleImageSelection(file) {
    if (!file.type.startsWith("image/")) {
        showToast("Please select a valid image file (PNG, JPG, WEBP, etc.)", "warning");
        return;
    }

    appState.selectedFile = file;

    const dropzone = document.getElementById("uploadDropzone");
    const previewBox = document.getElementById("uploadPreviewBox");
    const imgPreview = document.getElementById("selectedImgPreview");
    const nameEl = document.getElementById("previewFilename");
    const sizeEl = document.getElementById("previewFilesize");

    if (dropzone) dropzone.style.display = "none";
    if (previewBox) previewBox.style.display = "block";
    if (nameEl) nameEl.textContent = file.name;
    if (sizeEl) sizeEl.textContent = formatBytes(file.size);

    const reader = new FileReader();
    reader.onload = (e) => {
        if (imgPreview) imgPreview.src = e.target.result;
    };
    reader.readAsDataURL(file);

    setWorkflowStep(2);
}

function resetStudioUploadState() {
    appState.selectedFile = null;
    appState.currentDraft = null;

    const fileInput = document.getElementById("catalogImageInput");
    if (fileInput) fileInput.value = "";

    const dropzone = document.getElementById("uploadDropzone");
    const previewBox = document.getElementById("uploadPreviewBox");
    const progressCard = document.getElementById("aiProgressCard");
    const reviewWorkspace = document.getElementById("reviewWorkspace");

    if (dropzone) dropzone.style.display = "block";
    if (previewBox) previewBox.style.display = "none";
    if (progressCard) progressCard.style.display = "none";
    if (reviewWorkspace) reviewWorkspace.style.display = "none";

    setWorkflowStep(1);
}

function setWorkflowStep(stepNum) {
    const steps = [
        document.getElementById("step1Indicator"),
        document.getElementById("step2Indicator"),
        document.getElementById("step3Indicator"),
        document.getElementById("step4Indicator")
    ];

    steps.forEach((el, idx) => {
        if (!el) return;
        const current = idx + 1;
        el.classList.remove("active", "completed");
        if (current === stepNum) {
            el.classList.add("active");
        } else if (current < stepNum) {
            el.classList.add("completed");
        }
    });
}

async function runAiCatalogExtraction() {
    if (!appState.selectedFile) {
        showToast("Please upload an image first", "warning");
        return;
    }

    const previewBox = document.getElementById("uploadPreviewBox");
    const progressCard = document.getElementById("aiProgressCard");
    const reviewWorkspace = document.getElementById("reviewWorkspace");
    const progressStatus = document.getElementById("aiProgressStatus");
    const progressFill = document.getElementById("aiProgressBarFill");

    if (previewBox) previewBox.style.display = "none";
    if (progressCard) progressCard.style.display = "block";
    if (reviewWorkspace) reviewWorkspace.style.display = "none";

    setWorkflowStep(3);

    const stages = [
        { pct: "25%", text: "Preprocessing and optimizing image with Pillow..." },
        { pct: "55%", text: "Running Multimodal AI Vision analysis with Gemini..." },
        { pct: "85%", text: "Extracting packaging text, specifications and brand..." },
        { pct: "95%", text: "Validating structured catalog schema..." }
    ];

    let stageIdx = 0;
    const interval = setInterval(() => {
        if (stageIdx < stages.length) {
            if (progressFill) progressFill.style.width = stages[stageIdx].pct;
            if (progressStatus) progressStatus.textContent = stages[stageIdx].text;
            stageIdx++;
        }
    }, 900);

    try {
        const formData = new FormData();
        formData.append("image", appState.selectedFile);
        formData.append("save_immediately", "false");

        const modelSelect = document.getElementById("aiModelSelect");
        if (modelSelect) formData.append("model", modelSelect.value);

        const res = await fetch(`${API_BASE}/upload`, {
            method: "POST",
            body: formData
        });

        clearInterval(interval);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Upload failed");

        if (progressFill) progressFill.style.width = "100%";
        if (progressStatus) progressStatus.textContent = "Catalog details generated successfully!";

        appState.currentDraft = data.draft;

        setTimeout(() => {
            if (progressCard) progressCard.style.display = "none";
            populateReviewWorkspace(data.draft, data.image_metadata);
            if (reviewWorkspace) reviewWorkspace.style.display = "grid";
            setWorkflowStep(3);

            if (data.warning) {
                showToast(`Notice: ${data.warning}`, "warning");
            } else {
                showToast("Catalog draft generated! Review details below.", "success");
            }
        }, 500);

    } catch (err) {
        clearInterval(interval);
        console.error("AI analysis error:", err);
        if (progressCard) progressCard.style.display = "none";
        if (previewBox) previewBox.style.display = "block";
        showToast(`Extraction error: ${err.message}`, "error");
    }
}

function populateReviewWorkspace(draft, imgMeta) {
    const previewImg = document.getElementById("reviewLargeImage");
    if (previewImg && draft.image_path) previewImg.src = draft.image_path;

    const mediaMeta = document.getElementById("reviewMediaMeta");
    if (mediaMeta && imgMeta) {
        mediaMeta.innerHTML = `
            <div><b>Dimensions:</b> ${imgMeta.width} x ${imgMeta.height} px</div>
            <div><b>Format:</b> ${imgMeta.format} • <b>Size:</b> ${imgMeta.file_size_formatted}</div>
            <div><b>Engine:</b> ${draft.extraction_source || "Local Analyzer"}</div>
        `;
    }

    document.getElementById("reviewProductName").value = draft.product_name || "";
    document.getElementById("reviewBrand").value = draft.brand || "";
    document.getElementById("reviewModel").value = draft.model || "";
    document.getElementById("reviewCategory").value = draft.category || "General";
    document.getElementById("reviewPrice").value = draft.price || "";
    document.getElementById("reviewDimensions").value = draft.dimensions || "";
    document.getElementById("reviewShortDesc").value = draft.short_description || "";
    document.getElementById("reviewDesc").value = draft.description || "";
    document.getElementById("reviewSeoTitle").value = draft.seo_title || "";
    document.getElementById("reviewSeoDesc").value = draft.seo_description || "";

    renderDynamicFeaturesList(draft.features || []);
    renderDynamicSpecsList(draft.specifications || {});
    renderDynamicSellingPoints(draft.selling_points || []);
    document.getElementById("reviewTags").value = (draft.tags || []).join(", ");
}

function renderDynamicFeaturesList(features) {
    const container = document.getElementById("dynamicFeaturesContainer");
    if (!container) return;
    container.innerHTML = "";

    features.forEach(feat => {
        const row = document.createElement("div");
        row.className = "dynamic-row";
        row.innerHTML = `
            <input type="text" class="form-control feature-input" value="${escapeHtml(feat)}" placeholder="Feature description">
            <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Feature">&times;</button>
        `;
        container.appendChild(row);
    });
}

function addFeatureRow() {
    const container = document.getElementById("dynamicFeaturesContainer");
    if (!container) return;
    const row = document.createElement("div");
    row.className = "dynamic-row";
    row.innerHTML = `
        <input type="text" class="form-control feature-input" placeholder="New feature bullet...">
        <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Feature">&times;</button>
    `;
    container.appendChild(row);
    row.querySelector("input").focus();
}

function renderDynamicSpecsList(specs) {
    const container = document.getElementById("dynamicSpecsContainer");
    if (!container) return;
    container.innerHTML = "";

    Object.entries(specs).forEach(([k, v]) => {
        const row = document.createElement("div");
        row.className = "dynamic-row";
        row.innerHTML = `
            <input type="text" class="form-control spec-key-input" style="flex:1;" value="${escapeHtml(k)}" placeholder="Spec Name">
            <input type="text" class="form-control spec-val-input" style="flex:2;" value="${escapeHtml(v)}" placeholder="Specification Detail">
            <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Specification">&times;</button>
        `;
        container.appendChild(row);
    });
}

function addSpecRow() {
    const container = document.getElementById("dynamicSpecsContainer");
    if (!container) return;
    const row = document.createElement("div");
    row.className = "dynamic-row";
    row.innerHTML = `
        <input type="text" class="form-control spec-key-input" style="flex:1;" placeholder="Attribute (e.g. Battery)">
        <input type="text" class="form-control spec-val-input" style="flex:2;" placeholder="Detail (e.g. 5000 mAh)">
        <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Specification">&times;</button>
    `;
    container.appendChild(row);
    row.querySelector("input").focus();
}

function renderDynamicSellingPoints(usp) {
    const container = document.getElementById("dynamicUspContainer");
    if (!container) return;
    container.innerHTML = "";

    usp.forEach(item => {
        const row = document.createElement("div");
        row.className = "dynamic-row";
        row.innerHTML = `
            <input type="text" class="form-control usp-input" value="${escapeHtml(item)}" placeholder="Selling point / USP">
            <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Point">&times;</button>
        `;
        container.appendChild(row);
    });
}

function addUspRow() {
    const container = document.getElementById("dynamicUspContainer");
    if (!container) return;
    const row = document.createElement("div");
    row.className = "dynamic-row";
    row.innerHTML = `
        <input type="text" class="form-control usp-input" placeholder="Commercial advantage / selling point...">
        <button type="button" class="btn-icon" onclick="this.parentElement.remove()" title="Remove Point">&times;</button>
    `;
    container.appendChild(row);
    row.querySelector("input").focus();
}

async function saveReviewedCatalogItem() {
    try {
        const prodName = document.getElementById("reviewProductName").value.trim();
        if (!prodName) {
            showToast("Product name cannot be empty", "warning");
            return;
        }

        const features = [];
        document.querySelectorAll("#dynamicFeaturesContainer .feature-input").forEach(inp => {
            const val = inp.value.trim();
            if (val) features.push(val);
        });

        const specifications = {};
        document.querySelectorAll("#dynamicSpecsContainer .dynamic-row").forEach(row => {
            const k = row.querySelector(".spec-key-input")?.value.trim();
            const v = row.querySelector(".spec-val-input")?.value.trim();
            if (k) specifications[k] = v || "";
        });

        const usp = [];
        document.querySelectorAll("#dynamicUspContainer .usp-input").forEach(inp => {
            const val = inp.value.trim();
            if (val) usp.push(val);
        });

        const tagsRaw = document.getElementById("reviewTags")?.value || "";
        const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);

        const payload = {
            product_name: prodName,
            brand: document.getElementById("reviewBrand").value.trim(),
            model: document.getElementById("reviewModel").value.trim() || null,
            category: document.getElementById("reviewCategory").value.trim() || "General",
            price: document.getElementById("reviewPrice").value.trim() || "N/A",
            dimensions: document.getElementById("reviewDimensions").value.trim() || "N/A",
            short_description: document.getElementById("reviewShortDesc").value.trim(),
            description: document.getElementById("reviewDesc").value.trim(),
            features: features,
            specifications: specifications,
            selling_points: usp,
            tags: tags,
            seo_title: document.getElementById("reviewSeoTitle").value.trim(),
            seo_description: document.getElementById("reviewSeoDesc").value.trim(),
            image_path: appState.currentDraft?.image_path || "",
            extraction_source: appState.currentDraft?.extraction_source || "manual",
            status: "active"
        };

        const res = await fetch(`${API_BASE}/product`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed to save product");

        setWorkflowStep(4);
        showToast("Product saved successfully to catalog!", "success");
        resetStudioUploadState();
        switchTab("catalogExplorer");

    } catch (err) {
        console.error("Save error:", err);
        showToast(`Save error: ${err.message}`, "error");
    }
}

// ==============================================================================
// PRODUCT DETAILS MODAL & QUICK-VIEW
// ==============================================================================

async function openProductModal(productId) {
    try {
        const res = await fetch(`${API_BASE}/product/${productId}`);
        if (!res.ok) throw new Error("Product not found");
        const p = await res.json();
        appState.selectedCheckoutProduct = p;

        const modal = document.getElementById("productViewModal");
        const body = document.getElementById("productViewModalBody");
        const title = document.getElementById("productViewModalTitle");
        const pdfLink = document.getElementById("modalPdfDownloadLink");

        if (title) title.textContent = p.product_name;
        if (pdfLink) pdfLink.href = `/export/pdf/${p.id}`;

        const imageSrc = p.image_path || "/static/uploads/suchit_asset_4_boat.jpg";
        const imgHtml = `<img src="${escapeHtml(imageSrc)}" style="max-height:280px;width:100%;object-fit:contain;border-radius:8px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:1rem;">`;

        const specs = p.specifications || {};
        const specRows = Object.entries(specs).map(([k, v]) => `
            <tr>
                <td style="padding:0.4rem 0.6rem;font-weight:600;border-bottom:1px solid #edf2f7;width:35%;">${escapeHtml(k)}</td>
                <td style="padding:0.4rem 0.6rem;border-bottom:1px solid #edf2f7;">${escapeHtml(v)}</td>
            </tr>
        `).join("");

        const featuresList = (p.features || []).map(f => `<li style="margin-bottom:0.3rem;">${escapeHtml(f)}</li>`).join("");

        const uspList = (p.selling_points || []).map(u => `
            <div style="display:flex;align-items:center;gap:0.4rem;font-size:0.88rem;color:#059669;margin-bottom:0.25rem;">
                <span>✓</span> <b>${escapeHtml(u)}</b>
            </div>
        `).join("");

        body.innerHTML = `
            ${imgHtml}
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
                <div>
                    <span class="badge badge-category">${escapeHtml(p.category)}</span>
                    <span style="font-size:0.85rem;color:#64748b;margin-left:0.5rem;">Brand: <b>${escapeHtml(p.brand)}</b></span>
                </div>
                <div style="font-size:1.4rem;font-weight:800;color:#059669;">${escapeHtml(p.price)}</div>
            </div>

            ${p.short_description ? `<div style="background:#f8fafc;padding:0.75rem 1rem;border-left:3px solid #2563eb;border-radius:4px;font-style:italic;margin-bottom:1rem;">${escapeHtml(p.short_description)}</div>` : ''}
            ${p.description ? `<div style="font-size:0.92rem;line-height:1.6;margin-bottom:1.25rem;color:#334155;">${escapeHtml(p.description)}</div>` : ''}
            ${uspList ? `<div style="margin-bottom:1.25rem;"><b>Selling Highlights:</b><div style="margin-top:0.4rem;">${uspList}</div></div>` : ''}
            ${featuresList ? `<div style="margin-bottom:1.25rem;"><b>Key Features:</b><ul style="padding-left:1.2rem;margin-top:0.4rem;font-size:0.9rem;color:#334155;">${featuresList}</ul></div>` : ''}
            ${specRows ? `<div style="margin-bottom:1.25rem;"><b>Technical Specifications:</b><table style="width:100%;border-collapse:collapse;margin-top:0.5rem;font-size:0.88rem;"><tbody>${specRows}</tbody></table></div>` : ''}

            <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:0.75rem;flex-wrap:wrap;">
                <div>Dimensions: ${escapeHtml(p.dimensions || 'N/A')}</div>
                <div>ID: #${p.id}</div>
            </div>
        `;

        modal.classList.add("active");
        trackAnalyticsEvent("view_product_modal", { product_id: p.id, product_name: p.product_name });
    } catch (err) {
        showToast("Failed to load product details", "error");
    }
}

function closeProductModal() {
    const modal = document.getElementById("productViewModal");
    if (modal) modal.classList.remove("active");
}

function openCheckoutForProduct() {
    closeProductModal();
    switchTab("checkoutSection");
}

// ==============================================================================
// EDIT & DELETE MODALS
// ==============================================================================

async function openEditModal(productId) {
    if (!canEdit()) {
        openAuthModal("login");
        showToast("Admin or Editor privileges required to edit products", "warning");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/product/${productId}`);
        if (!res.ok) throw new Error("Product not found");
        const p = await res.json();

        document.getElementById("editProductId").value = p.id;
        document.getElementById("editProductName").value = p.product_name || "";
        document.getElementById("editBrand").value = p.brand || "";
        document.getElementById("editModel").value = p.model || "";
        document.getElementById("editCategory").value = p.category || "General";
        document.getElementById("editPrice").value = p.price || "";
        document.getElementById("editDimensions").value = p.dimensions || "";
        document.getElementById("editShortDesc").value = p.short_description || "";
        document.getElementById("editDesc").value = p.description || "";
        document.getElementById("editFeatures").value = (p.features || []).join("\n");
        document.getElementById("editTags").value = (p.tags || []).join(", ");

        const modal = document.getElementById("productEditModal");
        if (modal) modal.classList.add("active");
    } catch (err) {
        showToast("Failed to load product for editing", "error");
    }
}

function closeEditModal() {
    const modal = document.getElementById("productEditModal");
    if (modal) modal.classList.remove("active");
}

async function handleUpdateProductSubmit(e) {
    e.preventDefault();
    const id = document.getElementById("editProductId").value;
    if (!id) return;

    try {
        const featuresRaw = document.getElementById("editFeatures").value;
        const features = featuresRaw.split("\n").map(f => f.trim()).filter(Boolean);

        const tagsRaw = document.getElementById("editTags").value;
        const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);

        const payload = {
            product_name: document.getElementById("editProductName").value.trim(),
            brand: document.getElementById("editBrand").value.trim(),
            model: document.getElementById("editModel").value.trim() || null,
            category: document.getElementById("editCategory").value.trim() || "General",
            price: document.getElementById("editPrice").value.trim(),
            dimensions: document.getElementById("editDimensions").value.trim(),
            short_description: document.getElementById("editShortDesc").value.trim(),
            description: document.getElementById("editDesc").value.trim(),
            features: features,
            tags: tags
        };

        const res = await fetch(`${API_BASE}/product/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Update failed");

        showToast("Product updated successfully!", "success");
        closeEditModal();
        loadCatalogData();
    } catch (err) {
        showToast(`Update error: ${err.message}`, "error");
    }
}

let pendingDeleteId = null;

function confirmDeleteProduct(id, name) {
    if (!canEdit()) {
        openAuthModal("login");
        showToast("Admin or Editor privileges required to delete items", "warning");
        return;
    }

    pendingDeleteId = id;
    const nameEl = document.getElementById("deleteProductName");
    if (nameEl) nameEl.textContent = name;

    const modal = document.getElementById("productDeleteModal");
    if (modal) modal.classList.add("active");
}

function closeDeleteModal() {
    pendingDeleteId = null;
    const modal = document.getElementById("productDeleteModal");
    if (modal) modal.classList.remove("active");
}

async function executeProductDeletion() {
    if (!pendingDeleteId) return;

    try {
        const res = await fetch(`${API_BASE}/product/${pendingDeleteId}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Delete failed");

        showToast("Product deleted successfully", "success");
        closeDeleteModal();
        loadCatalogData();
    } catch (err) {
        showToast(`Delete error: ${err.message}`, "error");
    }
}

// ==============================================================================
// SETTINGS, API KEY PROTECTION & DATABASE BACKUPS
// ==============================================================================

function initSettingsAndBackups() {
    const testBtn = document.getElementById("testApiKeyBtn");
    const saveBtn = document.getElementById("saveSettingsBtn");

    if (testBtn) testBtn.addEventListener("click", runApiKeyTest);
    if (saveBtn) saveBtn.addEventListener("click", runSaveApiKey);
}

async function loadSettingsHealth() {
    try {
        const res = await fetch(`${API_BASE}/api/health`);
        if (res.ok) {
            const h = await res.json();
            const display = document.getElementById("apiKeyMaskedDisplay");
            if (display) {
                if (h.ai_engine?.gemini_api_key_configured) {
                    display.innerHTML = `<span style="color:#059669;font-weight:600;">✓ Configured & Encrypted: ${escapeHtml(h.ai_engine.masked_key || 'AIzaSy...****')}</span>`;
                } else {
                    display.innerHTML = `<span style="color:#d97706;font-weight:600;">⚠️ Not Configured (Using Offline Heuristics Fallback)</span>`;
                }
            }
        }
    } catch (err) {
        console.error("Health load error:", err);
    }
}

async function runApiKeyTest() {
    const keyInput = document.getElementById("settingsApiKeyInput");
    const resultBox = document.getElementById("apiKeyTestResult");
    const key = keyInput ? keyInput.value.trim() : "";

    if (resultBox) {
        resultBox.style.display = "block";
        resultBox.innerHTML = `<span style="color:#2563eb;">Testing connectivity with Google GenAI SDK...</span>`;
    }

    try {
        const res = await fetch(`${API_BASE}/api/settings/test-key`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: key })
        });

        const data = await res.json();
        if (data.success) {
            resultBox.innerHTML = `<span style="color:#059669;font-weight:600;">✓ ${escapeHtml(data.message)}</span>`;
            showToast("Gemini API connection verified!", "success");
        } else {
            resultBox.innerHTML = `<span style="color:#dc2626;font-weight:600;">✗ ${escapeHtml(data.message)}</span>`;
            showToast("API Key verification failed", "error");
        }
    } catch (err) {
        if (resultBox) {
            resultBox.innerHTML = `<span style="color:#dc2626;">Error: ${escapeHtml(err.message)}</span>`;
        }
    }
}

async function runSaveApiKey() {
    if (!isAdmin()) {
        openAuthModal("login");
        showToast("Administrator privileges required to update API keys", "warning");
        return;
    }

    const keyInput = document.getElementById("settingsApiKeyInput");
    const key = keyInput ? keyInput.value.trim() : "";

    try {
        const res = await fetch(`${API_BASE}/api/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ gemini_api_key: key })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.message || "Save failed");

        showToast("Gemini API key updated and encrypted!", "success");
        loadSettingsHealth();
        if (keyInput) keyInput.value = "";
    } catch (err) {
        showToast(`Error saving key: ${err.message}`, "error");
    }
}

async function saveAnalyticsSettings() {
    if (!isAdmin()) {
        openAuthModal("login");
        showToast("Administrator privileges required", "warning");
        return;
    }

    const gaId = document.getElementById("settingsGaIdInput")?.value.trim() || "";
    try {
        const res = await fetch(`${API_BASE}/api/settings/analytics`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ google_analytics_id: gaId })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Google Analytics configuration saved!", "success");
        } else {
            showToast(data.message || "Save failed", "error");
        }
    } catch (err) {
        showToast("Error updating analytics", "error");
    }
}

async function saveDomainEmailSettings() {
    if (!isAdmin()) {
        openAuthModal("login");
        showToast("Administrator privileges required", "warning");
        return;
    }

    const domainEmail = document.getElementById("settingsDomainEmailInput")?.value.trim() || "";
    const mailServer = document.getElementById("settingsMailServerInput")?.value.trim() || "";
    const mailPort = document.getElementById("settingsMailPortInput")?.value.trim() || "587";

    try {
        const res = await fetch(`${API_BASE}/api/settings/email`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain_email: domainEmail, mail_server: mailServer, mail_port: mailPort })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Domain email configuration updated!", "success");
        } else {
            showToast(data.message || "Save failed", "error");
        }
    } catch (err) {
        showToast("Error updating email settings", "error");
    }
}

async function loadBackupsList() {
    const container = document.getElementById("backupsListContainer");
    if (!container) return;

    try {
        const res = await fetch(`${API_BASE}/api/backups`);
        if (!res.ok) {
            container.innerHTML = `<div style="padding:0.75rem;color:#64748b;font-size:0.85rem;text-align:center;">Sign in as Admin to manage backups</div>`;
            return;
        }

        const backups = await res.json();
        if (backups.length === 0) {
            container.innerHTML = `<div style="padding:0.75rem;color:#64748b;font-size:0.85rem;text-align:center;">No snapshots yet. Click "Create Backup Now".</div>`;
            return;
        }

        let html = `<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><tbody>`;
        backups.forEach(b => {
            html += `
                <tr style="border-bottom:1px solid #e2e8f0;">
                    <td style="padding:0.5rem 0.65rem;"><b>${escapeHtml(b.filename)}</b><br><span style="color:#64748b;">${escapeHtml(b.created_at)} • ${escapeHtml(b.size_formatted)} (${b.product_count} items)</span></td>
                    <td style="padding:0.5rem 0.65rem;text-align:right;white-space:nowrap;">
                        <a href="/api/backups/download/${encodeURIComponent(b.filename)}" class="btn btn-secondary btn-sm" style="padding:0.2rem 0.5rem;font-size:0.75rem;" download>Download</a>
                        <button class="btn btn-danger btn-sm" style="padding:0.2rem 0.5rem;font-size:0.75rem;margin-left:0.25rem;" onclick="triggerRestoreBackup('${escapeJs(b.filename)}')">Restore</button>
                    </td>
                </tr>
            `;
        });
        html += `</tbody></table>`;
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<div style="padding:0.75rem;color:#dc2626;font-size:0.85rem;">Error loading backups</div>`;
    }
}

async function triggerCreateBackup() {
    if (!isAdmin()) {
        openAuthModal("login");
        showToast("Administrator privileges required to create database backups", "warning");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/backups/create`, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Database snapshot created successfully!", "success");
            loadBackupsList();
        } else {
            showToast(data.message || "Backup failed", "error");
        }
    } catch (err) {
        showToast("Error creating backup", "error");
    }
}

async function triggerRestoreBackup(filename) {
    if (!isAdmin()) {
        openAuthModal("login");
        showToast("Administrator privileges required", "warning");
        return;
    }

    if (!confirm(`CAUTION: Restoring from snapshot '${filename}' will roll back current catalog data. A pre-restore safety snapshot will be created automatically. Proceed?`)) {
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/backups/restore/${encodeURIComponent(filename)}`, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Database successfully restored!", "success");
            loadCatalogData();
            loadBackupsList();
        } else {
            showToast(data.message || "Restore failed", "error");
        }
    } catch (err) {
        showToast("Error during restore operation", "error");
    }
}

// ==============================================================================
// SECURITY PADLOCK MODAL
// ==============================================================================

function openSecurityModal() {
    const modal = document.getElementById("securityModal");
    if (modal) modal.classList.add("active");
}

function closeSecurityModal() {
    const modal = document.getElementById("securityModal");
    if (modal) modal.classList.remove("active");
}

function closeAllModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => m.classList.remove("active"));
}

// ==============================================================================
// UTILITIES & ANALYTICS
// ==============================================================================

function trackAnalyticsEvent(eventName, params = {}) {
    if (typeof window.gtag === "function") {
        try {
            window.gtag("event", eventName, params);
        } catch (e) {
            console.debug("GA4 event tracked:", eventName, params);
        }
    }
}

function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    let icon = "ℹ️";
    if (type === "success") icon = "✓";
    if (type === "error") icon = "✕";
    if (type === "warning") icon = "⚠️";

    toast.innerHTML = `
        <span style="font-weight:700;">${icon}</span>
        <div class="toast-message">${escapeHtml(message)}</div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(-100%)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeJs(str) {
    if (!str) return "";
    return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"');
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
