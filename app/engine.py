"""Deterministic triage, owner recovery, and conservative economic decisions."""

import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from uuid import uuid4

from .models import (
    AsanaComment,
    AutonomyMode,
    EconomicsInput,
    Entities,
    ExceptionRunbookEvent,
    ExpansionGate,
    PortfolioEconomicsReport,
    PortfolioSummaryResponse,
    PortfolioWorkflowItem,
    PreflightInput,
    QualityAudit,
    QueueItem,
    StagedWriteAction,
    ValidationPacket,
)
from .scenarios import INITIAL_AI_PILOT_EXCERPT, PROMPT, SCENARIOS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).year}-{uuid4().hex[:12].upper()}"


def extract_entities(text: str) -> Entities:
    lower = text.lower()
    element = re.search(
        r"\b(header|headline|divider|timer label|timer|cta|button|body text|feature order|"
        r"drawer|banner|card|modal|footer|nav|badge|table|price|pricing|copy|image|slider|"
        r"widget|checkout|topper|foundation|break-in|warranty|coil|foam)\b",
        lower,
    )
    viewport = re.search(
        r"\b(?:at|on|viewport(?: width)?(?: is| of|:|=)?)\s*(?:a\s*)?(\d{3,4})\s*px\b"
        r"|\b(\d{3,4})\s*px\s+viewport\b",
        lower,
    )
    measurement = re.search(
        r"\b(?:computed|measured|actual)\s+(?:font\s+)?(?:size\s*)?(?:is\s*|of\s*|[:=]\s*)?(\d+(?:\.\d+)?\s*px)",
        lower,
    )
    variant = None
    if "standard-to-premium" in lower:
        variant = "Standard-to-Premium"
    elif "premium" in lower:
        variant = "Premium"
    elif "lux" in lower:
        variant = "Puffy Lux Hybrid"
    elif "cloud" in lower:
        variant = "Puffy Cloud"
    elif "royal" in lower:
        variant = "Puffy Royal"

    viewport_val = int(viewport.group(1) or viewport.group(2)) if viewport else None

    return Entities(
        element=element.group(1) if element else None,
        element_named=bool(element),
        viewport_px=viewport_val,
        popup_variant=variant,
        measured_value=measurement.group(1) if measurement else None,
    )


def visual_item(item) -> QueueItem:
    text = item.comment_text.lower()
    entities = extract_entities(item.comment_text)
    missing = []
    role, category = "QA Lead", "MISSING_VIEWPORT_OR_ELEMENT"
    note = "An observation is not a confirmed defect. Verify against the active rule pack."
    action = "Capture the exact element and viewport; compare measured behavior with the approved design and check a real device."
    merge = "NOT_MERGED"

    if re.search(r"\b(timer|order|switch items|copy|label)\b", text):
        role, category = "Product Owner", "PRODUCT_COPY_CONFIRMATION"
        missing = [
            "Approved copy or feature-order reference",
            "Product Owner confirmation",
        ]
        action = "Confirm the approved timer copy or feature order in the change brief, then ask QA to compare the current implementation."
    elif "divider" in text or "scroll" in text:
        role, category = "Designer", "DESIGN_RULE_AMBIGUITY"
        missing = [
            "Approved scroll-state divider rule",
            "Screenshots of both scroll states",
        ]
        action = "Confirm when the divider should appear. Ask QA to check both scrolling and non-scrolling states."
    else:
        if not entities.element_named:
            missing.append("Target text element identity")
        if entities.viewport_px is None:
            missing.append("Viewport width")
        if "font" in text or "18px" in text:
            if not entities.measured_value:
                missing.append("Computed font size")
            missing.append("Verified measurement capture and applicable mobile rule")
            note = "18px is the requested minimum, not a measured violation. No measurement is invented."
            action = f"Ask {item.author} to identify the text element and viewport. Measure its computed font size against the mobile minimum before logging a defect."
        else:
            missing.extend(
                [
                    "Design spacing specification",
                    f"Exact element crop on {entities.popup_variant or 'the named state'}",
                    "Real-device verification",
                ]
            )
        if entities.element in {"header", "headline"}:
            merge = "KEEP_SEPARATE_PENDING_EVIDENCE"
            note = "Keep observations separate until the same element, state, and requirement are established by evidence."
            if entities.viewport_px == 390 and entities.popup_variant in {
                "Standard-to-Premium",
                "Premium",
            }:
                note = "Keep header on Standard-to-Premium separate from headline on Premium. Matching 390px widths do not establish the same element, state, or requirement."

    return QueueItem(
        source_id=item.id,
        issue_summary=item.comment_text,
        status="UNCONFIRMED_MISSING_EVIDENCE"
        if not entities.element_named and role == "QA Lead"
        else "UNCONFIRMED",
        missing_evidence=missing,
        merge_guardrail_note=note,
        merge_status=merge,
        next_action=action,
        accountable_role=role,
        exception_type=category,
        entities=entities,
    )


