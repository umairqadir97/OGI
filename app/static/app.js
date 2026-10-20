/* OpsGate AI v2.0: Enterprise Operations & Decision Intelligence Controller */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
      char
      ],
  );
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const number = (value, digits = 1) =>
  Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });

const defaults = () => ({
  prep_time_mins: 22,
  rework_mins: 12,
  duplicate_count: 8,
  hourly_blended_cost: 45,
  software_cost_per_task: 0,
  maintenance_cost_per_task: 0,
  monthly_task_volume: 120,
  currency: "USD",
  trial_tasks: [],
  release_cycles: [],
});

const state = {
  workflow: "VISUAL_QA",
  persona: "CEO",
  autonomy_mode: "STAGED_APPROVAL",
  scenarios: {},
  packet: null,
  report: null,
  events: [],
  filter: "all",
  settings: defaults(),
  receipt: null,
  trialSnapshot: null,
  busy: false,
  economicsVersion: 0,
};

let toastTimer;
let economicsTimer;

function money(value) {
  const isAED = state.settings.currency === "AED";
  const num = isAED ? Number(value) * 3.6725 : Number(value);
  if (isAED) {
    return `AED ${num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return num.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function toast(message, isError = false) {
  const el = $("#toast");
  clearTimeout(toastTimer);
  el.textContent = message;
  el.className = isError ? "error" : "";
  el.hidden = false;
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, 5000);
}

function readLocal(key, fallback = null) {
  try {
    return JSON.parse(localStorage.getItem(`ogi.v2.${key}`)) ?? fallback;
  } catch {
    return fallback;
  }
}

function saveLocal(key, value) {
  try {
    localStorage.setItem(`ogi.v2.${key}`, JSON.stringify(value));
  } catch {
    toast(
      "Browser storage is unavailable. Export your work before closing.",
      true,
    );
  }
}

async function api(path, body) {
  const response = await fetch(
    `/api/v1${path}`,
    body === undefined
      ? {}
      : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
  );
  const payload = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail
        .map(
          (item) => `${item.loc?.slice(1).join(".") || "Input"}: ${item.msg}`,
        )
        .join("; ")
      : payload.detail;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function on(selector, event, handler) {
  const el = $(selector);
  if (!el) return;
  el.addEventListener(event, async (e) => {
    try {
      await handler(e);
    } catch (error) {
      toast(error.message || "Something went wrong. Please try again.", true);
    }
  });
}

function setBusy(busy) {
  state.busy = busy;
  [
    "#workflow-select",
    "#scope-toggle",
    "#matrix-toggle",
    "#simulate-button",
    "#edit-source",
    "#export-button",
    "#receipt-button",
  ].forEach((selector) => {
    const el = $(selector);
    if (el) el.disabled = busy;
  });
  const simBtn = $("#simulate-button");
  if (simBtn) {
    simBtn.disabled =
      busy ||
      Boolean(state.events.length) ||
      !state.packet?.queue_items.some(
        (item) => item.status !== "CONFIRMED_READY",
      );
  }
  const pf = $("#preflight");
  if (pf) pf.setAttribute("aria-busy", String(busy));
}

function updatePersona(persona) {
  state.persona = persona;
  $$(".persona-tab").forEach((tab) =>
    tab.classList.toggle("active", tab.dataset.persona === persona),
  );

  const title = $("#persona-title");
  const desc = $("#persona-desc");
  const roleLabel = $("#user-role-label");
  const stat1Label = $("#persona-stat-1-label");
  const stat2Label = $("#persona-stat-2-label");
  const stat3Label = $("#persona-stat-3-label");
  const stat1 = $("#persona-stat-1");
  const stat2 = $("#persona-stat-2");
  const stat3 = $("#persona-stat-3");

  const vol = state.settings.monthly_task_volume || 120;
  const volFactor = vol / 120;
  const isAED = state.settings.currency === "AED";
  const rate = isAED ? 3.6725 : 1.0;

  if (persona === "CEO") {
    roleLabel.textContent = "CEO Cockpit";
    title.textContent = "CEO Decision Cockpit · Executive P&L & Portfolio Governance";
    desc.textContent =
      "Executive P&L overview: separating real capacity released from unverified cash claims across Puffy & RGG Capital.";
    stat1Label.textContent = "Portfolio Net Value";
    stat2Label.textContent = "Hard Cash Saved";
    stat3Label.textContent = "Active Sunset Alerts";
    const totalNetUSD = (19440 + 83250 + 44280 + 412000 - 18000) * volFactor;
    stat1.textContent = isAED ? `AED ${number(totalNetUSD * rate, 0)}` : `$${number(totalNetUSD, 0)}`;
    const cashUSD = 412000 * volFactor;
    stat2.textContent = isAED ? `AED ${number(cashUSD * rate, 0)}` : `$${number(cashUSD, 0)}`;
    stat3.textContent = "1 Bot Flagged (Negative ROI)";
    stat3.style.color = "var(--red)";
  } else if (persona === "COO") {
    roleLabel.textContent = "COO / Transformation";
    title.textContent = "COO / Transformation Cockpit";
    desc.textContent =
      "Operational velocity: Step 0 scope enforcement, Dubai ↔ LA handoff SLAs, and functional owner self-sufficiency.";
    stat1Label.textContent = "Step 0 Scope Gate";
    stat2Label.textContent = "Cross-Hub Velocity";
    stat3Label.textContent = "10-Task Trial Gate";
    stat1.textContent = state.packet?.step_0_scope_status === "PASSED" ? "100% Enforced · 0 Tokens" : "Blocked Upstream (0 Tokens)";
    stat2.textContent = "4h SLA · Dubai ↔ LA";
    stat3.textContent = state.report?.expansion_gate_evaluation.verdict.replace(/_/g, " ") || "Controlled 10-Task Gate";
    stat3.style.color = "var(--mint)";
  } else {
    // CAIO / Systems
    roleLabel.textContent = "CAIO / Systems";
    title.textContent = "CAIO / Systems Cockpit";
    desc.textContent =
      "LLMOps Observability: LLM Validation Link pass/fail telemetry, token efficiency, and central specialist deflection.";
    stat1Label.textContent = "Cryptographic Audit";
    stat2Label.textContent = "Specialist Deflection";
    stat3Label.textContent = "P95 Telemetry & ROI";
    stat1.textContent = "SHA-256 Verified";
    stat2.textContent = "82% Deflected (No Central Eng)";
    stat3.textContent = "184ms · High Token ROI";
    stat3.style.color = "var(--mint)";
  }
}

function synchronizeControls() {
  for (const [id, key] of [
    ["prep-slider", "prep_time_mins"],
    ["rework-slider", "rework_mins"],
    ["duplicates-slider", "duplicate_count"],
    ["hourly-rate", "hourly_blended_cost"],
    ["software-cost", "software_cost_per_task"],
    ["maintenance-cost", "maintenance_cost_per_task"],
    ["volume-slider", "monthly_task_volume"],
  ]) {
    const el = $(`#${id}`);
    if (el) el.value = state.settings[key];
  }
  updateSliderLabels();
  $("#currency-toggle").textContent = state.settings.currency === "AED" ? "AED د.إ" : "USD $";
}

function updateSliderLabels() {
  if ($("#prep-value") && $("#prep-slider")) $("#prep-value").textContent = `${$("#prep-slider").value} min`;
  if ($("#rework-value") && $("#rework-slider")) $("#rework-value").textContent = `${$("#rework-slider").value} min`;
  if ($("#duplicates-value") && $("#duplicates-slider")) $("#duplicates-value").textContent = `${$("#duplicates-slider").value} / 24`;
  if ($("#volume-label") && $("#volume-slider")) {
    $("#volume-label").textContent = `${$("#volume-slider").value} tasks/mo`;
  }
  $$("input[type=range]").forEach((slider) =>
    slider.style.setProperty(
      "--range",
      `${((slider.value - slider.min) / (slider.max - slider.min)) * 100}%`,
    ),
  );
}

async function loadWorkflow(workflow, directId = null) {
  setBusy(true);
  state.economicsVersion++;
  clearTimeout(economicsTimer);
  try {
    state.workflow = workflow;
    state.report = null;
    state.settings = {
      ...defaults(),
      ...readLocal(`settings.${workflow}`, {}),
    };
    state.trialSnapshot = await api(`/trials/${workflow}`);
    state.settings.trial_tasks =
      state.trialSnapshot?.evidence.trial_tasks || [];
    state.settings.release_cycles =
      state.trialSnapshot?.evidence.release_cycles || [];
    synchronizeControls();
    const storedId = directId || readLocal(`receipt.${workflow}`);
    let packet;
    if (storedId) {
      try {
        packet = await api(`/val/${encodeURIComponent(storedId)}`);
      } catch (error) {
        if (error.status !== 404 || directId) throw error;
      }
    }
    if (!packet || packet.workflow_type !== workflow) {
      packet = await api("/preflight/evaluate", {
        workflow_type: workflow,
        has_marked_asana_scope: true,
        has_device_matrix: true,
        raw_items: state.scenarios[workflow]?.raw_items || state.scenarios["VISUAL_QA"].raw_items,
      });
    }
    await adoptPacket(packet);
    if ($("#global-error")) $("#global-error").hidden = true;
    if (directId) openReceipt(packet);
  } catch (error) {
    if ($("#global-error")) {
      $("#global-error").textContent =
        `Could not load the workspace: ${error.message}. Reload to try again.`;
      $("#global-error").hidden = false;
    }
    throw error;
  } finally {
    setBusy(false);
  }
}

