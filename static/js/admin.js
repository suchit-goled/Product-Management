/**
 * Suchit Catalog - Role-Gated Administrator Console Module (Served ONLY to verified Admin sessions)
 * Controls encrypted API keys, Analytics, Domain SMTP email, ACID Database Backups, and Message Queue audit.
 */

document.addEventListener("DOMContentLoaded", () => {
    bindAdminControls();
});

function bindAdminControls() {
    const testBtn = document.getElementById("testApiKeyBtn");
    const saveKeyBtn = document.getElementById("saveSettingsBtn");
    const saveGaBtn = document.getElementById("saveAnalyticsBtn");
    const saveEmailBtn = document.getElementById("saveEmailSettingsBtn");
    const createBackupBtn = document.getElementById("createBackupBtn");

    if (testBtn) testBtn.addEventListener("click", runApiKeyTest);
    if (saveKeyBtn) saveKeyBtn.addEventListener("click", runSaveApiKey);
    if (saveGaBtn) saveGaBtn.addEventListener("click", saveAnalyticsSettings);
    if (saveEmailBtn) saveEmailBtn.addEventListener("click", saveDomainEmailSettings);
    if (createBackupBtn) createBackupBtn.addEventListener("click", triggerCreateBackup);

    document.addEventListener("click", (e) => {
        const restoreBtn = e.target.closest("[data-restore-backup]");
        if (restoreBtn) {
            const fname = restoreBtn.getAttribute("data-restore-backup");
            if (fname) triggerRestoreBackup(fname);
        }
    });
}

window.refreshAdminPanel = function () {
    loadAdminDiagnostics();
    loadBackupsList();
    loadAdminOutboxAndInquiries();
};

async function loadAdminDiagnostics() {
    const display = document.getElementById("apiKeyMaskedDisplay");
    try {
        const res = await window.secureFetch("/gw/admin/diagnostics");
        if (!res.ok) return;
        const h = await res.json();
        if (display) {
            if (h.gemini?.configured) {
                display.innerHTML = `<span style="color:#059669;font-weight:600;">✓ Configured &amp; Masked: ${window.escapeHtml(h.gemini.api_key_masked)}</span>`;
            } else {
                display.innerHTML = `<span style="color:#d97706;font-weight:600;">⚠️ Key Missing (Local Fallback Active)</span>`;
            }
        }
        const queueBox = document.getElementById("adminQueueMetricsBox");
        if (queueBox && h.queue) {
            queueBox.innerHTML = `
                <span class="spec-chip"><b>DB Mode:</b> ${window.escapeHtml(h.database?.mode)}</span>
                <span class="spec-chip"><b>Cache:</b> Active (${h.cache?.catalog_ttl_seconds}s TTL)</span>
                <span class="spec-chip"><b>Queue Pending:</b> ${h.queue.pending}</span>
                <span class="spec-chip"><b>Emails Dispatched:</b> ${h.queue.outbox_total}</span>
            `;
        }
    } catch (err) {
        console.debug("Diagnostics load error:", err);
    }
}

async function runApiKeyTest() {
    const keyInput = document.getElementById("settingsApiKeyInput");
    const resultBox = document.getElementById("apiKeyTestResult");
    const key = keyInput ? keyInput.value.trim() : "";

    if (resultBox) {
        resultBox.style.display = "block";
        resultBox.innerHTML = `<span style="color:#2563eb;">Testing encrypted connectivity with Gemini SDK...</span>`;
    }

    try {
        const res = await window.secureFetch("/gw/admin/settings/test-key", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: key })
        });
        const data = await res.json();
        if (resultBox) {
            resultBox.innerHTML = data.success
                ? `<span style="color:#059669;font-weight:600;">✓ ${window.escapeHtml(data.message)}</span>`
                : `<span style="color:#dc2626;font-weight:600;">✗ ${window.escapeHtml(data.message)}</span>`;
        }
        window.showToast(data.message, data.success ? "success" : "error");
    } catch (err) {
        window.showToast("Connectivity check error", "error");
    }
}

async function runSaveApiKey() {
    const inp = document.getElementById("settingsApiKeyInput");
    const key = inp ? inp.value.trim() : "";
    try {
        const res = await window.secureFetch("/gw/admin/settings/key", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ gemini_api_key: key })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.message || "Save failed");
        window.showToast("API key saved securely server-side", "success");
        if (inp) inp.value = "";
        loadAdminDiagnostics();
    } catch (err) {
        window.showToast(`Error: ${err.message}`, "error");
    }
}

async function saveAnalyticsSettings() {
    const gaId = document.getElementById("settingsGaIdInput")?.value.trim() || "";
    try {
        const res = await window.secureFetch("/gw/admin/settings/analytics", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ google_analytics_id: gaId })
        });
        const data = await res.json();
        window.showToast(data.message, res.ok && data.success ? "success" : "error");
    } catch (err) {
        window.showToast("Failed to save GA4 ID", "error");
    }
}