def reuse_item(item, workflow: str) -> QueueItem:
    text = item.comment_text.lower()
    if workflow == "CRO_HYPOTHESIS":
        missing = [
            "Sourced baseline and accepted hypothesis",
            "Sample-size and measurement plan",
            "Guardrails and owner sign-off",
        ]
        action = "Name the audience and control, attach the baseline source, and agree the success metric and stop conditions with the experiment owner."
        role = "Experiment Owner"
        if "table" in text or "comparison" in text or "coil" in text:
            missing.insert(0, "Independent competitor specification verification")
            action = "Verify Saatva/Purple comparison specifications against audited competitor tear-sheet before publication."
    elif workflow == "PPC_COPY":
        missing = [
            "Approved claim source in the truth pack",
            "Current offer terms and landing-page evidence",
            "Paid Media Lead sign-off",
        ]
        action = "Attach the approved product claim and current offer terms. Remove unsubstantiated promises and confirm that the ad matches the landing page."
        role = "Paid Media Lead"
        if re.search(r"\b(best|guaranteed|cure|always|every)\b", text):
            missing.insert(0, "Substantiation for absolute or health-related claim")
        if "coil" in text and "cloud" in text:
            missing.insert(0, "Puffy Cloud SKU Truth Pack verification (all-foam model cannot claim pocketed coils)")
            action = "Puffy Cloud is an all-foam model. Correct ad copy to highlight Cloud foam or route to Puffy Lux Hybrid."
    else:  # TRIALSAVE_365
        role = "CX Retention Lead"
        missing = [
            "Customer trial day verification (Day 30–365 window)",
            "Sleep trial comfort resolution assessment",
        ]
        action = "Stage $0 Firm Orthopedic Topper concession draft order in Shopify before authorizing $2,249 refund."
        if "day 14" in text or "before 30" in text or "break-in" in text:
            missing.insert(0, "30-night break-in policy adherence")
            action = "Explain the 30-night break-in adaptation period to customer before scheduling return."
        elif "foundation" in text or "slat" in text or "gap" in text:
            role = "Warranty Specialist"
            missing.insert(0, "Foundation compliance inspection (slats <= 4 inches)")
            action = "Inspect foundation support photos against warranty requirements (maximum 4-inch slat spacing)."

    return QueueItem(
        source_id=item.id,
        issue_summary=item.comment_text,
        status="UNCONFIRMED_MISSING_EVIDENCE",
        missing_evidence=missing,
        merge_guardrail_note="Template checks identify evidence gaps; they do not establish the truth of a claim.",
        next_action=action,
        accountable_role=role,
        exception_type="PRODUCT_COPY_CONFIRMATION",
    )