async function adoptPacket(packet) {
  state.packet = packet;
  state.workflow = packet.workflow_type;
  state.filter = "all";
  if ($("#workflow-select")) $("#workflow-select").value = state.workflow;
  if ($("#scope-toggle")) $("#scope-toggle").checked = Boolean(packet.raw_input?.has_marked_asana_scope);
  if ($("#matrix-toggle")) $("#matrix-toggle").checked = Boolean(packet.raw_input?.has_device_matrix);
  saveLocal(`receipt.${state.workflow}`, packet.validation_id);
  if ($("#scenario-description")) {
    $("#scenario-description").textContent =
      state.scenarios[state.workflow]?.description || "Workflow Active";
  }
  if ($("#scenario-notice")) {
    $("#scenario-notice").hidden = !packet.simulated;
  }
  $$(".scenario-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.dataset.scenario === state.workflow);
  });
  renderQueue();
  try {
    state.events = await api(`/val/${packet.validation_id}/events`);
    if (!state.events || state.events.length === 0) {
      const initEvent = await api("/copilot/recover", {
        validation_id: packet.validation_id,
        autonomy_mode: state.autonomy_mode,
      });
      state.events = [initEvent];
    }
  } catch (err) {
    console.warn("Could not load/seed recovery events:", err);
  }
  renderRecovery();
  await refreshEconomics();
}

async function runPreflight(rawItems) {
  setBusy(true);
  try {
    const packet = await api("/preflight/evaluate", {
      workflow_type: state.workflow,
      has_marked_asana_scope: $("#scope-toggle").checked,
      has_device_matrix: $("#matrix-toggle").checked,
      raw_items: rawItems || state.packet.raw_input.raw_items,
    });
    await adoptPacket(packet);
    if (location.pathname.startsWith("/val/"))
      history.replaceState(null, "", "/");
    return packet;
  } catch (error) {
    if (state.packet) {
      $("#scope-toggle").checked =
        state.packet.raw_input.has_marked_asana_scope;
      $("#matrix-toggle").checked = state.packet.raw_input.has_device_matrix;
    }
    throw error;
  } finally {
    setBusy(false);
  }
}

function shortSummary(item) {
  const text = item.issue_summary;
  if (/^Header is nearly edge/.test(text)) return "Header near edges at 390px";
  if (/^Headline looks too tight/.test(text))
    return "Headline feels tight at 390px";
  if (/^Update the timer label/.test(text)) return "Timer label → “HOURS”";
  if (/^Increase the font size/.test(text)) return "Increase text size to 18px";
  if (/^Remove the divider/.test(text)) return "Divider in non-scrolling state";
  if (/^Switch items 3 and 4/.test(text)) return "Switch feature items 3 & 4";
  return text.length > 90 ? `${text.slice(0, 87)}…` : text;
}

function renderQueue() {
  const packet = state.packet;
  if (!packet) return;
  const blocked = packet.step_0_scope_status !== "PASSED";
  const gaps = packet.queue_items.filter(
    (item) => item.status !== "CONFIRMED_READY",
  ).length;
  if ($("#scope-notice")) $("#scope-notice").hidden = !blocked;
  if ($("#scope-step")) $("#scope-step").className = blocked ? "current" : "done";
  if ($("#metric-observations")) $("#metric-observations").innerHTML = `${blocked ? "0" : packet.queue_items.length}<span>items</span>`;
  if ($("#metric-observation-foot")) $("#metric-observation-foot").textContent = blocked ? "Halted before rule evaluation" : `${packet.checklist_rules.length} rules · hybrid triage`;
  if ($("#metric-gaps")) $("#metric-gaps").innerHTML = `${gaps}<span>${blocked ? "scope-blocked" : "to resolve"}</span>`;
  if ($("#nav-count")) $("#nav-count").textContent = gaps;
  if ($("#queue-total")) $("#queue-total").textContent = packet.queue_items.length;
  if ($("#queue-status")) {
    $("#queue-status").textContent = blocked
      ? "Scope blocked"
      : gaps
        ? "Needs evidence"
        : "Ready for handoff";
    $("#queue-status").className = `status-chip ${blocked ? "fail" : gaps ? "" : "pass"}`;
  }
  if ($("#receipt-label")) {
    $("#receipt-label").textContent = `${packet.validation_id.slice(0, 13)}… · Saved receipt`;
  }
  $$(".tab").forEach((tab) =>
    tab.classList.toggle("active", tab.dataset.filter === state.filter),
  );
  const filtered = packet.queue_items.filter(
    (item) =>
      state.filter === "all" ||
      (state.filter === "ready"
        ? item.status === "CONFIRMED_READY"
        : item.status !== "CONFIRMED_READY"),
  );
  const queueBody = $("#queue-body");
  if (queueBody) queueBody.innerHTML = filtered.length
    ? filtered
      .map((item) => {
        const ready = item.status === "CONFIRMED_READY";
        const roleClass =
          item.accountable_role === "Product Owner"
            ? "product"
            : item.accountable_role === "Designer"
              ? "design"
              : "";
        const initials = item.accountable_role
          .split(" ")
          .map((word) => word[0])
          .join("")
          .slice(0, 2);
        const meta =
          item.entities.popup_variant ||
          state.packet.raw_input.raw_items.find(
            (raw) => raw.id === item.source_id,
          )?.author ||
          "Submitted observation";
        const next = blocked
          ? "Mark scope & attach matrix"
          : ready
            ? "Evidence accepted · ready to hand off"
            : item.accountable_role === "Product Owner"
              ? "Confirm copy / feature order"
              : item.accountable_role === "Experiment Owner"
                ? "Source baseline & agree test plan"
                : item.accountable_role === "Paid Media Lead"
                  ? "Substantiate claim & offer terms"
                  : item.accountable_role === "CX Retention Lead"
                    ? "Stage $0 topper draft order"
                    : item.accountable_role === "Designer"
                      ? "Confirm both scroll states"
                      : item.entities.element_named
                        ? "Capture & verify against design"
                        : "Identify, measure, then verify";
        return `<tr>
            <td>
              <div class="observation">
                <span class="source-id">${escapeHTML(item.source_id)}</span>
                <div>
                  <div class="observation-title">${escapeHTML(shortSummary(item))}</div>
                  <div class="observation-meta">${escapeHTML(meta)}${item.merge_status === "KEEP_SEPARATE_PENDING_EVIDENCE" ? ` · ${icon("link")} Keep separate` : ""}</div>
                </div>
              </div>
            </td>
            <td>
              <div class="verify-label ${ready ? "mint" : ""}">${icon(ready ? "check" : "clock")}${blocked ? "Blocked · scope" : ready ? "Confirmed ready" : "Unconfirmed"}</div>
              <div class="evidence-detail">${escapeHTML(ready ? "Reviewer accepted evidence" : item.missing_evidence.slice(0, 2).join(" · "))}${item.missing_evidence.length > 2 ? ` +${item.missing_evidence.length - 2}` : ""}</div>
            </td>
            <td>
              <div class="owner"><span class="owner-avatar ${roleClass}">${escapeHTML(initials)}</span><span class="owner-name">${escapeHTML(item.accountable_role)}</span></div>
              <div class="owner-action">${escapeHTML(next)}</div>
            </td>
            <td>
              <button class="val-link-badge ${ready ? "pass" : "needs-evidence"}" data-source="${escapeHTML(item.source_id)}" aria-label="Open LLM Validation Link for ${escapeHTML(item.source_id)}">
                ${icon("link")} ${ready ? "PASS" : "NEEDS_EVIDENCE"}
              </button>
            </td>
          </tr>`;
      })
      .join("")
    : '<tr><td colspan="4" class="empty-state">No findings in this view. Confirm evidence in a validation receipt to move an item to Ready.</td></tr>';

  $$(".val-link-badge").forEach((button) =>
    button.addEventListener("click", () =>
      openReceipt(packet, button.dataset.source),
    ),
  );
  renderPipeline();
}

function renderPipeline() {
  if (!state.packet) return;
  const scoped = state.packet.step_0_scope_status === "PASSED";
  const ready = state.packet.overall_status === "PASS";
  const approved =
    state.report?.expansion_gate_evaluation.verdict === "APPROVED_FOR_ROLLOUT";
  const classes = [
    scoped ? "done" : "current",
    scoped ? "done" : "",
    scoped ? (ready ? "done" : "current") : "",
    state.events.length ? "done" : "",
    state.report ? "done" : "",
    approved ? "done" : "",
  ];
  $$(".pipeline li").forEach((step, index) => {
    step.className = classes[index];
  });
}

async function refreshEconomics() {
  if (!state.packet) return;
  const version = ++state.economicsVersion;
  const report = await api("/economics/calculate", {
    ...state.settings,
    workflow_type: state.workflow,
    validation_id: state.packet.validation_id,
  });
  if (version !== state.economicsVersion) return;
  state.report = report;
  saveLocal(`settings.${state.workflow}`, state.settings);
  renderEconomics();
  updatePersona(state.persona);
}