async function saveDomainEmailSettings() {
    const domain_email = document.getElementById("settingsDomainEmailInput")?.value.trim() || "";
    const mail_server = document.getElementById("settingsMailServerInput")?.value.trim() || "";
    const mail_port = document.getElementById("settingsMailPortInput")?.value.trim() || "587";

    try {
        const res = await window.secureFetch("/gw/admin/settings/email", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain_email, mail_server, mail_port })
        });
        const data = await res.json();
        window.showToast(data.message, res.ok && data.success ? "success" : "error");
    } catch (err) {
        window.showToast("Failed to save email config", "error");
    }
}

async function loadBackupsList() {
    const container = document.getElementById("backupsListContainer");
    if (!container) return;
    try {
        const res = await window.secureFetch("/gw/admin/backups");
        if (!res.ok) return;
        const backups = await res.json();
        if (!backups.length) {
            container.innerHTML = `<div style="padding:0.75rem;text-align:center;color:#64748b;font-size:0.85rem;">No snapshots created yet.</div>`;
            return;
        }
        const rows = backups.map(b => `
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:0.5rem 0.65rem;">
                    <b>${window.escapeHtml(b.filename)}</b><br>
                    <span style="color:#64748b;">${window.escapeHtml(b.created_at)} &bull; ${window.escapeHtml(b.size_formatted)} (${b.product_count} SKUs)</span>
                </td>
                <td style="padding:0.5rem 0.65rem;text-align:right;white-space:nowrap;">
                    <a href="/gw/admin/backups/download/${encodeURIComponent(b.filename)}" class="btn btn-secondary btn-sm" style="padding:0.25rem 0.55rem;font-size:0.75rem;" download>Download</a>
                    <button type="button" class="btn btn-danger btn-sm" data-restore-backup="${window.escapeHtml(b.filename)}" style="padding:0.25rem 0.55rem;font-size:0.75rem;margin-left:0.25rem;">Restore</button>
                </td>
            </tr>
        `).join("");
        container.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><tbody>${rows}</tbody></table>`;
    } catch (err) {
        container.innerHTML = `<div style="padding:0.75rem;color:#dc2626;">Error loading backups</div>`;
    }
}

async function triggerCreateBackup() {
    try {
        const res = await window.secureFetch("/gw/admin/backups/create", { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
            window.showToast("ACID backup snapshot created!", "success");
            loadBackupsList();
            loadAdminDiagnostics();
        } else {
            window.showToast(data.message || "Backup failed", "error");
        }
    } catch (err) {
        window.showToast("Backup error", "error");
    }
}

async function triggerRestoreBackup(filename) {
    if (!confirm(`Restore database from '${filename}'? A pre-restore safety snapshot will be created automatically.`)) return;
    try {
        const res = await window.secureFetch(`/gw/admin/backups/restore/${encodeURIComponent(filename)}`, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
            window.showToast("Database restored & cache invalidated!", "success");
            window.loadCatalogData();
            loadBackupsList();
        } else {
            window.showToast(data.message || "Restore failed", "error");
        }
    } catch (err) {
        window.showToast("Restore failed", "error");
    }
}

async function loadAdminOutboxAndInquiries() {
    const outboxEl = document.getElementById("adminOutboxList");
    const inqEl = document.getElementById("adminInquiriesList");

    try {
        const [outRes, inqRes] = await Promise.all([
            window.secureFetch("/gw/admin/outbox"),
            window.secureFetch("/gw/admin/inquiries")
        ]);

        if (outboxEl && outRes.ok) {
            const d = await outRes.json();
            const items = (d.outbox || []).slice(0, 8);
            outboxEl.innerHTML = items.length
                ? items.map(m => `<div style="padding:0.45rem 0;border-bottom:1px solid #e2e8f0;font-size:0.8rem;"><b>${window.escapeHtml(m.subject)}</b> &rarr; ${window.escapeHtml(m.recipient)} <span class="badge badge-verified">${window.escapeHtml(m.delivery_mode)}</span></div>`).join("")
                : `<span style="font-size:0.82rem;color:#64748b;">No queued deliveries logged yet.</span>`;
        }

        if (inqEl && inqRes.ok) {
            const list = (await inqRes.json()).slice(0, 8);
            inqEl.innerHTML = list.length
                ? list.map(q => `<div style="padding:0.45rem 0;border-bottom:1px solid #e2e8f0;font-size:0.8rem;"><b>INQ-${String(q.id).padStart(4, "0")}: ${window.escapeHtml(q.subject)}</b> from ${window.escapeHtml(q.name)} (${window.escapeHtml(q.email)})</div>`).join("")
                : `<span style="font-size:0.82rem;color:#64748b;">No customer inquiries yet.</span>`;
        }
    } catch (err) {
        console.debug("Admin outbox/inquiries load error:", err);
    }
}