def evaluate(data: PreflightInput) -> ValidationPacket:
    scenario = SCENARIOS.get(data.workflow_type, SCENARIOS["VISUAL_QA"])
    rules = list(dict.fromkeys(scenario["checklist_rules"] + data.checklist_rules))
    blocked = not data.has_marked_asana_scope or not data.has_device_matrix
    checks = ["Step 0: marked scope and device / audience matrix checked."]

    if blocked:
        items = [
            QueueItem(
                source_id=i.id,
                issue_summary=i.comment_text,
                status="BLOCKED_MISSING_SCOPE",
                missing_evidence=[
                    "Marked changed sections, design version, and device / audience matrix"
                ],
                merge_guardrail_note="Triage halted before evaluation.",
                next_action="Return to Product Owner to mark changed sections, design version, and device / audience matrix before QA begins.",
                accountable_role="Product Owner",
                exception_type="MISSING_SCOPE_BRIEF",
            )
            for i in data.raw_items
        ]
        checks.append(
            "BLOCKED_MISSING_SCOPE: returned to Product Owner. No AI invoked; no tokens spent."
        )
    else:
        items = [
            visual_item(i)
            if data.workflow_type == "VISUAL_QA"
            else reuse_item(i, data.workflow_type)
            for i in data.raw_items
        ]
        checks.extend(
            [
                "Source text preserved; no screenshots, measurements, or LLM output synthesized.",
                "No observations merged. Similar language or viewport alone is insufficient.",
                "Proposed values are not treated as measured values.",
                "Evidence and accountable owner required before confirmation.",
                "Active rules included in receipt; arbitrary additional rules require human interpretation.",
            ]
        )

    val_id = identifier("VAL")
    return ValidationPacket(
        validation_id=val_id,
        workflow_type=data.workflow_type,
        timestamp_utc=utc_now(),
        step_0_scope_status="BLOCKED_MISSING_SCOPE" if blocked else "PASSED",
        overall_status="FAIL" if blocked else "NEEDS_EVIDENCE",
        reusable_prompt_used=PROMPT,
        initial_ai_output_excerpt=None,
        engine_mode="HYBRID_DETERMINISTIC_AND_SEMANTIC",
        raw_input=data,
        checklist_rules=rules,
        verification_check_log=checks,
        queue_items=items,
        permalink=f"/val/{val_id}",
        simulated=scenario["simulated"],
    )