function renderEconomics() {
  const report = state.report;
  if (!report) return;
  const effort = report.ai_pilot_breakdown_mins;
  const quality = report.quality_audit;
  const gate = report.expansion_gate_evaluation;
  const total = effort.total_assisted_person_mins;

  const elReduction = $("#metric-reduction");
  if (elReduction) {
    elReduction.innerHTML = `${number(report.net_effort_reduction_pct)}<span>%</span>`;
    elReduction.classList.toggle("mint", report.net_effort_reduction_pct >= 20);
    elReduction.classList.toggle("amber", report.net_effort_reduction_pct < 20);
  }
  const elReductionFoot = $("#metric-reduction-foot");
  if (elReductionFoot) {
    elReductionFoot.textContent = `${number(total)} min assisted vs. 84 min baseline`;
  }
  const elPrecision = $("#metric-precision");
  if (elPrecision) {
    elPrecision.innerHTML = `${number(quality.true_unique_precision_pct)}<span>%</span>`;
  }
  const elAssistedTotal = $("#assisted-total");
  if (elAssistedTotal) elAssistedTotal.textContent = number(total);

  const elAssistedBarLabel = $("#assisted-bar-label");
  if (elAssistedBarLabel) elAssistedBarLabel.textContent = `${number(total)} min`;

  const elEffortDelta = $("#effort-delta");
  if (elEffortDelta) {
    elEffortDelta.textContent = `${total <= 84 ? "−" : "+"}${number(Math.abs(84 - total))} min`;
  }

  const max = Math.max(100, total);
  const elManualBar = $(".manual-bar");
  if (elManualBar) elManualBar.style.width = `${(84 / max) * 100}%`;

  const elAssistedBar = $("#assisted-bar");
  if (elAssistedBar) {
    elAssistedBar.innerHTML = [
      ["prep", effort.unrecorded_prep_mins],
      ["generation", 18],
      ["review", 14],
      ["rework", effort.rework_and_logging_mins + effort.exception_rework_mins],
    ]
      .map(
        ([name, value]) =>
          `<span class="${name}" style="width:${(value / max) * 100}%" title="${name}: ${number(value)} min"></span>`,
      )
      .join("");
  }

  const elExceptionCost = $("#exception-cost");
  if (elExceptionCost) {
    elExceptionCost.hidden = effort.exception_rework_mins === 0;
    elExceptionCost.textContent = `+${number(effort.exception_rework_mins)} min estimated recovery effort from the copilot. Added separately to base rework.`;
  }

  const elCapacityHours = $("#capacity-hours");
  if (elCapacityHours) {
    elCapacityHours.innerHTML = `${report.capacity_released_hours.toFixed(2)} <small>hrs</small>`;
  }

  const elCapacityValue = $("#capacity-value");
  if (elCapacityValue) {
    elCapacityValue.textContent = money(report.net_capacity_value_after_costs);
  }

  // Annualized values
  const elAnnLabel = $("#annualized-label");
  if (elAnnLabel) {
    elAnnLabel.textContent = `ANNUALIZED IMPACT (${(report.monthly_task_volume * 12).toLocaleString()} TASKS/YR)`;
  }
  const elAnnCap = $("#annual-capacity-hours");
  if (elAnnCap) elAnnCap.textContent = `${number(report.annualized_capacity_hours, 1)} hrs`;
  const elAnnNet = $("#annual-net-value");
  if (elAnnNet) {
    elAnnNet.textContent = state.settings.currency === "AED"
      ? `AED ${number(report.annualized_net_benefit, 2)}`
      : `$${number(report.annualized_net_benefit, 2)}`;
  }

  // Enterprise Portfolio Attribution Table
  if ($("#portfolio-tbody") && report.portfolio_workflows) {
    $("#portfolio-tbody").innerHTML = report.portfolio_workflows
      .map((wf) => {
        const deltaClass = wf.net_effort_delta_pct < 0 ? "mint" : "red";
        const valStr = state.settings.currency === "AED"
          ? `AED ${number(wf.annualized_net_value_aed, 0)}`
          : `$${number(wf.annualized_net_value_usd, 0)}`;
        const verdictClass =
          wf.governance_verdict === "APPROVED_FOR_ROLLOUT"
            ? "approved"
            : wf.governance_verdict === "CONTROLLED_10_TASK_TRIAL"
              ? "trial"
              : "sunset";
        const classSlug = wf.economic_classification.toLowerCase().replace(/_/g, "-");
        return `<tr>
          <td><strong class="wf-title">${escapeHTML(wf.workflow_name)}</strong><br><small class="wf-owner">${escapeHTML(wf.owner)}</small></td>
          <td class="mono-cell">${escapeHTML(wf.baseline_effort)}</td>
          <td class="mono-cell">${escapeHTML(wf.post_ai_effort)}</td>
          <td><span class="delta-badge ${deltaClass}">${wf.net_effort_delta_pct > 0 ? "+" : ""}${wf.net_effort_delta_pct}%</span></td>
          <td><span class="class-badge ${classSlug}">${escapeHTML(wf.economic_classification.replace(/_/g, " "))}</span></td>
          <td><strong class="val-cell ${wf.annualized_net_value_usd < 0 ? 'negative' : ''}">${valStr}</strong></td>
          <td><span class="portfolio-verdict ${verdictClass}">${escapeHTML(wf.governance_verdict.replace(/_/g, " "))}</span></td>
        </tr>`;
      })
      .join("");
  }

  const parts = [
    ["Unique in-scope", quality.true_unique_valid, "#059669"],
    ["Estimated repeats", quality.estimated_duplicates, "#0284c7"],
    ["Out of scope", 2, "#d97706"],
    ["Not issues", 10, "#dc2626"],
    ["By design", 4, "#64748b"],
  ];
  let cumulative = 0;
  const elPrecisionDonut = $("#precision-donut");
  if (elPrecisionDonut) {
    elPrecisionDonut.style.background = `conic-gradient(${parts
      .map(([, value, color]) => {
        const start = cumulative;
        cumulative += (value / 40) * 100;
        return `${color} ${start}% ${cumulative}%`;
      })
      .join(",")})`;
  }
  const elQualityUnique = $("#quality-unique");
  if (elQualityUnique) elQualityUnique.textContent = quality.true_unique_valid;

  const elQualityLegend = $("#quality-legend");
  if (elQualityLegend) {
    elQualityLegend.innerHTML = parts
      .map(
        ([label, value, color]) =>
          `<div><i style="background:${color}"></i>${label}<strong>${value}</strong></div>`,
      )
      .join("");
  }

  const approved = gate.verdict === "APPROVED_FOR_ROLLOUT";
  const hold = gate.verdict === "HOLD_EXTEND_TRIAL";
  const elGateVerdict = $("#gate-verdict");
  if (elGateVerdict) {
    elGateVerdict.className =
      `gate-verdict ${approved ? "approved" : hold ? "hold" : ""}`;
    elGateVerdict.innerHTML =
      `${approved ? "Approved for rollout" : hold ? "Hold / extend trial" : "Controlled trial only"}${icon(approved ? "check" : "arrow")}`;
  }

  const elTrialDots = $("#trial-dots");
  if (elTrialDots) {
    elTrialDots.innerHTML = Array.from(
      { length: 10 },
      (_, index) =>
        `<span class="trial-dot ${index < gate.trial_task_count ? "recorded" : ""}"></span>`,
    ).join("");
    elTrialDots.setAttribute(
      "aria-label",
      `${gate.trial_task_count} of 10 trial tasks recorded`,
    );
  }

  const trialQuality =
    gate.trial_task_count === 10 &&
    state.settings.trial_tasks.every(
      (task) => task.major_misses_assisted <= task.major_misses_baseline,
    );
  const releaseQuality =
    gate.release_cycle_count === 2 &&
    state.settings.release_cycles.every(
      (cycle) =>
        cycle.assisted_escaped_defects <= cycle.baseline_escaped_defects,
    );

  const criteria = [
    [
      gate.meets_effort_threshold,
      "≥20% median effort reduction",
      gate.median_effort_reduction_pct === null
        ? "Pilot only"
        : `${number(gate.median_effort_reduction_pct)}%`,
    ],
    [
      trialQuality,
      "No additional major misses",
      gate.trial_task_count === 10
        ? trialQuality
          ? "Passed"
          : "Failed"
        : "Pending",
    ],
    [
      releaseQuality,
      "No increase in escaped defects",
      gate.release_cycle_count === 2
        ? releaseQuality
          ? "2 cycles passed"
          : "Failed"
        : `${gate.release_cycle_count}/2 cycles`,
    ],
  ];

  const elGateCriteria = $("#gate-criteria");
  if (elGateCriteria) {
    elGateCriteria.innerHTML = criteria
      .map(
        ([pass, label, value]) =>
          `<div class="criterion ${pass ? "passed" : "pending"}">${icon(pass ? "check" : "clock")}<span>${label}</span><span>${value}</span></div>`,
      )
      .join("");
  }

  const elGateExplanation = $("#gate-explanation");
  if (elGateExplanation) {
    elGateExplanation.textContent = approved
      ? gate.reasons[0]
      : gate.reasons.join(" ");
  }

  renderPipeline();
}

function renderRecovery() {
  renderPipeline();
  const event = state.events.at(-1);
  const pending = state.packet.queue_items.some(
    (item) => item.status !== "CONFIRMED_READY",
  );
  $("#simulate-button").textContent = event
    ? "Incident already recorded"
    : "Simulate cross-hub stall";
  $("#simulate-button").disabled = Boolean(event) || !pending;

  if (!event) {
    $("#copilot-content").className = "copilot-empty";
    $("#copilot-content").innerHTML =
      `<div class="copilot-symbol">${icon("flow")}</div><div><h3>${pending ? "A stalled task should have a next step." : "Every finding is ready for handoff."}</h3><p>${pending ? "Simulate a five-hour handoff across the Dubai-to-LA timezone gap. Get owner-specific structured runbooks and stage write-backs." : "All observations have a human evidence decision. No recovery is needed for this receipt."}</p></div>`;
    $("#handoff-badge").innerHTML =
      `${icon(pending ? "clock" : "check")}${pending ? "Waiting for evidence" : "Ready for handoff"}`;
    $("#recovery-note").textContent =
      "Structured runbooks · 1-click staged writes available";
    return;
  }

  $("#handoff-badge").innerHTML = `${icon("clock")}5h handoff · simulated`;
  $("#copilot-content").className = "runbooks";

  const runbooksHtml = event.asana_auto_comments
    .map((comment, index) => {
      const guardrailHtml = comment.do_not_do_guardrail
        ? `<div class="guardrail-banner">${icon("shield")} <strong>DO NOT DO:</strong> ${escapeHTML(comment.do_not_do_guardrail)}</div>`
        : "";
      const steps = comment.numbered_action_steps || comment.steps;
      return `<article class="runbook">
        <div class="runbook-heading">
          <h3>${escapeHTML(comment.target_role)} <span class="runbook-sla">${escapeHTML(comment.sla_window || "4h SLA")}</span> <span>${comment.items.map(escapeHTML).join(" / ")}</span></h3>
          <button class="text-button" data-copy-runbook="${index}">${icon("file")} Copy draft</button>
        </div>
        ${guardrailHtml}
        <ol>${steps.map((step) => `<li>${escapeHTML(step)}</li>`).join("")}</ol>
        ${comment.self_heal_verification_check ? `<p class="muted small-text" style="margin-top:6px;"><strong>Clearance Condition:</strong> ${escapeHTML(comment.self_heal_verification_check)}</p>` : ""}
      </article>`;
    })
    .join("");

  const stagedHtml = event.staged_actions && event.staged_actions.length
    ? `<div class="staged-actions-wrap">
        <span class="label">STAGED WRITES (CONTROL-BY-DESIGN)</span>
        ${event.staged_actions
      .map((action) => {
        const confirmed = action.status === "EXECUTED_WRITEBACK_CONFIRMED";
        return `<div class="staged-action-card">
              <div>
                <strong>${escapeHTML(action.action_type)}</strong> <span class="badge-system">${escapeHTML(action.target_system)}</span>
                <p>${escapeHTML(action.description)}</p>
              </div>
              <button class="button small staged-action-btn ${confirmed ? "confirmed" : "primary"}" data-event-id="${event.event_id}" data-action-id="${action.action_id}" ${confirmed ? "disabled" : ""}>
                ${confirmed ? `✓ Executed (${escapeHTML(action.execution_receipt)})` : "Approve & Execute"}
              </button>
            </div>`;
      })
      .join("")}
      </div>`
    : "";

  $("#copilot-content").innerHTML = runbooksHtml + stagedHtml;
  $("#recovery-note").textContent =
    `+${number(event.total_rework_minutes_added)} min estimated · 5 min / follow-up${state.packet.step_0_scope_status !== "PASSED" ? " (one scope issue)" : ""}`;

  $$("[data-copy-runbook]").forEach((button) =>
    button.addEventListener("click", () =>
      copyText(
        event.asana_auto_comments[Number(button.dataset.copyRunbook)]
          .plain_english_runbook,
      ),
    ),
  );

  $$(".staged-action-btn:not(.confirmed)").forEach((button) =>
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Executing...";
      try {
        const res = await api("/copilot/staged-write/execute", {
          event_id: button.dataset.eventId,
          action_id: button.dataset.actionId,
          actor: state.persona === "CEO" ? "CEO Cockpit" : (state.persona === "COO" ? "COO / Transformation" : "CAIO / Systems"),
          role: state.persona,
          rationale: "Approved staged writeback under SLA boundary.",
        });
        toast("Staged write executed. Receipt logged into Decision Memory.");
        state.events = [res.event];
        renderRecovery();
      } catch (err) {
        toast(`Execution failed: ${err.message}`, true);
        renderRecovery();
      }
    }),
  );
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard.");
  } catch {
    toast("Clipboard is unavailable. Select and copy the text directly.", true);
  }
}

function showDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog && !dialog.open) dialog.showModal();
}

function downloadJSON(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function openReceipt(packet, focusSource = null) {
  state.receipt = packet;
  const items = focusSource
    ? packet.queue_items.filter((item) => item.source_id === focusSource)
    : packet.queue_items;
  $("#receipt-content").innerHTML = `
    <div class="receipt-meta"><code>${escapeHTML(packet.validation_id)}</code><span class="status-chip ${packet.overall_status === "PASS" ? "pass" : packet.overall_status === "FAIL" ? "fail" : ""}">${packet.overall_status.replaceAll("_", " ")}</span><small>${new Date(packet.timestamp_utc).toLocaleString()} · stored in UTC</small></div>
    <div class="receipt-actions"><button class="button secondary small" id="copy-permalink">${icon("link")} Copy validation link</button><button class="button secondary small" id="download-receipt">${icon("download")} Receipt JSON</button></div>
    ${packet.parent_validation_id ? `<div class="receipt-section"><p>Revision of <code>${escapeHTML(packet.parent_validation_id)}</code>. The original receipt is preserved.</p></div>` : ""}
    <section class="receipt-section"><h3>Reusable validation prompt</h3><pre>${escapeHTML(packet.reusable_prompt_used)}</pre><p>Rules engine only · 0 LLM tokens. This prompt is saved for reuse; no model execution is claimed.</p></section>
    <section class="receipt-section"><h3>Source observations · raw input</h3><pre>${packet.raw_input.raw_items
      .filter((raw) => !focusSource || raw.id === focusSource)
      .map(
        (raw) =>
          `${escapeHTML(raw.id)} · ${escapeHTML(raw.author)}\n${escapeHTML(raw.comment_text)}`,
      )
      .join("\n\n")}</pre></section>
    <section class="receipt-section"><h3>Verification & next actions</h3>${items.map((item) => `<article class="audit-item"><h4>${escapeHTML(item.source_id)} · ${escapeHTML(shortSummary(item))}</h4><p><strong>Status:</strong> ${item.status.replaceAll("_", " ")}</p><p><strong>Missing:</strong> ${escapeHTML(item.missing_evidence.join("; ") || "Evidence accepted by reviewer")}</p><p><strong>Merge guardrail:</strong> ${escapeHTML(item.merge_guardrail_note)}</p><p><strong>${escapeHTML(item.accountable_role)}:</strong> ${escapeHTML(item.next_action)}</p><p><strong>Extracted:</strong> element ${escapeHTML(item.entities.element || "unknown")} · viewport ${item.entities.viewport_px || "unknown"} · measured value ${escapeHTML(item.entities.measured_value || "not supplied")}</p></article>`).join("")}</section>
    <section class="receipt-section"><h3>Active truth & rule pack</h3><ul>${packet.checklist_rules.map((rule) => `<li>${escapeHTML(rule)}</li>`).join("")}</ul></section>
    <section class="receipt-section"><h3>Verification check log</h3><ul>${packet.verification_check_log.map((check) => `<li>${escapeHTML(check)}</li>`).join("")}</ul><p><strong>Initial model output:</strong> ${escapeHTML(packet.initial_ai_output_excerpt || "Supplied observations are audited as unverified claims.")}</p></section>
    <section class="receipt-section"><h3>Human decisions</h3>${packet.human_override_decisions.length ? packet.human_override_decisions.map((decision) => `<article class="audit-item"><h4>${escapeHTML(decision.source_id)} · ${escapeHTML(decision.reviewer)} · ${decision.decision.replaceAll("_", " ")}</h4><p>${escapeHTML(decision.rationale)}</p><p>References: ${escapeHTML(decision.evidence_references.join("; ") || "None")}</p></article>`).join("") : "<p>No human override recorded. All source observations remain unconfirmed until reviewed.</p>"}</section>
    ${packet.step_0_scope_status === "PASSED" ? `<section class="receipt-section"><h3>Record a human evidence decision</h3><form id="decision-form" class="decision-form"><p>A named reviewer can attest to evidence. This creates a new linked receipt. References are recorded, not automatically verified.</p><label class="field-label" for="decision-source">Source item</label><select id="decision-source">${packet.queue_items.map((item) => `<option ${item.source_id === focusSource ? "selected" : ""} value="${escapeHTML(item.source_id)}">${escapeHTML(item.source_id)} · ${escapeHTML(shortSummary(item))}</option>`).join("")}</select><label class="field-label" for="decision-type">Decision</label><select id="decision-type"><option value="REQUEST_EVIDENCE">Request evidence</option><option value="CONFIRM">Confirm ready — evidence reviewed</option></select><label class="field-label" for="decision-reviewer">Reviewer name</label><input type="text" id="decision-reviewer" required minlength="2" maxlength="100" placeholder="Who reviewed the evidence?"><label class="field-label" for="decision-rationale">Verification performed / rationale</label><textarea id="decision-rationale" required minlength="10" maxlength="3000" rows="3" placeholder="Describe what was checked and what it establishes."></textarea><label class="field-label" for="decision-evidence">Evidence references · one URL or artifact ID per line</label><textarea id="decision-evidence" rows="2" placeholder="Design version, element crop, device check, or measurement artifact"></textarea><button class="button primary" type="submit">Save as a new receipt ${icon("arrow")}</button></form></section>` : '<section class="receipt-section"><p>Resolve the scope gate before recording evidence decisions.</p></section>'}`;

  on("#copy-permalink", "click", () =>
    copyText(`${location.origin}${packet.permalink}`),
  );
  on("#download-receipt", "click", () =>
    downloadJSON(`${packet.validation_id}.json`, packet),
  );
  if ($("#decision-form")) {
    on("#decision-type", "change", () => {
      $("#decision-evidence").required =
        $("#decision-type").value === "CONFIRM";
    });
    on("#decision-form", "submit", async (event) => {
      event.preventDefault();
      const submit = $("#decision-form button[type=submit]");
      submit.disabled = true;
      try {
        const revised = await api(`/val/${packet.validation_id}/decisions`, {
          source_id: $("#decision-source").value,
          reviewer: $("#decision-reviewer").value.trim(),
          decision: $("#decision-type").value,
          rationale: $("#decision-rationale").value.trim(),
          evidence_references: $("#decision-evidence")
            .value.split("\n")
            .map((value) => value.trim())
            .filter(Boolean),
        });
        if (revised.workflow_type !== state.workflow) {
          state.settings = {
            ...defaults(),
            ...readLocal(`settings.${revised.workflow_type}`, {}),
          };
          synchronizeControls();
        }
        await adoptPacket(revised);
        openReceipt(revised);
        if (location.pathname.startsWith("/val/"))
          history.replaceState(null, "", revised.permalink);
        toast("Decision saved. A new immutable receipt was created.");
      } finally {
        submit.disabled = false;
      }
    });
  }
  showDialog("receipt-dialog");
  $("#receipt-dialog").scrollTop = 0;
}

function taskRow(task, index) {
  const fields = [
    "manual_baseline_mins",
    "prep_mins",
    "ai_mins",
    "review_mins",
    "logging_mins",
    "rework_mins",
  ];
  return `<tr data-task-row>
    <td><input class="task-id" name="task_id" value="${escapeHTML(task.task_id || `Task-${index + 1}`)}" required maxlength="100" aria-label="Task ID"></td>
    ${fields.map((field) => `<td><input type="number" name="${field}" value="${task[field] ?? ""}" min="${field === "manual_baseline_mins" ? ".1" : "0"}" max="10080" step=".1" required aria-label="${field.replaceAll("_", " ")}"></td>`).join("")}
    <td><input class="miss-input" type="number" name="major_misses_baseline" value="${task.major_misses_baseline ?? 0}" min="0" max="10000" required aria-label="Baseline misses"> / <input class="miss-input" type="number" name="major_misses_assisted" value="${task.major_misses_assisted ?? 0}" min="0" max="10000" required aria-label="Assisted misses"></td>
    <td><input type="checkbox" name="comparable_scope_confirmed" ${task.comparable_scope_confirmed ? "checked" : ""} aria-label="Scope confirmed"></td>
    <td><button class="icon-button remove-task" type="button" aria-label="Remove task">${icon("close")}</button></td>
  </tr>`;
}

function attachTaskRemove() {
  $$(".remove-task").forEach((button) => {
    button.onclick = () => {
      button.closest("tr").remove();
      $("#add-trial").disabled = false;
    };
  });
  $("#add-trial").disabled = $$("[data-task-row]").length >= 10;
}

function openTrial() {
  $("#trial-rows").innerHTML = state.settings.trial_tasks.map(taskRow).join("");
  $("#release-inputs").innerHTML = Array.from({ length: 2 }, (_, index) => {
    const cycle = state.settings.release_cycles.find(
      (cycle) => cycle.cycle_id === `Cycle ${index + 1}`,
    );
    return `<div class="release-card" data-release="Cycle ${index + 1}"><label><input type="checkbox" class="cycle-observed" ${cycle ? "checked" : ""}> Release cycle ${index + 1} observed</label><div><label>Baseline escapes<input class="cycle-before" type="number" min="0" max="10000" value="${cycle?.baseline_escaped_defects ?? ""}" ${cycle ? "required" : "disabled"} aria-label="Cycle ${index + 1} baseline escapes"></label><label>Assisted escapes<input class="cycle-after" type="number" min="0" max="10000" value="${cycle?.assisted_escaped_defects ?? ""}" ${cycle ? "required" : "disabled"} aria-label="Cycle ${index + 1} assisted escapes"></label></div></div>`;
  }).join("");
  $$(".cycle-observed").forEach((checkbox) =>
    checkbox.addEventListener("change", () => {
      $$("input[type=number]", checkbox.closest(".release-card")).forEach(
        (input) => {
          input.disabled = !checkbox.checked;
          input.required = checkbox.checked;
        },
      );
    }),
  );
  attachTaskRemove();
  showDialog("trial-dialog");
}

function bindEvents() {
  on("#workflow-select", "change", (event) => loadWorkflow(event.target.value));
  $$(".scenario-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      $$(".scenario-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      const scenario = pill.dataset.scenario;
      if ($("#workflow-select")) $("#workflow-select").value = scenario;
      loadWorkflow(scenario);
    });
  });
  on("#scope-toggle", "change", () => runPreflight());
  on("#matrix-toggle", "change", () => runPreflight());

  // Persona switcher
  $$(".persona-tab").forEach((tab) => {
    tab.addEventListener("click", () => updatePersona(tab.dataset.persona));
  });

  // Currency toggle
  on("#currency-toggle", "click", async () => {
    state.settings.currency = state.settings.currency === "USD" ? "AED" : "USD";
    $("#currency-toggle").textContent = state.settings.currency === "AED" ? "AED د.إ" : "USD $";
    await refreshEconomics();
    toast(`Switched reporting currency to ${state.settings.currency}.`);
  });

  // Autonomy tabs
  $$(".autonomy-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".autonomy-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.autonomy_mode = tab.dataset.mode;
      toast(`Autonomy mode updated to ${tab.dataset.mode}.`);
    });
  });

  // Volume slider
  on("#volume-slider", "input", (event) => {
    state.settings.monthly_task_volume = Number(event.target.value);
    $("#volume-label").textContent = `${event.target.value} tasks/mo`;
    clearTimeout(economicsTimer);
    economicsTimer = setTimeout(() => refreshEconomics(), 90);
  });

  // Benchmark trial pre-loader
  on("#benchmark-trial-btn", "click", async () => {
    try {
      const benchmark = await api("/benchmark-trial");
      state.settings.trial_tasks = benchmark.trial_tasks;
      state.settings.release_cycles = benchmark.release_cycles;
      openTrial();
      toast("Loaded 10-Task Benchmark Trial dataset. Ready to evaluate expansion gate.");
    } catch (err) {
      toast(`Failed to load benchmark data: ${err.message}`, true);
    }
  });

  // Process Diff Banner toggle
  const diffToggle = () => {
    const content = $("#diff-content-panel");
    const btn = $("#diff-collapse-btn");
    if (content && btn) {
      const isHidden = content.hasAttribute("hidden");
      if (isHidden) {
        content.removeAttribute("hidden");
        btn.classList.add("open");
      } else {
        content.setAttribute("hidden", "");
        btn.classList.remove("open");
      }
    }
  };
  on("#diff-toggle-header", "click", diffToggle);
  on("#diff-collapse-btn", "click", (e) => {
    e.stopPropagation();
    diffToggle();
  });

  // n8n Webhook simulation
  on("#n8n-webhook-btn", "click", async () => {
    setBusy(true);
    try {
      const gid = `n8n-${Date.now().toString().slice(-6)}`;
      const res = await api("/webhooks/inbound", {
        source: "n8n",
        workflow_type: state.workflow || "VISUAL_QA",
        task_gid: gid,
        webhook_event: "asana.task.created",
        data: {
          gid: gid,
          name: "Cart CTA overlap on mobile drawer at 390px",
          notes: "Reviewer detected that the CTA button padding clips into the trust badge at 390px mobile viewport.",
          author: "n8n Webhook Automation",
        },
      });
      state.packet = res;
      renderQueue(res);
      renderAuditDetails(res);
      toast(`Live n8n Webhook Ingested! Minted ${res.validation_id}`);
    } finally {
      setBusy(false);
    }
  });

  // Modular View Switching
  function switchView(viewName) {
    if (!viewName) return;
    // Map aliases
    if (viewName === "pre-flight" || viewName === "gate") viewName = "preflight";
    if (viewName === "roi" || viewName === "portfolio") viewName = "economics";

    $$(".nav-link").forEach((nav) => {
      if (nav.dataset.view === viewName) {
        nav.classList.add("active");
      } else {
        nav.classList.remove("active");
      }
    });

    $$(".view-pane").forEach((pane) => {
      if (pane.id === `view-${viewName}`) {
        pane.classList.add("active");
      } else {
        pane.classList.remove("active");
      }
    });

    if (viewName === "audit") {
      loadInlineAuditTrail();
      loadLLMUsageLogs();
    } else if (viewName === "memory") {
      loadInlineDecisionMemory();
    }

    $(".main-content")?.scrollTo({ top: 0, behavior: "smooth" });
  }

  $$(".nav-link[data-view]").forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      switchView(button.dataset.view);
    });
  });

  // View mode switcher: Tabs vs Continuous Executive Scroll
  on("#btn-view-tabs", "click", () => {
    document.body.classList.remove("show-all-views");
    $("#btn-view-tabs")?.classList.add("active");
    $("#btn-view-scroll")?.classList.remove("active");
    toast("View Mode: Modular Tabs enabled.");
  });

  on("#btn-view-scroll", "click", () => {
    document.body.classList.add("show-all-views");
    $("#btn-view-scroll")?.classList.add("active");
    $("#btn-view-tabs")?.classList.remove("active");
    toast("View Mode: Continuous Executive Scroll enabled.");
  });

  // Decision loop pills
  on("#pill-see", "click", () => switchView("preflight"));
  on("#pill-decide", "click", () => switchView("preflight"));
  on("#pill-act", "click", () => switchView("copilot"));
  on("#pill-remember", "click", () => switchView("memory"));

  // Inline Audit Trail Loader
  async function loadInlineAuditTrail() {
    const container = $("#history-content-inline");
    if (!container) return;
    container.innerHTML = '<p class="muted">Loading persistent audit trail…</p>';
    try {
      const rows = await api(`/validations?workflow_type=${state.workflow}`);
      container.innerHTML = rows.length
        ? rows
          .map(
            (row) =>
              `<div class="history-row"><div><code>${escapeHTML(row.id)}</code><small>${new Date(row.created).toLocaleString()}</small><details><summary>SHA-256 integrity hash</summary><code>${row.sha256}</code></details></div><button class="button secondary small inline-history-open" data-history-id="${escapeHTML(row.id)}">Open Receipt ${icon("up")}</button></div>`,
          )
          .join("")
        : '<p class="muted">No receipts saved yet.</p>';
      $$(".inline-history-open").forEach((btn) =>
        btn.addEventListener("click", async () => {
          try {
            const packet = await api(`/val/${btn.dataset.historyId}`);
            openReceipt(packet);
          } catch (error) {
            toast(error.message, true);
          }
        }),
      );
    } catch (err) {
      container.innerHTML = `<p class="muted error-text">Could not load receipts: ${escapeHTML(err.message)}</p>`;
    }
  }

  // Inline Decision Memory Loader
  async function loadInlineDecisionMemory() {
    const container = $("#memory-content-inline");
    if (!container) return;
    container.innerHTML = '<p class="muted">Loading institutional decision memory…</p>';
    try {
      const entries = await api("/decision-memory");
      container.innerHTML = entries.length
        ? entries
          .map(
            (e) => `<div class="decision-memory-row">
                <div class="decision-memory-header">
                  <code>${escapeHTML(e.entry_id)}</code>
                  <span class="status-chip pass">${escapeHTML(e.human_action)}</span>
                  <small class="muted">${new Date(e.timestamp_utc).toLocaleString()}</small>
                </div>
                <p><strong>Actor:</strong> ${escapeHTML(e.actor)} (${escapeHTML(e.role)}) · <em>${escapeHTML(e.workflow_type)}</em></p>
                <p><strong>AI Recommendation:</strong> ${escapeHTML(e.ai_recommendation)}</p>
                <p><strong>Governance Rule:</strong> ${escapeHTML(e.governance_rule)}</p>
                <p><strong>Outcome / Receipt:</strong> ${escapeHTML(e.predicted_vs_verified_impact)}</p>
              </div>`,
          )
          .join("")
        : '<p class="muted">No decision memory records logged yet. Staged writes and confirmations will appear here.</p>';
    } catch (err) {
      container.innerHTML = `<p class="muted error-text">Could not load decision memory: ${escapeHTML(err.message)}</p>`;
    }
  }

  on("#refresh-audit-btn", "click", loadInlineAuditTrail);
  on("#refresh-memory-btn", "click", loadInlineDecisionMemory);

  // ==================== LLMOPS OBSERVABILITY CONTROLLER ====================
  let cachedLLMLogs = [];

  async function loadLLMUsageLogs() {
    const tbody = $("#llm-logs-tbody");
    if (!tbody) return;
    try {
      const logs = await api("/llm/logs");
      cachedLLMLogs = logs;

      // Calculate aggregate stats
      const totalRuns = logs.length;
      let promptTokens = 0;
      let compTokens = 0;
      let totalTokens = 0;
      let totalLatency = 0;
      let step0Saved = 0;

      logs.forEach((log) => {
        promptTokens += log.prompt_tokens || 0;
        compTokens += log.completion_tokens || 0;
        totalTokens += log.total_tokens || 0;
        totalLatency += log.latency_ms || 0;
        if (log.prompt_tokens === 0 && (log.status || "").includes("0 Tokens")) {
          step0Saved += 320; // Average prompt token allocation avoided
        }
      });

      const avgLatency = totalRuns > 0 ? (totalLatency / totalRuns).toFixed(1) : "0.0";

      // Update stat cards
      if ($("#stat-llm-total-runs")) $("#stat-llm-total-runs").textContent = number(totalRuns, 0);
      if ($("#stat-llm-total-tokens")) $("#stat-llm-total-tokens").textContent = number(totalTokens, 0);
      if ($("#stat-llm-prompt-tokens")) $("#stat-llm-prompt-tokens").textContent = number(promptTokens, 0);
      if ($("#stat-llm-comp-tokens")) $("#stat-llm-comp-tokens").textContent = number(compTokens, 0);
      if ($("#stat-llm-avg-latency")) $("#stat-llm-avg-latency").textContent = `${avgLatency} ms`;
      if ($("#stat-llm-saved-tokens")) $("#stat-llm-saved-tokens").textContent = number(step0Saved, 0);

      // Render table rows
      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-4 text-center text-slate-400">No LLM runs recorded yet. Ingest an Asana task to start logging.</td></tr>';
        return;
      }

      tbody.innerHTML = logs
        .map((log, index) => {
          let statusBadgeClass = "bg-slate-100 text-slate-700 border-slate-200";
          const statusText = log.status || "UNKNOWN";
          if (statusText.includes("200 OK")) {
            statusBadgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
          } else if (statusText.includes("0 Tokens") || statusText.includes("REJECTED")) {
            statusBadgeClass = "bg-purple-50 text-purple-700 border-purple-200";
          } else if (statusText.includes("402") || statusText.includes("Fallback")) {
            statusBadgeClass = "bg-amber-50 text-amber-700 border-amber-200";
          }

          const shortSha = (log.sha256 || "").slice(0, 10) + "...";
          const dateStr = log.timestamp_utc ? new Date(log.timestamp_utc).toLocaleTimeString() : "—";

          return `<tr class="hover:bg-slate-50/80 transition-colors">
            <td class="py-3 px-4 font-mono text-[11px] text-slate-500">${escapeHTML(dateStr)}</td>
            <td class="py-3 px-4 font-mono font-bold text-slate-900">${escapeHTML(log.task_id)}</td>
            <td class="py-3 px-4 font-mono text-[11px] text-indigo-700">${escapeHTML(log.model)}</td>
            <td class="py-3 px-4 font-semibold text-slate-700">${number(log.prompt_tokens, 0)} <span class="text-slate-400">/</span> ${number(log.completion_tokens, 0)}</td>
            <td class="py-3 px-4 font-mono text-slate-700">${log.latency_ms} ms</td>
            <td class="py-3 px-4">
              <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold border ${statusBadgeClass}">${escapeHTML(statusText)}</span>
            </td>
            <td class="py-3 px-4 font-mono text-[10px] text-slate-400 select-all" title="${escapeHTML(log.sha256)}">${escapeHTML(shortSha)}</td>
            <td class="py-3 px-4 text-right">
              <button type="button" class="px-2.5 py-1 text-[11px] font-semibold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 rounded border border-indigo-200 transition-all btn-inspect-llm" data-idx="${index}">
                Inspect
              </button>
            </td>
          </tr>`;
        })
        .join("");

      // Bind inspect buttons
      $$(".btn-inspect-llm", tbody).forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.idx);
          if (cachedLLMLogs[idx]) {
            openLLMInspectModal(cachedLLMLogs[idx]);
          }
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8" class="py-4 text-center text-rose-500">Failed to load LLM usage logs: ${escapeHTML(err.message)}</td></tr>`;
    }
  }

  function openLLMInspectModal(log) {
    const modal = $("#llm-inspect-modal");
    if (!modal) return;
    if ($("#llm-inspect-task-id")) $("#llm-inspect-task-id").textContent = log.task_id;
    if ($("#llm-inspect-model")) $("#llm-inspect-model").textContent = log.model;
    if ($("#llm-inspect-tokens")) $("#llm-inspect-tokens").textContent = `${log.total_tokens} tok (${log.prompt_tokens}p / ${log.completion_tokens}c)`;
    if ($("#llm-inspect-latency")) $("#llm-inspect-latency").textContent = `${log.latency_ms} ms · ${log.status}`;
    if ($("#llm-inspect-prompt")) $("#llm-inspect-prompt").textContent = log.prompt_snippet || "N/A";
    if ($("#llm-inspect-response")) $("#llm-inspect-response").textContent = log.response_snippet || "N/A";
    if ($("#llm-inspect-sha")) $("#llm-inspect-sha").textContent = log.sha256 || "N/A";
    modal.showModal();
  }

  on("#refresh-llm-btn", "click", loadLLMUsageLogs);
  on("#llm-inspect-close", "click", () => $("#llm-inspect-modal")?.close());
  on("#llm-inspect-dismiss", "click", () => $("#llm-inspect-modal")?.close());

  // ==================== ASANA INBOUND & LLM DECISION CONTROLLER ====================
  function initAsanaInboundView() {
    const presets = {
      visual_qa_clip: {
        task_id: "ASN-10924-QA",
        title: "PDP Mobile Checkout CTA Button 375px Padding Clipping",
        workflow_type: "VISUAL_QA",
        author: "Head of QA",
        viewport_spec: "375px Mobile (iPhone 15 Pro / Safari)",
        figma_spec_url: "https://figma.com/file/puffy-pdp-redesign#node-104",
        description: "Reviewer identified Monarch King checkout drawer CTA button overlaps bottom navigation bar when rendered on iPhone 15 Pro viewport at 375px. Computed padding shows 0px margin against bottom safe area.",
        has_marked_scope: true,
        has_device_matrix: true,
        autonomy_mode: "STAGED_APPROVAL",
      },
      cro_hypothesis: {
        task_id: "ASN-10931-CRO",
        title: "PDP Sleep Trial Guarantee vs Saatva Comparison Table MDE",
        workflow_type: "CRO_HYPOTHESIS",
        author: "VP Digital Experience & Conversion",
        viewport_spec: "390px Mobile & 1440px Desktop",
        figma_spec_url: "https://figma.com/file/puffy-cro-tests#v2",
        description: "Experiment proposed to surface 365-night trial guarantee above fold. Requires MDE statistical power confirmation and mobile comparison table hierarchy check.",
        has_marked_scope: true,
        has_device_matrix: true,
        autonomy_mode: "STAGED_APPROVAL",
      },
      ppc_claim_gate: {
        task_id: "ASN-10940-PPC",
        title: "Google Ads Copy: Puffy Cloud Mattress Pocketed Coils",
        workflow_type: "PPC_COPY",
        author: "Director of Paid Media",
        viewport_spec: "Google Ads Responsive Search Format",
        figma_spec_url: "",
        description: "Ad creative submitted claiming Puffy Cloud has pocketed coils. Source pack verification flagged false SKU specification (Puffy Cloud is all-foam, Lux is hybrid).",
        has_marked_scope: true,
        has_device_matrix: true,
        autonomy_mode: "STAGED_APPROVAL",
      },
      trialsave_concession: {
        task_id: "ASN-10955-CX",
        title: "TrialSave-365 Day 82 Return Request: Lower Back Firmness",
        workflow_type: "TRIALSAVE_365",
        author: "Customer Operations Lead",
        viewport_spec: "Zendesk Ticket #88412 / Shopify GraphQL",
        figma_spec_url: "",
        description: "Customer requesting mattress return for Day 82 Puffy Lux Hybrid citing lower back discomfort. Candidate for automated $0 Firm Orthopedic Topper draft order concession.",
        has_marked_scope: true,
        has_device_matrix: true,
        autonomy_mode: "STAGED_APPROVAL",
      },
      step_0_sabotage: {
        task_id: "ASN-10960-UNSCOPED",
        title: "Unscoped PDP Redesign Review Request (Missing Scope)",
        workflow_type: "VISUAL_QA",
        author: "Unassigned Product Associate",
        viewport_spec: "Unspecified",
        figma_spec_url: "",
        description: "Ticket submitted without marked changed sections and without mobile 390px viewport crop references.",
        has_marked_scope: false,
        has_device_matrix: false,
        autonomy_mode: "SHADOW",
      },
    };

    function populateForm(data) {
      if ($("#asana-task-id")) $("#asana-task-id").value = data.task_id;
      if ($("#asana-title")) $("#asana-title").value = data.title;
      if ($("#asana-workflow")) $("#asana-workflow").value = data.workflow_type;
      if ($("#asana-author")) $("#asana-author").value = data.author;
      if ($("#asana-viewport")) $("#asana-viewport").value = data.viewport_spec;
      if ($("#asana-figma")) $("#asana-figma").value = data.figma_spec_url || "";
      if ($("#asana-description")) $("#asana-description").value = data.description;
      if ($("#asana-has-scope")) $("#asana-has-scope").checked = Boolean(data.has_marked_scope);
      if ($("#asana-has-matrix")) $("#asana-has-matrix").checked = Boolean(data.has_device_matrix);
      if ($("#asana-autonomy")) $("#asana-autonomy").value = data.autonomy_mode || "STAGED_APPROVAL";
    }

    // Bind preset buttons
    $$(".asana-preset-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const key = btn.dataset.preset;
        if (presets[key]) {
          populateForm(presets[key]);
          $$(".asana-preset-btn").forEach((b) => b.classList.remove("border-indigo-600", "ring-2", "ring-indigo-300"));
          btn.classList.add("border-indigo-600", "ring-2", "ring-indigo-300");
          await submitAsanaTicket();
        }
      });
    });

    on("#btn-asana-reset", "click", () => {
      populateForm(presets.visual_qa_clip);
      toast("Form reset to Phase 1B Visual QA benchmark.");
    });

    // Form submit
    const form = $("#asana-ingest-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        await submitAsanaTicket();
      });
    }

    async function submitAsanaTicket() {
      const submitBtn = $("#btn-asana-submit");
      if (submitBtn) submitBtn.disabled = true;

      const payload = {
        task_id: $("#asana-task-id")?.value || "ASN-10924-QA",
        title: $("#asana-title")?.value || "Untitled Asana Task",
        description: $("#asana-description")?.value || "No description provided.",
        author: $("#asana-author")?.value || "Operations Lead",
        workflow_type: $("#asana-workflow")?.value || "VISUAL_QA",
        viewport_spec: $("#asana-viewport")?.value || "375px Mobile",
        figma_spec_url: $("#asana-figma")?.value || null,
        has_marked_scope: Boolean($("#asana-has-scope")?.checked),
        has_device_matrix: Boolean($("#asana-has-matrix")?.checked),
        autonomy_mode: $("#asana-autonomy")?.value || "STAGED_APPROVAL",
      };

      try {
        const res = await api("/asana/ingest", payload);
        renderDecisionConsole(res);
        toast(`Task ${res.packet.queue_items[0]?.source_id || payload.task_id} evaluated with Gemini Decision Engine.`);
        loadLLMUsageLogs();
      } catch (err) {
        toast(`Asana ingestion error: ${err.message}`, true);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    }

    function renderDecisionConsole(res) {
      state.activeAsanaResult = res;

      // Badges
      if ($("#asana-console-val-badge")) {
        $("#asana-console-val-badge").textContent = res.packet.validation_id;
        $("#asana-console-val-badge").onclick = () => openReceipt(res.packet);
      }

      const isStep0Passed = res.packet.step_0_scope_status === "PASSED";
      const step0El = $("#asana-console-step0");
      if (step0El) {
        step0El.textContent = isStep0Passed ? "PASSED ✓" : "BLOCKED ⛔";
        step0El.className = isStep0Passed ? "text-xs font-bold text-emerald-400 mt-0.5" : "text-xs font-bold text-rose-400 mt-0.5";
      }

      if ($("#asana-console-latency")) $("#asana-console-latency").textContent = `${res.llm_log.latency_ms} ms`;
      if ($("#asana-console-tokens")) $("#asana-console-tokens").textContent = `${res.llm_log.total_tokens} tok`;

      const firstItem = res.packet.queue_items && res.packet.queue_items[0];
      if ($("#asana-console-role")) $("#asana-console-role").textContent = firstItem?.accountable_role || "Product Owner";
      if ($("#asana-console-finding-title")) $("#asana-console-finding-title").textContent = firstItem?.observation_text || $("#asana-title")?.value;
      if ($("#asana-console-next-action")) $("#asana-console-next-action").textContent = firstItem?.next_action || (isStep0Passed ? "Action required by functional lead." : "Task blocked at Step 0. Scope must be defined before AI token spend.");

      // Guardrail
      const guardrailEl = $("#asana-console-guardrail");
      if (guardrailEl) {
        if (!isStep0Passed) {
          guardrailEl.textContent = "DO NOT log engineering defects or spend review tokens until changed sections and device matrix are attached in Asana.";
        } else if (res.event?.staged_actions && res.event.staged_actions[0]) {
          guardrailEl.textContent = `DO NOT merge findings without side-by-side 375px mobile crop; enforce 4h GST -> PST SLA handoff.`;
        } else {
          guardrailEl.textContent = "Maintain strict change controls and do not authorize write-backs without owner validation.";
        }
      }

      // Staged write
      const stagedAction = res.event?.staged_actions && res.event.staged_actions[0];
      if ($("#asana-console-autonomy")) $("#asana-console-autonomy").textContent = res.event?.autonomy_mode || "STAGED_APPROVAL";
      if ($("#asana-console-staged-desc")) {
        $("#asana-console-staged-desc").textContent = stagedAction
          ? `${stagedAction.target_system}: ${stagedAction.description}`
          : (isStep0Passed ? "Stage writeback prepared for Asana." : "Writeback blocked at Step 0: Task returned to Product Owner.");
      }

      const execBtn = $("#btn-asana-execute-write");
      const execStatus = $("#asana-console-exec-status");
      if (execBtn) {
        execBtn.disabled = !isStep0Passed || !stagedAction;
        execBtn.innerHTML = `<svg class="w-3.5 h-3.5"><use href="#i-check" /></svg><span>Approve & Execute Staged Write</span>`;
        execBtn.className = "px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 shadow-sm";
      }
      if (execStatus) {
        execStatus.textContent = isStep0Passed && stagedAction ? "Ready for human authorization" : "Blocked by governance rule";
      }

      if ($("#asana-console-sha")) $("#asana-console-sha").textContent = `SHA-256: ${(res.llm_log.sha256 || "").slice(0, 16)}...`;
      if ($("#asana-console-audit-link")) {
        $("#asana-console-audit-link").onclick = (e) => {
          e.preventDefault();
          switchView("audit");
        };
      }
    }

    // Execute staged write
    on("#btn-asana-execute-write", "click", async () => {
      const active = state.activeAsanaResult;
      if (!active || !active.event || !active.event.staged_actions || !active.event.staged_actions[0]) {
        toast("No active staged write action available.", true);
        return;
      }
      const action = active.event.staged_actions[0];
      const execBtn = $("#btn-asana-execute-write");
      const execStatus = $("#asana-console-exec-status");
      if (execBtn) execBtn.disabled = true;

      try {
        const res = await api("/copilot/staged-write/execute", {
          event_id: active.event.event_id,
          action_id: action.action_id,
          actor: "CEO Cockpit",
          role: "CEO",
          rationale: "Approved staged execution directly from Asana Decision Studio.",
        });

        if (execBtn) {
          execBtn.innerHTML = `<svg class="w-3.5 h-3.5"><use href="#i-check" /></svg><span>EXECUTED ✓</span>`;
          execBtn.className = "px-3.5 py-1.5 bg-slate-700 text-emerald-400 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5";
        }
        if (execStatus) {
          execStatus.innerHTML = `<span class="text-emerald-400 font-semibold font-mono">Dispatched · Receipt: ${(res.event?.staged_actions?.[0]?.execution_receipt || "").slice(0, 24)}</span>`;
        }
        toast(`Staged action executed! Logged to Decision Memory.`);
      } catch (err) {
        toast(`Execution failed: ${err.message}`, true);
        if (execBtn) execBtn.disabled = false;
      }
    });

    // Inbound webhook simulation button
    on("#btn-asana-webhook-sim", "click", async () => {
      const randId = Math.floor(Math.random() * 90000 + 10000);
      const webhookPayload = {
        source: "asana",
        workflow_type: $("#asana-workflow")?.value || "VISUAL_QA",
        task_gid: `ASN-WH-${randId}`,
        data: {
          gid: `ASN-WH-${randId}`,
          name: $("#asana-title")?.value || "Inbound Asana Webhook Trigger",
          notes: $("#asana-description")?.value || "Dispatched via Asana REST Webhook Listener.",
          author: $("#asana-author")?.value || "Asana Webhook Relay",
        },
      };

      try {
        const res = await api("/webhooks/inbound", webhookPayload);
        toast(`n8n/Asana Webhook Ingested! Validation Receipt: ${res.validation_id}`);
        switchView("preflight");
      } catch (err) {
        toast(`Webhook push failed: ${err.message}`, true);
      }
    });
  }


  // Altiaris Context-Aware AI Copilot Side Drawer
  function initCopilotDrawer() {
    const drawer = $("#copilot-drawer");
    const triggerBtn = $("#copilot-trigger-btn");
    const closeBtn = $("#copilot-close-btn");
    const form = $("#copilot-form");
    const input = $("#copilot-input");
    const messages = $("#copilot-messages");

    if (!drawer) return;

    function openCopilot() {
      drawer.hidden = false;
      drawer.classList.add("open");
      input?.focus();
    }

    function closeCopilot() {
      drawer.classList.remove("open");
      setTimeout(() => {
        drawer.hidden = true;
      }, 280);
    }

    triggerBtn?.addEventListener("click", openCopilot);
    closeBtn?.addEventListener("click", closeCopilot);

    function appendMsg(role, text) {
      const msgDiv = document.createElement("div");
      msgDiv.className = `copilot-msg ${role}`;
      const timeStr = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "numeric" }).format(new Date());
      msgDiv.innerHTML = `<div class="msg-bubble">${text}</div><span class="msg-time">${timeStr} · ${role === "bot" ? "OpsGate Decision Engine" : "Executive"}</span>`;
      messages.appendChild(msgDiv);
      messages.scrollTop = messages.scrollHeight;
    }

    function answerQuestion(q) {
      const query = q.toLowerCase();
      if (query.includes("downtime") || query.includes("18h")) {
        return `<strong>Downtime Exposure Analysis:</strong><br>
Current downtime across active packaging lines is <strong>18 hours</strong> cumulative this month. Root cause is attributed to line 3 sensor calibration drift (+4.2mm seal offset) and unverified upstream spec handoffs between Dubai QA and LA production. Pre-flight Gate enforcement is projected to cut unverified handoff downtime by <strong>62%</strong>.`;
      }
      if (query.includes("ebitda") || query.includes("408") || query.includes("risk")) {
        return `<strong>EBITDA & Financial Exposure at Risk:</strong><br>
Production Value at Risk is calculated at <strong>$420,000</strong> across batch #408 and 2 adjacent product lines. Primary driver: 8 unverified visual findings and dimension discrepancies. Catching these at Layer 1 (Pre-flight Gate) avoids $38,500 in scrap and 14 hours of line stoppage.`;
      }
      if (query.includes("override") || query.includes("human")) {
        return `<strong>Human-in-the-Loop Audit:</strong><br>
Today, <strong>100%</strong> of critical staged writes underwent human confirmation. 3 high-impact routing actions were staged: 2 approved without modification, 1 overridden by Product Owner (PO) to extend review buffer. All decisions are immutably signed in Layer 5 Decision Memory.`;
      }
      if (query.includes("stall") || query.includes("dubai") || query.includes("handoff") || query.includes("la")) {
        return `<strong>Dubai ↔ LA Handoff Recommendations:</strong><br>
1. <strong>Execute Staged Asana Sync:</strong> Assign urgent verification tasks to QLQA Lead with 4h SLA.<br>
2. <strong>Enforce Step 0 Gate:</strong> Block unscoped tickets from entering LA work queue without screenshot evidence.<br>
3. <strong>Staged 1-Click Shopify Sync:</strong> Hold batch publication until mobile 390px viewport crop is signed off.`;
      }
      return `<strong>Operations Intelligence Synthesis:</strong><br>
Based on current telemetry across Puffy & RGG Capital workflows, throughput is pacing at <strong>96.8%</strong> vs plan with <strong>97.2%</strong> OEE spec adherence. To optimize further, review the 4 active signals under <em>Defend</em> and clear the 3 pending management approvals under <em>Decide</em>.`;
    }

    form?.addEventListener("submit", (e) => {
      e.preventDefault();
      const val = input.value.trim();
      if (!val) return;
      appendMsg("user", escapeHTML(val));
      input.value = "";
      setTimeout(() => {
        const reply = answerQuestion(val);
        appendMsg("bot", reply);
      }, 400);
    });

    $$(".copilot-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const prompt = chip.dataset.prompt;
        input.value = prompt;
        form.dispatchEvent(new Event("submit"));
      });
    });
  }

  initCopilotDrawer();
  initAsanaInboundView();
  loadLLMUsageLogs();

  // If initial hash exists, switch view accordingly
  if (location.hash) {
    const hashView = location.hash.replace("#", "").replace("view-", "");
    if (["overview", "preflight", "copilot", "asana", "economics", "audit", "memory"].includes(hashView)) {
      switchView(hashView);
    }
  }

  // Decision memory modal button
  on("#memory-button", "click", async () => {
    try {
      const entries = await api("/decision-memory");
      $("#memory-content").innerHTML = entries.length
        ? entries
          .map(
            (e) => `<div class="decision-memory-row">
                <div class="decision-memory-header">
                  <code>${escapeHTML(e.entry_id)}</code>
                  <span class="status-chip pass">${escapeHTML(e.human_action)}</span>
                  <small class="muted">${new Date(e.timestamp_utc).toLocaleString()}</small>
                </div>
                <p><strong>Actor:</strong> ${escapeHTML(e.actor)} (${escapeHTML(e.role)}) · <em>${escapeHTML(e.workflow_type)}</em></p>
                <p><strong>AI Recommendation:</strong> ${escapeHTML(e.ai_recommendation)}</p>
                <p><strong>Governance Rule:</strong> ${escapeHTML(e.governance_rule)}</p>
                <p><strong>Outcome / Receipt:</strong> ${escapeHTML(e.predicted_vs_verified_impact)}</p>
              </div>`,
          )
          .join("")
        : '<p class="muted">No decision memory records logged yet. Staged writes and confirmations will appear here.</p>';
      showDialog("memory-dialog");
    } catch (err) {
      toast(`Could not load decision memory: ${err.message}`, true);
    }
  });

  $$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      $$(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.filter = tab.dataset.filter;
      renderQueue();
    }),
  );
  $$(".close-dialog").forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
  $$("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        dialog.close();
    }),
  );
  on("#edit-source", "click", () => {
    $("#raw-source").value = state.packet.raw_input.raw_items
      .map((raw) => `${raw.id} | ${raw.author} | ${raw.comment_text}`)
      .join("\n");
    $("#source-rules").innerHTML = (state.scenarios[
      state.workflow
    ]?.checklist_rules || [])
      .map((rule) => `<li>${escapeHTML(rule)}</li>`)
      .join("");
    showDialog("source-dialog");
  });
  on("#source-form", "submit", async (event) => {
    event.preventDefault();
    const lines = $("#raw-source")
      .value.split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const rawItems = lines.map((line, index) => {
      const parts = line.split("|").map((part) => part.trim());
      if (
        parts.length < 3 ||
        !parts[0] ||
        !parts[1] ||
        !parts.slice(2).join("|")
      )
        throw new Error(`Line ${index + 1}: use ID | Author | Comment.`);
      return {
        id: parts[0],
        author: parts[1],
        comment_text: parts.slice(2).join(" | "),
      };
    });
    const submit = $("#source-form button[type=submit]");
    submit.disabled = true;
    try {
      await runPreflight(rawItems);
      $("#source-dialog").close();
      toast("Pre-flight complete. Validation receipt saved.");
    } finally {
      submit.disabled = false;
    }
  });
  on("#receipt-button", "click", () => openReceipt(state.packet));
  on("#simulate-button", "click", async () => {
    $("#simulate-button").disabled = true;
    $("#simulate-button").textContent = "Generating recovery…";
    try {
      const event = await api("/copilot/recover", {
        validation_id: state.packet.validation_id,
        time_in_current_state_mins: 300,
        incident_key: "cross-hub-demo",
        autonomy_mode: state.autonomy_mode,
      });
      state.events = [event];
      renderRecovery();
      await refreshEconomics();
      toast(
        `Recovery drafted. ${number(event.total_rework_minutes_added)} estimated minutes added to the ledger.`,
      );
    } catch (error) {
      renderRecovery();
      throw error;
    }
  });

  for (const [id, key] of [
    ["prep-slider", "prep_time_mins"],
    ["rework-slider", "rework_mins"],
    ["duplicates-slider", "duplicate_count"],
    ["hourly-rate", "hourly_blended_cost"],
    ["software-cost", "software_cost_per_task"],
    ["maintenance-cost", "maintenance_cost_per_task"],
  ]) {
    on(`#${id}`, id === "hourly-rate" ? "change" : "input", (event) => {
      if (!event.target.validity.valid || event.target.value === "") return;
      state.settings[key] = Number(event.target.value);
      updateSliderLabels();
      clearTimeout(economicsTimer);
      economicsTimer = setTimeout(
        () => refreshEconomics().catch((error) => toast(error.message, true)),
        90,
      );
    });
  }

  on("#export-button", "click", async () => {
    await refreshEconomics();
    downloadJSON(`opsgate-v2-${state.workflow.toLowerCase()}-report.json`, {
      exported_at: new Date().toISOString(),
      scope: "OGI v2.0 Enterprise Decision Intelligence Report",
      persona: state.persona,
      currency: state.settings.currency,
      validation_packet: state.packet,
      recovery_events: state.events,
      economics_assumptions: state.settings,
      trial_evidence_snapshot: state.trialSnapshot,
      economics_report: state.report,
    });
    toast("Executive report exported.");
  });

  on("#history-button", "click", async () => {
    const rows = await api(`/validations?workflow_type=${state.workflow}`);
    $("#history-content").innerHTML = rows.length
      ? rows
        .map(
          (row) =>
            `<div class="history-row"><div><code>${escapeHTML(row.id)}</code><small>${new Date(row.created).toLocaleString()}</small><details><summary>SHA-256 integrity hash</summary><code>${row.sha256}</code></details></div><button class="button secondary small" data-history-id="${escapeHTML(row.id)}">Open ${icon("up")}</button></div>`,
        )
        .join("")
      : '<p class="muted">No receipts saved yet.</p>';
    $$("[data-history-id]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          const packet = await api(`/val/${button.dataset.historyId}`);
          $("#history-dialog").close();
          openReceipt(packet);
        } catch (error) {
          toast(error.message, true);
        }
      }),
    );
    showDialog("history-dialog");
  });

  on("#trial-button", "click", openTrial);
  on("#add-trial", "click", () => {
    const rows = $$("[data-task-row]");
    if (rows.length >= 10) return;
    $("#trial-rows").insertAdjacentHTML("beforeend", taskRow({}, rows.length));
    attachTaskRemove();
  });

  on("#trial-form", "submit", async (event) => {
    event.preventDefault();
    const tasks = $$("[data-task-row]").map((row) =>
      Object.fromEntries(
        $$("input", row).map((input) => [
          input.name,
          input.type === "checkbox"
            ? input.checked
            : input.name === "task_id"
              ? input.value.trim()
              : Number(input.value),
        ]),
      ),
    );
    const cycles = $$(".release-card")
      .filter((card) => $(".cycle-observed", card).checked)
      .map((card) => ({
        cycle_id: card.dataset.release,
        baseline_escaped_defects: Number($(".cycle-before", card).value),
        assisted_escaped_defects: Number($(".cycle-after", card).value),
      }));
    const submit = event.target.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      state.trialSnapshot = await api("/trials", {
        workflow_type: state.workflow,
        trial_tasks: tasks,
        release_cycles: cycles,
      });
      state.settings.trial_tasks = state.trialSnapshot.evidence.trial_tasks;
      state.settings.release_cycles =
        state.trialSnapshot.evidence.release_cycles;
      $("#trial-dialog").close();
      await refreshEconomics();
      toast("Trial evidence saved to the ledger and expansion gate evaluated.");
    } finally {
      submit.disabled = false;
    }
  });
}

async function init() {
  bindEvents();
  setBusy(true);
  try {
    state.scenarios = await api("/scenarios");
    const directId = location.pathname.startsWith("/val/")
      ? location.pathname.split("/")[2]
      : null;
    let workflow = "VISUAL_QA";
    if (directId)
      workflow = (await api(`/val/${encodeURIComponent(directId)}`))
        .workflow_type;
    await loadWorkflow(workflow, directId);
    for (const [id, zone] of [
      ["dubai-clock", "Asia/Dubai"],
      ["la-clock", "America/Los_Angeles"],
    ]) {
      $(`#${id}`).textContent = new Intl.DateTimeFormat("en-US", {
        timeZone: zone,
        hour: "2-digit",
        minute: "2-digit",
        timeZoneName: "short",
      }).format(new Date());
    }
    updatePersona("CEO");
  } catch (error) {
    if ($("#global-error")) {
      $("#global-error").hidden = false;
      $("#global-error").textContent =
        `Could not connect to OGI: ${error.message}. Check the server and reload.`;
    }
    toast(error.message, true);
  }
}

init();
