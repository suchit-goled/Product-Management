/**
 * Product Catalog - Role-Gated Editor Module (Served ONLY to authenticated Editor & Admin sessions)
 * Handles AI Studio uploads, draft refinement, and catalog CRUD mutations via CSRF-protected BFF routes.
 */

let studioSelectedFile = null;
let studioCurrentDraft = null;
let studioMode = "image";
let pendingDeleteId = null;

document.addEventListener("DOMContentLoaded", () => {
    initStudioDropzone();
    bindEditorControls();
});

function bindEditorControls() {
    const modeImageBtn = document.getElementById("modeImageBtn");
    const modePromptBtn = document.getElementById("modePromptBtn");
    const genPromptBtn = document.getElementById("generateFromPromptBtn");
    const addFeat = document.getElementById("addFeatureRowBtn");
    const addSpec = document.getElementById("addSpecRowBtn");
    const addUsp = document.getElementById("addUspRowBtn");
    const saveDraftTop = document.getElementById("saveDraftTopBtn");
    const saveDraftBot = document.getElementById("saveDraftBottomBtn");
    const discardTop = document.getElementById("discardDraftTopBtn");
    const discardBot = document.getElementById("discardDraftBottomBtn");
    const editForm = document.getElementById("productEditForm");
    const confirmDeleteBtn = document.getElementById("confirmExecuteDeleteBtn");

    if (modeImageBtn) modeImageBtn.addEventListener("click", () => switchStudioMode("image"));
    if (modePromptBtn) modePromptBtn.addEventListener("click", () => switchStudioMode("prompt"));
    if (genPromptBtn) genPromptBtn.addEventListener("click", runPromptCatalogGeneration);
    if (addFeat) addFeat.addEventListener("click", addFeatureRow);
    if (addSpec) addSpec.addEventListener("click", addSpecRow);
    if (addUsp) addUsp.addEventListener("click", addUspRow);
    if (saveDraftTop) saveDraftTop.addEventListener("click", saveReviewedCatalogItem);
    if (saveDraftBot) saveDraftBot.addEventListener("click", saveReviewedCatalogItem);
    if (discardTop) discardTop.addEventListener("click", resetStudioUploadState);
    if (discardBot) discardBot.addEventListener("click", resetStudioUploadState);
    if (editForm) editForm.addEventListener("submit", handleUpdateProductSubmit);
    if (confirmDeleteBtn) confirmDeleteBtn.addEventListener("click", executeProductDeletion);

    document.addEventListener("click", (e) => {
        const rmBtn = e.target.closest("[data-remove-row]");
        if (rmBtn && rmBtn.parentElement) {
            rmBtn.parentElement.remove();
        }
    });
}

function switchStudioMode(mode) {
    studioMode = mode === "prompt" ? "prompt" : "image";
    const imgPane = document.getElementById("imageGeneratorPane");
    const promptPane = document.getElementById("promptGeneratorPane");
    const modeImageBtn = document.getElementById("modeImageBtn");
    const modePromptBtn = document.getElementById("modePromptBtn");
    const reviewWorkspace = document.getElementById("reviewWorkspace");

    if (reviewWorkspace) reviewWorkspace.style.display = "none";
    if (imgPane) imgPane.style.display = studioMode === "image" ? "block" : "none";
    if (promptPane) promptPane.style.display = studioMode === "prompt" ? "block" : "none";

    if (modeImageBtn) {
        modeImageBtn.classList.toggle("btn-primary", studioMode === "image");
        modeImageBtn.classList.toggle("btn-secondary", studioMode !== "image");
    }
    if (modePromptBtn) {
        modePromptBtn.classList.toggle("btn-primary", studioMode === "prompt");
        modePromptBtn.classList.toggle("btn-secondary", studioMode !== "prompt");
    }
    setWorkflowStep(1);
}