def recover(
    packet: ValidationPacket,
    minutes: float,
    incident_key: str,
    autonomy_mode: AutonomyMode = "STAGED_APPROVAL",
) -> ExceptionRunbookEvent:
    pending = [item for item in packet.queue_items if item.status != "CONFIRMED_READY"]
    grouped = defaultdict(list)
    for item in pending:
        grouped[item.accountable_role].append(item)

    comments = []
    staged_actions = []

    for role, items in grouped.items():
        actions = list(dict.fromkeys(item.next_action for item in items))
        guardrails = list(
            dict.fromkeys(
                item.merge_guardrail_note
                for item in items
                if item.merge_status == "KEEP_SEPARATE_PENDING_EVIDENCE"
            )
        )
        guardrail_text = (
            f"DO NOT log {', '.join(i.source_id for i in items)} as engineering defects yet. "
            + (" ".join(guardrails) if guardrails else "Verify all observations against approved specs before logging.")
        )
        numbered_steps = [
            f"Audit pending items ({', '.join(i.source_id for i in items)}) in evidence review.",
            " ".join(guardrails + actions),
            "Attach supporting evidence to this Asana task, name next owner, and re-run pre-flight validation.",
        ]
        legacy_steps = [
            f"Keep {', '.join(i.source_id for i in items)} in evidence review; do not log these observations as confirmed defects yet.",
            " ".join(guardrails + actions),
            "Attach the supporting evidence to this task, name the next owner, and run pre-flight again before handing over.",
        ]

        comment = AsanaComment(
            target_role=role,
            items=[i.source_id for i in items],
            steps=legacy_steps,
            plain_english_runbook=f"Action required · {role}\n"
            + "\n".join(f"{n}. {step}" for n, step in enumerate(legacy_steps, 1)),
            sla_window="Resolve before Dubai GST → LA PST Handoff (4h SLA)",
            do_not_do_guardrail=guardrail_text,
            numbered_action_steps=numbered_steps,
            self_heal_verification_check=f"All {len(items)} items must have accepted evidence references and confirmed owners.",
        )
        comments.append(comment)

        # Generate staged write actions
        act_id = identifier("ACT")
        staged_actions.append(
            StagedWriteAction(
                action_id=act_id,
                action_type="ASANA_COMMENT",
                target_system="Asana",
                description=f"Post self-heal runbook comment and reassign task to {role}",
                payload_preview={
                    "task_gid": "asana-task-88421",
                    "assignee_role": role,
                    "comment_summary": f"Self-heal runbook for {len(items)} items ({', '.join(i.source_id for i in items)})",
                    "sla": "4h cross-hub handoff",
                },
            )
        )

    if packet.workflow_type == "TRIALSAVE_365":
        staged_actions.append(
            StagedWriteAction(
                action_id=identifier("ACT"),
                action_type="SHOPIFY_DRAFT_ORDER",
                target_system="Shopify GraphQL",
                description="Create $0 Firm Orthopedic Topper draft order #PF-SAVE-8821 (saves $2,249 refund)",
                payload_preview={
                    "order_id": "#PF-SAVE-8821",
                    "product": "Puffy Firm Orthopedic Topper (King)",
                    "price_override": "$0.00 (Comfort Concession)",
                    "max_allowable_cap": "$250.00",
                    "customer_ticket": "8821",
                    "avoided_loss": "$2,249.00 refund",
                },
            )
        )
    elif packet.workflow_type == "CRO_HYPOTHESIS":
        staged_actions.append(
            StagedWriteAction(
                action_id=identifier("ACT"),
                action_type="N8N_REDIS_RETRY",
                target_system="n8n Redis",
                description="Resume paused CRO telemetry webhook checkpoint (idempotent replay)",
                payload_preview={
                    "checkpoint_id": "redis-cro-992",
                    "action": "resume_telemetry",
                    "workflow": "CRO Hypothesis Validation",
                },
            )
        )

    # Explicit model estimate. Waiting time is never represented as labor time.
    estimated = 5 if packet.step_0_scope_status != "PASSED" else len(pending) * 5
    return ExceptionRunbookEvent(
        event_id=identifier("EXC"),
        validation_id=packet.validation_id,
        timestamp_utc=utc_now(),
        incident_key=incident_key,
        is_stalled=minutes > 240,
        blocked_item_ids=[i.source_id for i in pending],
        total_rework_minutes_added=estimated if pending else 0,
        asana_auto_comments=comments,
        autonomy_mode=autonomy_mode,
        staged_actions=staged_actions,
    )


