(() => {
  "use strict";

  const state = { token: null, user: null, deals: [], deal: null, documents: [], methodology: null, run: null, report: null };
  const loginView = document.querySelector("#login-view");
  const application = document.querySelector("#application");
  const pageContent = document.querySelector("#page-content");
  const pageTitle = document.querySelector("#page-title");
  const breadcrumb = document.querySelector("#breadcrumb");
  const dialog = document.querySelector("#create-deal-dialog");

  document.querySelector("#login-form").addEventListener("submit", login);
  document.querySelector("#logout-button").addEventListener("click", logout);
  document.querySelector("#create-deal-form").addEventListener("submit", createDeal);
  document.querySelectorAll("[data-route]").forEach((element) => {
    element.addEventListener("click", (event) => {
      event.preventDefault();
      route(element.dataset.route);
    });
  });

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const response = await fetch(path, { ...options, headers });
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && state.token) resetSession();
      const detail = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg || "Invalid value").join(" ")
        : typeof body.detail === "object"
          ? body.detail.message || body.detail.code
          : body.detail;
      throw new Error(detail || "The request could not be completed.");
    }
    return body;
  }

  async function login(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const error = document.querySelector("#login-error");
    error.hidden = true;
    setBusy(form, true);
    try {
      const payload = await api("/pilot/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: form.email.value,
          password: form.password.value,
        }),
      });
      state.token = payload.access_token;
      state.user = payload.user;
      loginView.hidden = true;
      application.hidden = false;
      document.querySelector("#user-name").textContent = state.user.display_name;
      document.querySelector("#user-role").textContent = state.user.is_pilot_admin
        ? "Pilot administrator"
        : "Deal team member";
      document.querySelector("#user-avatar").textContent = initials(state.user.display_name);
      await loadDeals();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      setBusy(form, false);
    }
  }

  async function logout() {
    try { await api("/pilot/auth/logout", { method: "POST" }); } catch (_) { /* session reset below */ }
    resetSession();
  }

  function resetSession() {
    state.token = null;
    state.user = null;
    state.deals = [];
    state.deal = null;
    state.documents = [];
    state.methodology = null;
    state.run = null;
    state.report = null;
    application.hidden = true;
    loginView.hidden = false;
    document.querySelector("#password").value = "";
  }

  async function loadDeals() {
    pageContent.innerHTML = loading("Loading deal workspaces…");
    state.deals = await api("/pilot/deals");
    route("deals");
  }

  function route(name) {
    if (name !== "deals" && !state.deal) return;
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.route === name);
    });
    const renderers = {
      deals: renderDeals,
      overview: renderOverview,
      documents: renderDocuments,
      analysis: renderAnalysis,
      findings: renderFindings,
      financials: renderFinancials,
      review: renderReview,
      report: renderReport,
    };
    renderers[name]();
    pageContent.focus();
  }

  function setDeal(dealId) {
    state.deal = state.deals.find((deal) => deal.deal_id === dealId);
    state.documents = [];
    state.methodology = null;
    state.run = null;
    state.report = null;
    document.querySelectorAll(".nav-item").forEach((item) => {
      if (item.dataset.route !== "deals") item.disabled = false;
    });
    route("overview");
  }

  function renderDeals() {
    state.deal = null;
    state.documents = [];
    state.run = null;
    document.querySelectorAll(".nav-item").forEach((item) => {
      if (item.dataset.route !== "deals") item.disabled = true;
    });
    setHeading("Deals", "Deal workspaces");
    const createButton = state.user?.is_pilot_admin
      ? '<button id="new-deal" class="button button-primary" type="button">Create deal</button>'
      : "";
    const cards = state.deals.length
      ? state.deals.map((deal) => `
          <article class="deal-card">
            <button type="button" data-deal-id="${escapeHtml(deal.deal_id)}">
              <span class="status status-${escapeHtml(deal.status)}">${pretty(deal.status)}</span>
              <h3>${escapeHtml(deal.name)}</h3>
              <p>${escapeHtml(deal.target_name)}</p>
              <div class="deal-meta">
                <span>${escapeHtml(deal.transaction_type)}</span>
                <span>${escapeHtml(deal.reporting_currency)} · ${escapeHtml(deal.as_of_date)}</span>
              </div>
            </button>
          </article>`).join("")
      : `<div class="panel empty-state"><div class="empty-icon">◆</div><h3>No deals assigned</h3><p>Ask a pilot administrator to assign you to a deal workspace.</p></div>`;
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>Your transactions</h2><p>Open a controlled workspace to review its evidence and decisions.</p></div>${createButton}</div>
      <div class="card-grid">${cards}</div>`;
    pageContent.querySelectorAll("[data-deal-id]").forEach((button) => {
      button.addEventListener("click", () => setDeal(button.dataset.dealId));
    });
    document.querySelector("#new-deal")?.addEventListener("click", () => dialog.showModal());
  }

  function renderOverview() {
    setHeading(`Deals / ${state.deal.name}`, "Executive overview");
    const run = state.run;
    const financial = run?.financial;
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>${escapeHtml(state.deal.target_name)}</h2><p>${escapeHtml(state.deal.transaction_type)} · as of ${escapeHtml(state.deal.as_of_date)}</p></div>${run ? status(run.status) : status("not_started")}</div>
      <div class="stats">
        ${stat("Documents", run?.document_count ?? "—")}
        ${stat("Findings", run?.finding_count ?? "—")}
        ${stat("Adjusted EBITDA", money(financial?.adjusted_ebitda, financial))}
        ${stat("Largest customer", financial?.largest_customer_percent ? `${financial.largest_customer_percent}%` : "—")}
      </div>
      <section class="panel">
        <h3>Decision-support boundary</h3>
        <p class="muted">This pilot links material findings to evidence and keeps financial arithmetic deterministic. No result is an autonomous investment recommendation.</p>
      </section>
      ${run ? priorityFindings(run.findings.slice(0, 4)) : empty("◎", "No analysis run yet", "Start the controlled demo analysis to populate evidence-linked findings and financial outputs.", "Open analysis", "analysis")}`;
    bindRouteButtons();
  }

  async function renderDocuments() {
    setHeading(`Deals / ${state.deal.name}`, "Documents");
    const dealId = state.deal.deal_id;
    pageContent.innerHTML = loading("Loading the encrypted document inventory…");
    try {
      state.documents = await api(`/pilot/deals/${dealId}/documents`);
    } catch (failure) {
      pageContent.innerHTML = `<p class="form-error">${escapeHtml(failure.message)}</p>`;
      return;
    }
    if (!state.deal || state.deal.deal_id !== dealId) return;
    const indexed = state.documents.filter((item) => item.status === "indexed").length;
    const exceptions = state.documents.filter((item) => ["partial", "failed"].includes(item.status)).length;
    const rows = state.documents.length
      ? `<div class="document-list">${state.documents.map(documentRow).join("")}</div>`
      : empty("▤", "No pilot documents uploaded", "Upload supported PDF, XLSX, CSV, TXT, Markdown, or HTML files. Each file is validated, screened, encrypted, parsed, and retained with a visible status.");
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>Virtual data room</h2><p>Encrypted document inventory, processing status, and recoverable exceptions.</p></div><label class="button button-primary upload-button">Upload documents<input id="document-upload" type="file" multiple hidden accept=".pdf,.xlsx,.csv,.txt,.md,.markdown,.html,.htm" /></label></div>
      <div class="stats">${stat("Uploaded", state.documents.length)}${stat("Indexed", indexed)}${stat("Exceptions", exceptions)}${stat("Maximum file", "50 MB")}</div>
      <p id="upload-progress" class="muted">Files are processed independently; one failure does not discard the batch.</p>
      ${rows}`;
    document.querySelector("#document-upload").addEventListener("change", uploadDocuments);
  }

  async function uploadDocuments(event) {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    const batchId = `batch-${crypto.randomUUID()}`;
    const progress = document.querySelector("#upload-progress");
    input.disabled = true;
    let accepted = 0;
    const failures = [];
    for (const [index, file] of files.entries()) {
      progress.textContent = `Processing ${index + 1} of ${files.length}: ${file.name}`;
      try {
        const response = await fetch(`/pilot/deals/${state.deal.deal_id}/documents`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${state.token}`,
            "Content-Type": file.type || "application/octet-stream",
            "X-Filename": encodeURIComponent(file.name),
            "X-Upload-Batch": batchId,
          },
          body: file,
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = typeof body.detail === "object" ? body.detail.message : body.detail;
          throw new Error(detail || "Upload failed.");
        }
        accepted += 1;
      } catch (failure) {
        failures.push(`${file.name}: ${failure.message}`);
      }
    }
    input.disabled = false;
    input.value = "";
    toast(`${accepted} of ${files.length} documents processed${failures.length ? `; ${failures.length} rejected` : ""}.`, Boolean(failures.length));
    await renderDocuments();
    if (failures.length) {
      document.querySelector("#upload-progress").textContent = failures.join(" · ");
    }
  }

  function documentRow(item) {
    const issues = [...(item.warnings || []), ...(item.issues || []).map((issue) => issue.message)];
    const details = [
      item.document_type ? pretty(item.document_type) : "Classification unavailable",
      `${formatBytes(item.size_bytes)}`,
      item.page_count ? `${item.page_count} pages` : null,
      item.chunk_count != null ? `${item.chunk_count} chunks` : null,
      item.table_row_count ? `${item.table_row_count} table rows` : null,
    ].filter(Boolean).join(" · ");
    return `<article class="document-row">
      <div><h3>${escapeHtml(item.filename)}</h3><p>${escapeHtml(details)}</p>${issues.length ? `<small>${escapeHtml(issues.join(" · "))}</small>` : ""}</div>
      ${status(item.status)}
    </article>`;
  }

  function renderAnalysis() {
    setHeading(`Deals / ${state.deal.name}`, "Analysis");
    const body = state.run
      ? `<section class="panel"><div class="page-heading"><div><h2>Run ${escapeHtml(state.run.run_id.slice(-8))}</h2><p>Evidence retrieval, deterministic finance, four specialists, and review routing.</p></div>${status(state.run.status)}</div>
          <div class="review-list">
            ${progress("VDR ingestion", true, `${state.run.document_count} documents`)}
            ${progress("Hybrid evidence retrieval", true, "Evidence retained with provenance")}
            ${progress("Financial diligence", Boolean(state.run.financial), state.run.financial ? "Calculations complete" : "Unavailable")}
            ${progress("Specialist investigation", state.run.finding_count > 0, `${state.run.finding_count} findings`) }
            ${progress("Human review", !state.run.review_required, state.run.review_required ? `${state.run.review_reasons.length} reasons require attention` : "Complete")}
          </div></section>`
      : empty("◎", "Ready for a controlled demonstration", "Run the verified 25-document synthetic data room through the complete V1 workflow. This does not upload or expose company data.", "Run demo analysis", "start-run");
    pageContent.innerHTML = `<div class="page-heading"><div><h2>Diligence workflow</h2><p>Traceable processing from evidence to human-reviewed report.</p></div></div>${body}`;
    document.querySelector("[data-action='start-run']")?.addEventListener("click", startRun);
  }

  async function startRun(event) {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Running analysis…";
    pageContent.insertAdjacentHTML("beforeend", loading("Processing the synthetic VDR through all four workstreams…"));
    try {
      state.run = await api(`/pilot/deals/${state.deal.deal_id}/runs`, { method: "POST" });
      toast("Analysis paused at the human-review checkpoint.");
      route("analysis");
    } catch (failure) {
      toast(failure.message, true);
      route("analysis");
    }
  }

  function renderFindings() {
    setHeading(`Deals / ${state.deal.name}`, "Findings");
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>Evidence-linked findings</h2><p>Expand any finding to inspect its source excerpts and support status.</p></div>${state.run ? status(state.run.status) : ""}</div>
      ${state.run ? findingList(state.run.findings) : empty("!", "No findings yet", "Start an analysis run before reviewing findings.", "Open analysis", "analysis")}`;
    bindRouteButtons();
  }

  async function renderFinancials() {
    setHeading(`Deals / ${state.deal.name}`, "Financials");
    if (!state.methodology) {
      pageContent.innerHTML = loading("Loading the versioned financial methodology…");
      try {
        state.methodology = await api(`/pilot/deals/${state.deal.deal_id}/financial-methodology`);
      } catch (failure) {
        pageContent.innerHTML = `<p class="form-error">${escapeHtml(failure.message)}</p>`;
        return;
      }
    }
    const financial = state.run?.financial;
    const methodology = state.methodology;
    const assumptions = methodology.engagement_assumptions;
    const rules = methodology.rules.map((rule) => `<details class="methodology-rule"><summary><span>${escapeHtml(rule.code)}</span><strong>${escapeHtml(rule.title)}</strong></summary><p>${escapeHtml(rule.policy)}</p>${rule.formula ? `<p><strong>Formula:</strong> ${escapeHtml(rule.formula)}</p>` : ""}<p><strong>Reviewer challenges:</strong> ${rule.challenge_questions.map((item) => escapeHtml(item)).join(" · ")}</p></details>`).join("");
    const trace = financial?.calculation_trace;
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>Deterministic financial analysis</h2><p>Methodology ${escapeHtml(methodology.version)} · ${escapeHtml(methodology.fingerprint_sha256.slice(0, 12))} · values retain full Decimal precision.</p></div></div>
      ${financial ? `<div class="financial-grid">
        ${financialValue("Reported EBITDA", money(financial.reported_ebitda, financial))}
        ${financialValue("Accepted adjustments", money(financial.accepted_adjustments, financial))}
        ${financialValue("Diligence-adjusted EBITDA", money(financial.adjusted_ebitda, financial))}
        ${financialValue("Largest customer", `${financial.largest_customer_percent}%`)}
        ${financialValue("Normalized NWC", money(financial.normalized_nwc, financial))}
        ${financialValue("Adjusted net debt", money(financial.adjusted_net_debt, financial))}
      </div>${trace ? `<section class="panel"><h3>Reproducible calculation trace</h3><p class="muted">Each bridge below shows its formula, signed inputs, source identifiers, and reconciliation result.</p>${calculationTrace(trace)}</section>` : ""}` : empty("£", "No financial output yet", "Complete an analysis run to calculate the QoE, working-capital, concentration, and net-debt outputs.", "Open analysis", "analysis")}
      <section class="panel"><div class="page-heading"><div><h3>Methodology and engagement assumptions</h3><p>Currency ${escapeHtml(assumptions.reporting_currency)} · unit ${escapeHtml(assumptions.unit)} · as of ${escapeHtml(assumptions.as_of_date)} · materiality ${escapeHtml(assumptions.materiality_threshold || "not preset")}</p></div><span class="status">Version ${escapeHtml(methodology.version)}</span></div><div class="methodology-list">${rules}</div></section>`;
    bindRouteButtons();
  }

  function calculationTrace(trace) {
    const ebitda = trace.ebitda_bridge;
    const netDebt = trace.net_debt;
    const concentration = trace.customer_concentration;
    const reconciliation = trace.revenue_reconciliation;
    const nwc = trace.working_capital.map((item) => calculationBlock(`NWC · ${item.period}`, item.formula, item.lines, item.result, item.reconciles)).join("");
    const customerInputs = concentration.customers.map((item) => `<div><span>${escapeHtml(item.customer_id)}<small>Period ${escapeHtml(item.period)} · evidence ${escapeHtml(item.evidence_ids.join(", ") || "not available")}</small></span><strong>${escapeHtml(item.revenue)}</strong></div>`).join("");
    const sourceObservations = reconciliation.observations.map((item) => `<div><span>${escapeHtml(item.observation_id)}<small>${escapeHtml(pretty(item.source_document_type))} · ${escapeHtml(item.period)} · ${escapeHtml(pretty(item.reporting_status))} / ${escapeHtml(pretty(item.basis))} · evidence ${escapeHtml(item.evidence_ids.join(", ") || "not available")}</small></span><strong>${escapeHtml(item.value)}</strong></div>`).join("");
    const peg = trace.nwc_peg;
    return `${calculationBlock("EBITDA bridge", ebitda.formula, ebitda.lines, ebitda.result, ebitda.reconciles)}${nwc}<details class="methodology-rule"><summary><span>PEG</span><strong>NWC peg</strong></summary><p>Method: ${escapeHtml(pretty(peg.method))} · periods ${escapeHtml(peg.period_labels.join(", ") || "none")}</p><p>Normalized NWC: ${escapeHtml(peg.normalized_nwc ?? "unknown")} · current NWC: ${escapeHtml(peg.current_nwc ?? "unknown")} · surplus/(shortfall): ${escapeHtml(peg.surplus_or_shortfall ?? "unknown")}</p></details><details class="methodology-rule"><summary><span>CONC</span><strong>Customer concentration</strong></summary><p><strong>Formula:</strong> ${escapeHtml(concentration.formula)}</p><div class="calculation-lines">${customerInputs}</div><p>Total identified revenue: ${escapeHtml(concentration.total_revenue ?? "unknown")} · largest ${escapeHtml(concentration.largest_customer_percent ?? "unknown")}% · top five ${escapeHtml(concentration.top_five_percent ?? "unknown")}% · top ten ${escapeHtml(concentration.top_ten_percent ?? "unknown")}%</p></details>${calculationBlock("Adjusted net debt", netDebt.formula, netDebt.lines, netDebt.result, netDebt.reconciles)}<details class="methodology-rule"><summary><span>RECON</span><strong>Revenue source reconciliation</strong></summary><p>${escapeHtml(reconciliation.rationale)}</p><div class="calculation-lines">${sourceObservations}</div><p>Preferred source: ${escapeHtml(reconciliation.preferred_observation_id || "none")} · absolute variance ${escapeHtml(reconciliation.absolute_variance || "unknown")} · percentage variance ${escapeHtml(reconciliation.percent_variance || "unknown")} · ${escapeHtml(pretty(reconciliation.status))}</p></details>`;
  }

  function calculationBlock(title, formula, lines, result, reconciles) {
    const indicator = reconciles === true ? "✓" : reconciles === false ? "!" : "?";
    const conclusion = reconciles === true ? "reconciled" : reconciles === false ? "does not reconcile" : "input incomplete";
    return `<details class="methodology-rule"><summary><span>${indicator}</span><strong>${escapeHtml(title)}</strong></summary><p><strong>Formula:</strong> ${escapeHtml(formula)}</p><div class="calculation-lines">${lines.map((line) => `<div><span>${escapeHtml(line.operation)} ${escapeHtml(line.label)}<small>Source ${escapeHtml(line.source_ids.join(", ") || "not available")} · evidence ${escapeHtml(line.evidence_ids.join(", ") || "not available")}</small></span><strong>${escapeHtml(line.amount)}</strong></div>`).join("")}</div><p><strong>Result:</strong> ${escapeHtml(result ?? "unknown")} · ${conclusion}</p></details>`;
  }

  function renderReview() {
    setHeading(`Deals / ${state.deal.name}`, "Review queue");
    if (!state.run) {
      pageContent.innerHTML = empty("✓", "Nothing to review", "Start an analysis run to create the material-review queue.", "Open analysis", "analysis");
      bindRouteButtons();
      return;
    }
    const required = state.run.review_required;
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>Human review gate</h2><p>Material ambiguity must be explicitly dispositioned before report release.</p></div>${status(state.run.status)}</div>
      <section class="panel">
        ${required ? `<div class="warning-box">${state.run.review_reasons.length} policy reasons currently block final report release.</div>` : `<div class="warning-box">Review has been completed and retained in the workflow audit trail.</div>`}
        <div class="review-list">${state.run.review_reasons.map((reason) => `<div class="review-row"><span>${escapeHtml(reason)}</span><span class="status">Required</span></div>`).join("") || '<p class="muted">No open review reasons.</p>'}</div>
        ${required ? '<label>Overall review rationale<textarea id="review-rationale" rows="3">Reviewed the cited evidence and approved supported findings for this controlled demonstration.</textarea></label><button id="complete-review" class="button button-primary" type="button">Approve required items and resolve conflicts</button>' : '<button class="button button-secondary" data-action="report" type="button">Open report</button>'}
      </section>`;
    document.querySelector("#complete-review")?.addEventListener("click", completeReview);
    bindRouteButtons();
  }

  async function completeReview(event) {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Applying review…";
    const rationale = document.querySelector("#review-rationale").value;
    const decisions = state.run.review_finding_ids.map((findingId) => ({
      subject_type: "finding",
      subject_id: findingId,
      action: "approve_finding",
      rationale: "Reviewer inspected the cited evidence and approved this candidate finding.",
    }));
    state.run.conflicts
      .filter((conflict) => state.run.review_conflict_ids.includes(conflict.conflict_id))
      .forEach((conflict) => decisions.push({
        subject_type: "conflict",
        subject_id: conflict.conflict_id,
        action: "resolve_conflict",
        rationale: "Reviewer selected the direct source for final presentation.",
        preferred_source_id: conflict.observation_fact_ids[0],
      }));
    try {
      state.run = await api(`/pilot/deals/${state.deal.deal_id}/runs/${state.run.run_id}/review`, {
        method: "POST",
        body: JSON.stringify({ rationale, decisions }),
      });
      state.report = await api(`/pilot/deals/${state.deal.deal_id}/runs/${state.run.run_id}/report`);
      toast("Review recorded and report generated.");
      route("report");
    } catch (failure) {
      toast(failure.message, true);
      route("review");
    }
  }

  async function renderReport() {
    setHeading(`Deals / ${state.deal.name}`, "Report");
    if (!state.run?.report_available) {
      pageContent.innerHTML = empty("▣", "Report is not available", "Complete the required human review before generating the diligence report.", "Open review queue", "review");
      bindRouteButtons();
      return;
    }
    if (!state.report) {
      pageContent.innerHTML = loading("Loading reviewed report…");
      try { state.report = await api(`/pilot/deals/${state.deal.deal_id}/runs/${state.run.run_id}/report`); }
      catch (failure) { pageContent.innerHTML = `<p class="form-error">${escapeHtml(failure.message)}</p>`; return; }
    }
    const report = state.report.report;
    pageContent.innerHTML = `
      <div class="page-heading"><div><h2>${escapeHtml(report.target_name)} diligence report</h2><p>Evidence-linked output · ${escapeHtml(report.status)}</p></div>${status(state.run.status)}</div>
      <section class="panel report-document">
        ${report.sections.map((section) => `<article class="report-section"><h3>${escapeHtml(section.title)}</h3><p>${escapeHtml(section.narrative)}</p><p><strong>${section.findings.length}</strong> findings · <strong>${section.request_ids.length}</strong> requests</p></article>`).join("")}
        <article class="report-section"><h3>Limitations</h3>${report.limitations.map((item) => `<p>• ${escapeHtml(item)}</p>`).join("")}</article>
      </section>`;
  }

  async function createDeal(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const error = document.querySelector("#deal-form-error");
    error.hidden = true;
    const fields = new FormData(form);
    setBusy(form, true);
    try {
      const created = await api("/pilot/deals", {
        method: "POST",
        body: JSON.stringify({
          name: fields.get("name"), target_name: fields.get("target_name"),
          buyer_name: fields.get("buyer_name") || null,
          transaction_type: fields.get("transaction_type"),
          reporting_currency: fields.get("reporting_currency"),
          as_of_date: fields.get("as_of_date"),
          workstreams: ["financial", "commercial", "legal_contractual", "operational"],
          notes: fields.get("notes") || null,
        }),
      });
      state.deals.unshift(created);
      dialog.close();
      toast("Deal workspace created.");
      renderDeals();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally { setBusy(form, false); }
  }

  function findingList(findings) {
    if (!findings.length) return '<div class="panel"><p class="muted">No findings returned.</p></div>';
    return `<div class="finding-list">${findings.map((item) => `<details class="finding" data-severity="${escapeHtml(item.severity)}"><summary><span class="severity severity-${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span><span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(pretty(item.workstream))} · ${escapeHtml(pretty(item.support_status))}</p></span><span>＋</span></summary><div class="evidence"><p>${escapeHtml(item.description)}</p>${item.evidence.map((evidence) => `<blockquote><strong>${escapeHtml(evidence.document_id || "Source")}</strong>${evidence.pages.length ? ` · page ${evidence.pages.join(", ")}` : ""}<br>${escapeHtml(evidence.source_text || "Evidence reference retained in the workflow.")}</blockquote>`).join("")}</div></details>`).join("")}</div>`;
  }

  function priorityFindings(findings) { return `<section class="panel"><h3>Priority findings</h3>${findingList(findings)}</section>`; }
  function progress(label, complete, detail) { return `<div class="review-row"><span><strong>${complete ? "✓" : "○"} ${escapeHtml(label)}</strong><small class="muted"> · ${escapeHtml(detail)}</small></span></div>`; }
  function stat(label, value) { return `<div class="stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`; }
  function financialValue(label, value) { return `<div class="financial-value"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`; }
  function money(value, financial) {
    if (value == null) return "—";
    const numericValue = Number(value);
    const displayValue = Number.isFinite(numericValue)
      ? numericValue.toLocaleString("en-GB", { maximumFractionDigits: 2 })
      : String(value);
    return `${financial.currency} ${displayValue}${financial.unit === "million" ? "m" : ""}`;
  }
  function formatBytes(value) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  function status(value) { return `<span class="status status-${escapeHtml(value)}">${escapeHtml(pretty(value))}</span>`; }
  function empty(icon, title, copy, action, routeName) { return `<section class="panel empty-state"><div class="empty-icon">${icon}</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p>${action ? `<button class="button button-primary" type="button" data-action="${escapeHtml(routeName)}">${escapeHtml(action)}</button>` : ""}</section>`; }
  function loading(text) { return `<div class="panel loading"><span class="spinner" aria-hidden="true"></span>${escapeHtml(text)}</div>`; }
  function setHeading(path, title) { breadcrumb.textContent = path; pageTitle.textContent = title; }
  function bindRouteButtons() { document.querySelectorAll("[data-action]").forEach((button) => { if (button.dataset.action !== "start-run") button.addEventListener("click", () => route(button.dataset.action)); }); }
  function setBusy(form, busy) { form.querySelectorAll("button, input, select, textarea").forEach((control) => { control.disabled = busy; }); }
  function initials(name) { return name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase(); }
  function pretty(value) { return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }
  function toast(message, destructive = false) { const element = document.querySelector("#toast"); element.textContent = message; element.style.background = destructive ? "var(--red)" : "var(--ink)"; element.hidden = false; window.setTimeout(() => { element.hidden = true; }, 4000); }
})();