function initStudioDropzone() {
    const dropzone = document.getElementById("uploadDropzone");
    const fileInput = document.getElementById("catalogImageInput");
    if (!dropzone || !fileInput) return;

    dropzone.addEventListener("click", () => fileInput.click());

    ["dragenter", "dragover"].forEach(ev => {
        dropzone.addEventListener(ev, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(ev => {
        dropzone.addEventListener(ev, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove("dragover");
        });
    });

    dropzone.addEventListener("drop", (e) => {
        if (e.dataTransfer.files?.length > 0) handleImageSelection(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files?.length > 0) handleImageSelection(e.target.files[0]);
    });

    const clearBtn = document.getElementById("clearSelectedImageBtn");
    const startBtn = document.getElementById("startAiAnalysisBtn");
    if (clearBtn) clearBtn.addEventListener("click", resetStudioUploadState);
    if (startBtn) startBtn.addEventListener("click", runAiCatalogExtraction);
}

function handleImageSelection(file) {
    if (!file.type.startsWith("image/")) {
        window.showToast("Please select a valid image file (PNG, JPG, WEBP)", "warning");
        return;
    }
    studioSelectedFile = file;

    const dropzone = document.getElementById("uploadDropzone");
    const previewBox = document.getElementById("uploadPreviewBox");
    const imgPreview = document.getElementById("selectedImgPreview");
    const nameEl = document.getElementById("previewFilename");
    const sizeEl = document.getElementById("previewFilesize");

    if (dropzone) dropzone.style.display = "none";
    if (previewBox) previewBox.style.display = "block";
    if (nameEl) nameEl.textContent = file.name;
    if (sizeEl) sizeEl.textContent = `${(file.size / 1024).toFixed(1)} KB`;

    const reader = new FileReader();
    reader.onload = (ev) => { if (imgPreview) imgPreview.src = ev.target.result; };
    reader.readAsDataURL(file);
    setWorkflowStep(2);
}

function resetStudioUploadState() {
    studioSelectedFile = null;
    studioCurrentDraft = null;
    const inp = document.getElementById("catalogImageInput");
    if (inp) inp.value = "";
    const promptInp = document.getElementById("promptCatalogInput");
    if (promptInp) promptInp.value = "";
    ["promptBrandInput", "promptCategoryInput", "promptPriceInput"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    const ids = {
        uploadDropzone: "block",
        uploadPreviewBox: "none",
        aiProgressCard: "none",
        reviewWorkspace: "none"
    };
    Object.entries(ids).forEach(([id, disp]) => {
        const el = document.getElementById(id);
        if (el) el.style.display = disp;
    });
    switchStudioMode(studioMode);
}

function setWorkflowStep(stepNum) {
    ["step1Indicator", "step2Indicator", "step3Indicator", "step4Indicator"].forEach((id, idx) => {
        const el = document.getElementById(id);
        if (!el) return;
        const curr = idx + 1;
        el.classList.toggle("active", curr === stepNum);
        el.classList.toggle("completed", curr < stepNum);
    });
}

async function runAiCatalogExtraction() {
    if (!studioSelectedFile) {
        window.showToast("Please upload an image first", "warning");
        return;
    }
    const previewBox = document.getElementById("uploadPreviewBox");
    const progressCard = document.getElementById("aiProgressCard");
    const reviewWorkspace = document.getElementById("reviewWorkspace");
    const progressFill = document.getElementById("aiProgressBarFill");
    const progressStatus = document.getElementById("aiProgressStatus");

    if (previewBox) previewBox.style.display = "none";
    if (progressCard) progressCard.style.display = "block";
    if (reviewWorkspace) reviewWorkspace.style.display = "none";
    if (progressFill) progressFill.style.width = "40%";
    if (progressStatus) progressStatus.textContent = "Sanitizing image & analyzing product attributes...";
    setWorkflowStep(3);

    try {
        const fd = new FormData();
        fd.append("image", studioSelectedFile);
        fd.append("save_immediately", "false");
        const modelSel = document.getElementById("aiModelSelect");
        if (modelSel) fd.append("model", modelSel.value);

        const res = await window.secureFetch("/gw/studio/upload", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Upload failed");

        if (progressFill) progressFill.style.width = "100%";
        studioCurrentDraft = data.draft;

        setTimeout(() => {
            if (progressCard) progressCard.style.display = "none";
            populateReviewWorkspace(data.draft, data.image_metadata);
            if (reviewWorkspace) reviewWorkspace.style.display = "grid";
            window.showToast(data.warning ? `Notice: ${data.warning}` : "Draft ready for review", data.warning ? "warning" : "success");
        }, 300);
    } catch (err) {
        if (progressCard) progressCard.style.display = "none";
        if (previewBox) previewBox.style.display = "block";
        window.showToast(`Extraction error: ${err.message}`, "error");
    }
}

async function runPromptCatalogGeneration() {
    const promptText = (document.getElementById("promptCatalogInput")?.value || "").trim();
    if (promptText.length < 3) {
        window.showToast("Please describe the product first (at least 3 characters)", "warning");
        return;
    }

    const promptPane = document.getElementById("promptGeneratorPane");
    const progressCard = document.getElementById("aiProgressCard");
    const reviewWorkspace = document.getElementById("reviewWorkspace");
    const progressFill = document.getElementById("aiProgressBarFill");
    const progressStatus = document.getElementById("aiProgressStatus");

    if (promptPane) promptPane.style.display = "none";
    if (progressCard) progressCard.style.display = "block";
    if (reviewWorkspace) reviewWorkspace.style.display = "none";
    if (progressFill) progressFill.style.width = "45%";
    if (progressStatus) progressStatus.textContent = "Generating structured catalog entry via server AI...";
    setWorkflowStep(2);

    try {
        const payload = {
            prompt: promptText,
            brand: document.getElementById("promptBrandInput")?.value.trim() || "",
            category: document.getElementById("promptCategoryInput")?.value.trim() || "",
            price: document.getElementById("promptPriceInput")?.value.trim() || "",
            model: document.getElementById("promptModelSelect")?.value || "llama-3.3-70b-versatile",
            save_immediately: false
        };

        const res = await window.secureFetch("/gw/studio/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Catalog generation failed");

        if (progressFill) progressFill.style.width = "100%";
        studioCurrentDraft = data.draft;
        setWorkflowStep(3);

        setTimeout(() => {
            if (progressCard) progressCard.style.display = "none";
            populateReviewWorkspace(data.draft, null);
            if (reviewWorkspace) reviewWorkspace.style.display = "grid";
            window.showToast(data.warning ? `Notice: ${data.warning}` : "Catalog draft generated for review", data.warning ? "warning" : "success");
        }, 250);
    } catch (err) {
        if (progressCard) progressCard.style.display = "none";
        if (promptPane) promptPane.style.display = "block";
        window.showToast(`Generation error: ${err.message}`, "error");
    }
}

function populateReviewWorkspace(draft, imgMeta) {
    const img = document.getElementById("reviewLargeImage");
    const meta = document.getElementById("reviewMediaMeta");
    if (img) {
        if (draft.image_path && typeof draft.image_path === "string" && draft.image_path.startsWith("/static/uploads/")) {
            img.src = draft.image_path;
            img.style.display = "block";
        } else {
            img.removeAttribute("src");
            img.style.display = "none";
        }
    }
    if (meta) {
        if (imgMeta) {
            meta.innerHTML = `
                <div><b>Dimensions:</b> ${Number(imgMeta.width) || 0} x ${Number(imgMeta.height) || 0} px</div>
                <div><b>Format:</b> ${window.escapeHtml(imgMeta.format)} &bull; <b>EXIF Stripped:</b> Yes</div>
            `;
        } else {
            meta.innerHTML = `<div><b>Source:</b> Text Brief Catalog Generation</div><div><b>Status:</b> Ready for review &amp; publishing</div>`;
        }
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
    document.getElementById("reviewTags").value = (draft.tags || []).join(", ");

    renderDynamicList("dynamicFeaturesContainer", draft.features || [], "feature-input", "Feature");
    renderDynamicSpecs(draft.specifications || {});
    renderDynamicList("dynamicUspContainer", draft.selling_points || [], "usp-input", "Selling point");
}

function renderDynamicList(containerId, items, cls, placeholder) {
    const c = document.getElementById(containerId);
    if (!c) return;
    c.innerHTML = "";
    items.forEach(item => {
        const row = document.createElement("div");
        row.className = "dynamic-row";
        row.innerHTML = `
            <input type="text" class="form-control ${cls}" value="${window.escapeHtml(item)}" placeholder="${placeholder}">
            <button type="button" class="btn-icon" data-remove-row="1" title="Remove">&times;</button>
        `;
        c.appendChild(row);
    });
}

function renderDynamicSpecs(specs) {
    const c = document.getElementById("dynamicSpecsContainer");
    if (!c) return;
    c.innerHTML = "";
    Object.entries(specs).forEach(([k, v]) => {
        const row = document.createElement("div");
        row.className = "dynamic-row";
        row.innerHTML = `
            <input type="text" class="form-control spec-key-input" style="flex:1;" value="${window.escapeHtml(k)}">
            <input type="text" class="form-control spec-val-input" style="flex:2;" value="${window.escapeHtml(v)}">
            <button type="button" class="btn-icon" data-remove-row="1" title="Remove">&times;</button>
        `;
        c.appendChild(row);
    });
}

function addFeatureRow() {
    const c = document.getElementById("dynamicFeaturesContainer");
    if (!c) return;
    const r = document.createElement("div");
    r.className = "dynamic-row";
    r.innerHTML = `<input type="text" class="form-control feature-input" placeholder="New feature..."><button type="button" class="btn-icon" data-remove-row="1">&times;</button>`;
    c.appendChild(r);
}

function addSpecRow() {
    const c = document.getElementById("dynamicSpecsContainer");
    if (!c) return;
    const r = document.createElement("div");
    r.className = "dynamic-row";
    r.innerHTML = `<input type="text" class="form-control spec-key-input" style="flex:1;" placeholder="Attribute"><input type="text" class="form-control spec-val-input" style="flex:2;" placeholder="Value"><button type="button" class="btn-icon" data-remove-row="1">&times;</button>`;
    c.appendChild(r);
}

function addUspRow() {
    const c = document.getElementById("dynamicUspContainer");
    if (!c) return;
    const r = document.createElement("div");
    r.className = "dynamic-row";
    r.innerHTML = `<input type="text" class="form-control usp-input" placeholder="Commercial advantage..."><button type="button" class="btn-icon" data-remove-row="1">&times;</button>`;
    c.appendChild(r);
}

async function saveReviewedCatalogItem() {
    const prodName = document.getElementById("reviewProductName").value.trim();
    if (!prodName) {
        window.showToast("Product title is required", "warning");
        return;
    }
    const features = [...document.querySelectorAll("#dynamicFeaturesContainer .feature-input")].map(i => i.value.trim()).filter(Boolean);
    const specifications = {};
    document.querySelectorAll("#dynamicSpecsContainer .dynamic-row").forEach(row => {
        const k = row.querySelector(".spec-key-input")?.value.trim();
        const v = row.querySelector(".spec-val-input")?.value.trim();
        if (k) specifications[k] = v || "";
    });
    const selling_points = [...document.querySelectorAll("#dynamicUspContainer .usp-input")].map(i => i.value.trim()).filter(Boolean);
    const tags = (document.getElementById("reviewTags")?.value || "").split(",").map(t => t.trim()).filter(Boolean);

    const payload = {
        product_name: prodName,
        brand: document.getElementById("reviewBrand").value.trim(),
        model: document.getElementById("reviewModel").value.trim() || null,
        category: document.getElementById("reviewCategory").value.trim() || "General",
        price: document.getElementById("reviewPrice").value.trim() || "N/A",
        dimensions: document.getElementById("reviewDimensions").value.trim() || "N/A",
        short_description: document.getElementById("reviewShortDesc").value.trim(),
        description: document.getElementById("reviewDesc").value.trim(),
        features, specifications, selling_points, tags,
        seo_title: document.getElementById("reviewSeoTitle").value.trim(),
        seo_description: document.getElementById("reviewSeoDesc").value.trim(),
        image_path: studioCurrentDraft?.image_path || "",
        extraction_source: studioCurrentDraft?.extraction_source || "manual",
        status: "active"
    };

    try {
        const res = await window.secureFetch("/gw/catalog/item", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Save failed");

        setWorkflowStep(4);
        window.showToast("Product saved to catalog!", "success");
        resetStudioUploadState();
        window.loadCatalogData();
        window.switchTab("catalogExplorer");
    } catch (err) {
        window.showToast(`Save error: ${err.message}`, "error");
    }
}

window.openEditorModalForId = async function (productId) {
    try {
        const res = await window.secureFetch(`/gw/catalog/item/${productId}`);
        if (!res.ok) throw new Error("Not found");
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
        window.showToast("Unable to open product editor", "error");
    }
};

async function handleUpdateProductSubmit(e) {
    e.preventDefault();
    const id = document.getElementById("editProductId").value;
    if (!id) return;

    const payload = {
        product_name: document.getElementById("editProductName").value.trim(),
        brand: document.getElementById("editBrand").value.trim(),
        model: document.getElementById("editModel").value.trim() || null,
        category: document.getElementById("editCategory").value.trim() || "General",
        price: document.getElementById("editPrice").value.trim(),
        dimensions: document.getElementById("editDimensions").value.trim(),
        short_description: document.getElementById("editShortDesc").value.trim(),
        description: document.getElementById("editDesc").value.trim(),
        features: document.getElementById("editFeatures").value.split("\n").map(x => x.trim()).filter(Boolean),
        tags: document.getElementById("editTags").value.split(",").map(x => x.trim()).filter(Boolean)
    };

    try {
        const res = await window.secureFetch(`/gw/catalog/item/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Update failed");
        window.showToast("Product updated!", "success");
        const modal = document.getElementById("productEditModal");
        if (modal) modal.classList.remove("active");
        window.loadCatalogData();
    } catch (err) {
        window.showToast(`Update error: ${err.message}`, "error");
    }
}

window.openDeleteModalForId = function (id, name) {
    pendingDeleteId = id;
    const el = document.getElementById("deleteProductName");
    if (el) el.textContent = name;
    const modal = document.getElementById("productDeleteModal");
    if (modal) modal.classList.add("active");
};

async function executeProductDeletion() {
    if (!pendingDeleteId) return;
    try {
        const res = await window.secureFetch(`/gw/catalog/item/${pendingDeleteId}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Delete failed");
        window.showToast("Product removed from catalog", "success");
        pendingDeleteId = null;
        const modal = document.getElementById("productDeleteModal");
        if (modal) modal.classList.remove("active");
        window.loadCatalogData();
    } catch (err) {
        window.showToast(`Delete error: ${err.message}`, "error");
    }
}