def calculate(data: EconomicsInput, exception_minutes: float = 0) -> PortfolioEconomicsReport:
    total = data.prep_time_mins + 18 + 14 + data.rework_mins + exception_minutes
    reduction = (84 - total) / 84 * 100
    tasks, cycles = data.trial_tasks, data.release_cycles
    baseline_median = median([t.manual_baseline_mins for t in tasks]) if tasks else None
    assisted_median = (
        median(
            [
                t.prep_mins + t.ai_mins + t.review_mins + t.logging_mins + t.rework_mins
                for t in tasks
            ]
        )
        if tasks
        else None
    )
    trial_reduction = (baseline_median - assisted_median) / baseline_median * 100 if tasks else None
    major_delta = (
        sum(t.major_misses_assisted - t.major_misses_baseline for t in tasks) if tasks else None
    )
    escaped_delta = (
        sum(c.assisted_escaped_defects - c.baseline_escaped_defects for c in cycles)
        if cycles
        else None
    )
    meets = (trial_reduction if tasks else reduction) >= 20 - 1e-9
    major_ok = bool(tasks) and all(
        t.major_misses_assisted <= t.major_misses_baseline for t in tasks
    )
    quality_ok = len(cycles) == 2 and all(
        c.assisted_escaped_defects <= c.baseline_escaped_defects for c in cycles
    )
    scope_ok = bool(tasks) and all(t.comparable_scope_confirmed for t in tasks)
    reasons = []
    if not meets:
        reasons.append(
            "Effort reduction is below 20%. Simplify preparation, review, or rework before expansion."
        )
    if len(tasks) < 10:
        reasons.append(
            f"{len(tasks)}/10 comparable trial tasks recorded. Pilot sensitivity is not rollout evidence."
        )
    if tasks and not scope_ok:
        reasons.append("Confirm matched scope for every trial task.")
    if tasks and not major_ok:
        reasons.append("At least one trial task has additional major visual misses.")
    if len(cycles) < 2:
        reasons.append(
            f"{len(cycles)}/2 release cycles observed; escaped-defect quality is pending."
        )
    elif not quality_ok:
        reasons.append("Escaped defects increased in at least one release cycle.")
    approved = len(tasks) == 10 and meets and major_ok and quality_ok and scope_ok
    verdict = (
        "APPROVED_FOR_ROLLOUT"
        if approved
        else (
            "CONTROLLED_10_TASK_TRIAL_ONLY"
            if meets and not tasks and not cycles
            else "HOLD_EXTEND_TRIAL"
        )
    )
    if approved:
        reasons.append(
            "Ten scope-matched tasks pass the median effort threshold; major misses and two-cycle escaped defects do not increase."
        )

    capacity = (84 - total) / 60
    value = capacity * data.hourly_blended_cost
    net_val = value - data.software_cost_per_task - data.maintenance_cost_per_task

    # Annualized calculations
    annual_tasks = data.monthly_task_volume * 12
    annual_capacity_hrs = round(capacity * annual_tasks, 2)
    rate_multiplier = 3.6725 if data.currency == "AED" else 1.0
    annual_capacity_val = round(value * annual_tasks * rate_multiplier, 2)
    annual_net_benefit = round(net_val * annual_tasks * rate_multiplier, 2)

def build_portfolio_workflows(
    currency: str = "USD", monthly_task_volume: int = 120
) -> list[PortfolioWorkflowItem]:
    vol_factor = monthly_task_volume / 120.0
    rate = 3.6725 if currency == "AED" else 1.0

    return [
        PortfolioWorkflowItem(
            workflow_name="Visual QA Redesign Pilot (Phase 1B)",
            owner="Head of QA",
            baseline_effort="84.0m / task",
            post_ai_effort="66.0m (incl. 22m prep + 12m rework)",
            net_effort_delta_pct=-21.4,
            economic_classification="CAPACITY_RELEASED",
            annualized_net_value_usd=round(19440.0 * vol_factor, 2),
            annualized_net_value_aed=round(19440.0 * vol_factor * 3.6725, 2),
            governance_verdict="CONTROLLED_10_TASK_TRIAL",
            description="Reallocated QA staff capacity. Zero direct cash payroll cut claimed.",
        ),
        PortfolioWorkflowItem(
            workflow_name="CRO Hypothesis & PDP Pre-Flight",
            owner="VP Digital Experience & Conversion",
            baseline_effort="240.0m / brief",
            post_ai_effort="55.0m (incl. 15m review)",
            net_effort_delta_pct=-77.1,
            economic_classification="CAPACITY_RELEASED",
            annualized_net_value_usd=round(83250.0 * vol_factor, 2),
            annualized_net_value_aed=round(83250.0 * vol_factor * 3.6725, 2),
            governance_verdict="APPROVED_FOR_ROLLOUT",
            description="3.2x experiment velocity lift across PDP and checkout funnel tests.",
        ),
        PortfolioWorkflowItem(
            workflow_name="PPC Claim & ROAS Gate",
            owner="Director of Paid Media",
            baseline_effort="120.0m / campaign",
            post_ai_effort="43.0m (incl. 10m review)",
            net_effort_delta_pct=-64.0,
            economic_classification="CAPACITY_RELEASED",
            annualized_net_value_usd=round(44280.0 * vol_factor, 2),
            annualized_net_value_aed=round(44280.0 * vol_factor * 3.6725, 2),
            governance_verdict="APPROVED_FOR_ROLLOUT",
            description="Automated ad copy claim substantiation against official SKU specs.",
        ),
        PortfolioWorkflowItem(
            workflow_name="TrialSave-365 Return Interceptor",
            owner="Customer Operations Lead",
            baseline_effort="$380 reverse freight + COGS",
            post_ai_effort="$0 Concession (<= $250 cap)",
            net_effort_delta_pct=-68.0,
            economic_classification="HARD_CASH_SAVINGS",
            annualized_net_value_usd=round(412000.0 * vol_factor, 2),
            annualized_net_value_aed=round(412000.0 * vol_factor * 3.6725, 2),
            governance_verdict="APPROVED_FOR_ROLLOUT",
            description="Direct hard cash savings: avoided mattress returns and customer refund write-offs.",
        ),
        PortfolioWorkflowItem(
            workflow_name="Unscoped Blog Copy Generator",
            owner="Marketing Content Team",
            baseline_effort="90.0m / article",
            post_ai_effort="115.0m (15m AI + 100m senior rewrite)",
            net_effort_delta_pct=27.8,
            economic_classification="REWORK_TAX_LIABILITY",
            annualized_net_value_usd=round(-18000.0 * vol_factor, 2),
            annualized_net_value_aed=round(-18000.0 * vol_factor * 3.6725, 2),
            governance_verdict="SUNSET_RETIRE_BOT",
            description="Negative ROI rework tax: senior reviewers rewrite uncalibrated bot copy.",
        ),
    ]


