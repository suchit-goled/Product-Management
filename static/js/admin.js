/**
 * Product Catalog - Role-Gated Administrator Console Module (Served ONLY to verified Admin sessions)
 * Privacy-safe operational telemetry and server-side snapshot triggers.
 * Strictly zero API keys, zero raw credentials, zero PII, and zero DB downloads shipped to frontend.
 */

document.addEventListener("DOMContentLoaded", () => {
    bindAdminControls();
});

function bindAdminControls() {
    const createBackupBtn = document.getElementById("createBackupBtn");
    if (createBackupBtn) createBackupBtn.addEventListener("click", triggerCreateBackup);
}

window.refreshAdminPanel = function () {
    loadAdminDiagnostics();
    loadBackupsList();
    loadAdminOutboxAndInquiries();
};

async function loadAdminDiagnostics() {
    const display = document.getElementById("aiEngineStatusDisplay");
    try {
        const res = await window.secureFetch("/gw/admin/diagnostics");
        if (!res.ok) return;
        const h = await res.json();
        if (display) {
            const groqOk = Boolean(h.groq?.configured);
            const geminiOk = Boolean(h.gemini?.configured);
            const badges = [
                groqOk
                    ? `<span style="color:#059669;font-weight:600;">✓ Groq AI: Server-Configured</span>`
                    : `<span style="color:#d97706;font-weight:600;">⚠️ Groq AI: Set GROQ_API_KEY in server .env</span>`,
                geminiOk
                    ? `<span style="color:#059669;font-weight:600;">✓ Gemini AI: Server-Configured</span>`
                    : `<span style="color:#64748b;font-weight:500;">• Gemini AI: Fallback Inactive</span>`
            ];
            display.innerHTML = `<div style="display:flex;flex-direction:column;gap:0.25rem;">${badges.join("")}</div>`;
        }
        const queueBox = document.getElementById("adminQueueMetricsBox");
        if (queueBox && h.queue) {
            queueBox.innerHTML = `
                <span class="spec-chip"><b>DB Mode:</b> ${window.escapeHtml(h.database?.mode)}</span>
                <span class="spec-chip"><b>Cache:</b> Active (${Number(h.cache?.catalog_ttl_seconds) || 0}s TTL)</span>
                <span class="spec-chip"><b>Queue Pending:</b> ${Number(h.queue.pending) || 0}</span>
                <span class="spec-chip"><b>Emails Dispatched:</b> ${Number(h.queue.outbox_total) || 0}</span>
            `;
        }
    } catch (err) {
        console.debug("Diagnostics load error:", err);
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
                    <b>Snapshot (${window.escapeHtml(b.created_at)})</b><br>
                    <span style="color:#64748b;">${window.escapeHtml(b.size_formatted)} &bull; ${Number(b.product_count) || 0} SKUs</span>
                </td>
                <td style="padding:0.5rem 0.65rem;text-align:right;white-space:nowrap;">
                    <span class="badge badge-verified">Server Stored</span>
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
            window.showToast("Server-side ACID snapshot created!", "success");
            loadBackupsList();
            loadAdminDiagnostics();
        } else {
            window.showToast(data.message || "Backup failed", "error");
        }
    } catch (err) {
        window.showToast("Backup error", "error");
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
                ? items.map(m => `<div style="padding:0.45rem 0;border-bottom:1px solid #e2e8f0;font-size:0.8rem;"><b>${window.escapeHtml(m.event_id)}</b> &bull; ${window.escapeHtml(m.created_at)} <span class="badge badge-verified">${window.escapeHtml(m.status)}</span></div>`).join("")
                : `<span style="font-size:0.82rem;color:#64748b;">No queued deliveries logged yet.</span>`;
        }

        if (inqEl && inqRes.ok) {
            const list = (await inqRes.json()).slice(0, 8);
            inqEl.innerHTML = list.length
                ? list.map(q => `<div style="padding:0.45rem 0;border-bottom:1px solid #e2e8f0;font-size:0.8rem;"><b>${window.escapeHtml(q.reference_code)}</b> &bull; ${window.escapeHtml(q.category)} <span class="badge badge-verified">${window.escapeHtml(q.status)}</span></div>`).join("")
                : `<span style="font-size:0.82rem;color:#64748b;">No customer inquiries yet.</span>`;
        }
    } catch (err) {
        console.debug("Admin outbox/inquiries load error:", err);
    }
}