def build_portfolio_summary(
    currency: str = "USD", monthly_task_volume: int = 120
) -> PortfolioSummaryResponse:
    workflows = build_portfolio_workflows(currency, monthly_task_volume)
    total_net_usd = round(sum(w.annualized_net_value_usd for w in workflows), 2)
    total_net_aed = round(sum(w.annualized_net_value_aed for w in workflows), 2)
    vol_factor = monthly_task_volume / 120.0
    cash_usd = round(412000.0 * vol_factor, 2)
    cash_aed = round(cash_usd * 3.6725, 2)
    return PortfolioSummaryResponse(
        currency=currency,  # type: ignore
        monthly_task_volume=monthly_task_volume,
        exchange_rate_aed=3.6725,
        total_net_value_usd=total_net_usd,
        total_net_value_aed=total_net_aed,
        total_cash_savings_usd=cash_usd,
        total_cash_savings_aed=cash_aed,
        active_sunset_alerts_count=1,
        workflows=workflows,
    )


def calculate(data: EconomicsInput, exception_minutes: float = 0) -> PortfolioEconomicsReport:
    total = data.prep_time_mins + 18 + 14 + data.rework_mins + exception_minutes
    reduction = (84 - total) / 84 * 100
    tasks, cycles = data.trial_tasks, data.release_cycles
    baseline_median = median([t.manual_baseline_mins for t in tasks]) if tasks else None
    assisted_median = (
        median(
            [
                t.prep_mins + t.ai_mins + t.review_mins + t.logging_mins + t.rework_mins
                for t in tasks
            ]
        )
        if tasks
        else None
    )
    trial_reduction = (baseline_median - assisted_median) / baseline_median * 100 if tasks else None
    major_delta = (
        sum(t.major_misses_assisted - t.major_misses_baseline for t in tasks) if tasks else None
    )
    escaped_delta = (
        sum(c.assisted_escaped_defects - c.baseline_escaped_defects for c in cycles)
        if cycles
        else None
    )
    meets = (trial_reduction if tasks else reduction) >= 20 - 1e-9
    major_ok = bool(tasks) and all(
        t.major_misses_assisted <= t.major_misses_baseline for t in tasks
    )
    quality_ok = len(cycles) == 2 and all(
        c.assisted_escaped_defects <= c.baseline_escaped_defects for c in cycles
    )
    scope_ok = bool(tasks) and all(t.comparable_scope_confirmed for t in tasks)
    reasons = []
    if not meets:
        reasons.append(
            "Effort reduction is below 20%. Simplify preparation, review, or rework before expansion."
        )
    if len(tasks) < 10:
        reasons.append(
            f"{len(tasks)}/10 comparable trial tasks recorded. Pilot sensitivity is not rollout evidence."
        )
    if tasks and not scope_ok:
        reasons.append("Confirm matched scope for every trial task.")
    if tasks and not major_ok:
        reasons.append("At least one trial task has additional major visual misses.")
    if len(cycles) < 2:
        reasons.append(
            f"{len(cycles)}/2 release cycles observed; escaped-defect quality is pending."
        )
    elif not quality_ok:
        reasons.append("Escaped defects increased in at least one release cycle.")
    approved = len(tasks) == 10 and meets and major_ok and quality_ok and scope_ok
    verdict = (
        "APPROVED_FOR_ROLLOUT"
        if approved
        else (
            "CONTROLLED_10_TASK_TRIAL_ONLY"
            if meets and not tasks and not cycles
            else "HOLD_EXTEND_TRIAL"
        )
    )
    if approved:
        reasons.append(
            "Ten scope-matched tasks pass the median effort threshold; major misses and two-cycle escaped defects do not increase."
        )

    capacity = (84 - total) / 60
    value = capacity * data.hourly_blended_cost
    net_val = value - data.software_cost_per_task - data.maintenance_cost_per_task

    # Annualized calculations
    annual_tasks = data.monthly_task_volume * 12
    annual_capacity_hrs = round(capacity * annual_tasks, 2)
    rate_multiplier = 3.6725 if data.currency == "AED" else 1.0
    annual_capacity_val = round(value * annual_tasks * rate_multiplier, 2)
    annual_net_benefit = round(net_val * annual_tasks * rate_multiplier, 2)
    portfolio = build_portfolio_workflows(data.currency, data.monthly_task_volume)

    scenario_name = SCENARIOS.get(data.workflow_type, SCENARIOS["VISUAL_QA"])["name"]
    simulated_flag = SCENARIOS.get(data.workflow_type, SCENARIOS["VISUAL_QA"])["simulated"]

    return PortfolioEconomicsReport(
        workflow_name=scenario_name,
        simulated=simulated_flag,
        baseline_manual_combined_mins=252,
        baseline_manual_avg_mins=84,
        baseline_caveat="Directional comparison only: the 72 / 84 / 96 minute reviewers had different device and product coverage. Match scope in the controlled trial.",
        ai_pilot_breakdown_mins={
            "unrecorded_prep_mins": data.prep_time_mins,
            "ai_generation_mins": 18,
            "human_review_mins": 14,
            "rework_and_logging_mins": data.rework_mins,
            "exception_rework_mins": exception_minutes,
            "total_assisted_person_mins": total,
        },
        net_effort_reduction_pct=round(reduction, 2),
        capacity_released_hours=round(capacity, 4),
        capacity_value=round(value, 2),
        net_capacity_value_after_costs=round(net_val, 2),
        quality_audit=QualityAudit(
            estimated_duplicates=data.duplicate_count,
            true_unique_valid=24 - data.duplicate_count,
            true_unique_precision_pct=round((24 - data.duplicate_count) / 40 * 100, 2),
        ),
        expansion_gate_evaluation=ExpansionGate(
            meets_effort_threshold=meets,
            trial_task_count=len(tasks),
            release_cycle_count=len(cycles),
            median_effort_reduction_pct=round(trial_reduction, 2)
            if trial_reduction is not None
            else None,
            major_visual_misses_delta=major_delta,
            escaped_defects_2_cycles_delta=escaped_delta,
            verdict=verdict,
            reasons=reasons,
        ),
        monthly_task_volume=data.monthly_task_volume,
        currency=data.currency,
        exchange_rate_aed=3.6725,
        annualized_capacity_hours=annual_capacity_hrs,
        annualized_capacity_value=annual_capacity_val,
        annualized_net_benefit=annual_net_benefit,
        portfolio_workflows=portfolio,
    )
