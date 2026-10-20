from copy import deepcopy

import pytest

from app.engine import calculate, evaluate, extract_entities, recover
from app.models import EconomicsInput, PreflightInput
from app.scenarios import SCENARIOS


def pilot(**kwargs):
    return PreflightInput(raw_items=SCENARIOS["VISUAL_QA"]["raw_items"], **kwargs)


def trial_tasks(total=66):
    return [
        {
            "task_id": f"T{i}",
            "manual_baseline_mins": 84,
            "prep_mins": total - 44,
            "ai_mins": 18,
            "review_mins": 14,
            "logging_mins": 2,
            "rework_mins": 10,
            "major_misses_baseline": 0,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        }
        for i in range(10)
    ]


def cycles():
    return [
        {
            "cycle_id": str(i),
            "baseline_escaped_defects": 0,
            "assisted_escaped_defects": 0,
        }
        for i in range(2)
    ]


def test_pilot_entities_routes_and_no_fabricated_evidence():
    packet = evaluate(pilot())
    items = {i.source_id: i for i in packet.queue_items}
    assert packet.overall_status == "NEEDS_EVIDENCE"
    assert packet.ai_tokens_spent == 0
    assert packet.initial_ai_output_excerpt is None
    assert items["F1"].entities.element == "header"
    assert items["F1"].entities.popup_variant == "Standard-to-Premium"
    assert items["F2"].entities.element == "headline"
    assert items["F2"].entities.popup_variant == "Premium"
    assert items["F1"].entities.viewport_px == items["F2"].entities.viewport_px == 390
    assert items["F1"].merge_status == items["F2"].merge_status == "KEEP_SEPARATE_PENDING_EVIDENCE"
    assert items["F4"].status == "UNCONFIRMED_MISSING_EVIDENCE"
    assert items["F4"].entities.element_named is False
    assert items["F4"].entities.viewport_px is None
    assert items["F4"].entities.measured_value is None
    assert {
        "Target text element identity",
        "Viewport width",
        "Computed font size",
    } <= set(items["F4"].missing_evidence)
    assert items["F3"].accountable_role == items["F6"].accountable_role == "Product Owner"
    assert items["F5"].accountable_role == "Designer"


@pytest.mark.parametrize("field", ["has_marked_asana_scope", "has_device_matrix"])
def test_step_zero_preempts_all_triage(field):
    packet = evaluate(pilot(**{field: False}))
    assert packet.step_0_scope_status == "BLOCKED_MISSING_SCOPE"
    assert packet.overall_status == "FAIL"
    assert all(
        i.accountable_role == "Product Owner" and i.status == "BLOCKED_MISSING_SCOPE"
        for i in packet.queue_items
    )
    assert all(i.entities.viewport_px is None for i in packet.queue_items)


def test_engine_uses_content_not_source_ids():
    data = pilot()
    data.raw_items[3].id = "CUSTOM_FOUR"
    result = evaluate(data)
    assert result.queue_items[3].status == "UNCONFIRMED_MISSING_EVIDENCE"
    assert result.queue_items[3].source_id == "CUSTOM_FOUR"


def test_requested_font_size_is_not_measured():
    assert extract_entities("Increase body text to 18px at a 390px viewport").measured_value is None
    assert extract_entities("Body text computed font size: 16px at 390px").measured_value == "16px"


def test_layout_dimensions_do_not_invent_a_viewport():
    assert extract_entities("The header is 390px wide").viewport_px is None
    assert extract_entities("The header has a 390px border").viewport_px is None
    assert extract_entities("Viewport width: 390px").viewport_px == 390


def test_border_does_not_match_product_order_routing():
    data = pilot()
    data.raw_items[0].comment_text = "The header border looks incorrect."
    item = evaluate(data).queue_items[0]
    assert item.accountable_role == "QA Lead"
    assert "Standard-to-Premium" not in item.merge_guardrail_note


def test_recovery_preserves_the_merge_guardrail():
    event = recover(evaluate(pilot()), 300, "guardrail")
    qa = next(comment for comment in event.asana_auto_comments if comment.target_role == "QA Lead")
    assert (
        "Keep header on Standard-to-Premium separate from headline on Premium"
        in qa.plain_english_runbook
    )


def test_exact_grounded_economics():
    result = calculate(EconomicsInput())
    assert result.ai_pilot_breakdown_mins.total_assisted_person_mins == 66
    assert result.net_effort_reduction_pct == 21.43
    assert result.quality_audit.true_unique_precision_pct == 40
    assert result.quality_audit.true_unique_valid == 16
    assert result.quality_audit.recall_status == "UNMEASURABLE_PENDING_MANUAL_ACCEPTANCE"
    assert result.capacity_released_hours == 0.3
    assert result.capacity_value == 13.5
    assert result.cash_savings == 0
    assert result.expansion_gate_evaluation.verdict == "CONTROLLED_10_TASK_TRIAL_ONLY"
    assert result.expansion_gate_evaluation.major_visual_misses_delta is None


@pytest.mark.parametrize(
    "prep,passes",
    [(23, True), (23.2, True), (23.2001, False), (24, False), (30, False)],
)
def test_prep_boundary_without_rounded_approval(prep, passes):
    result = calculate(EconomicsInput(prep_time_mins=prep))
    assert result.expansion_gate_evaluation.meets_effort_threshold is passes


def test_recovery_estimate_flows_into_effort_without_wait_time():
    event = recover(evaluate(pilot()), 300, "incident")
    assert event.is_stalled
    assert len(event.asana_auto_comments) == 3
    assert all(len(c.steps) == 3 for c in event.asana_auto_comments)
    assert event.total_rework_minutes_added == 30
    assert event.asana_delivery_status == "DRAFT_ONLY_NOT_CONNECTED"
    result = calculate(EconomicsInput(), event.total_rework_minutes_added)
    assert result.ai_pilot_breakdown_mins.total_assisted_person_mins == 96
    assert result.net_effort_reduction_pct == -14.29
    assert result.expansion_gate_evaluation.verdict == "HOLD_EXTEND_TRIAL"
    assert result.capacity_value < 0


def test_four_hour_stall_boundary():
    packet = evaluate(pilot())
    assert not recover(packet, 240, "one").is_stalled
    assert recover(packet, 241, "two").is_stalled


def test_costs_reduce_capacity_value_not_cash_savings():
    result = calculate(
        EconomicsInput(
            hourly_blended_cost=75,
            software_cost_per_task=2,
            maintenance_cost_per_task=3,
        )
    )
    assert result.capacity_value == 22.5
    assert result.net_capacity_value_after_costs == 17.5
    assert result.cash_savings == 0


def test_rollout_requires_complete_trial_and_quality():
    assert (
        calculate(
            EconomicsInput(trial_tasks=trial_tasks(), release_cycles=cycles())
        ).expansion_gate_evaluation.verdict
        == "APPROVED_FOR_ROLLOUT"
    )
    for tasks, releases in [
        (trial_tasks()[:9], cycles()),
        (trial_tasks(), cycles()[:1]),
        ([], cycles()),
    ]:
        assert (
            calculate(
                EconomicsInput(trial_tasks=tasks, release_cycles=releases)
            ).expansion_gate_evaluation.verdict
            != "APPROVED_FOR_ROLLOUT"
        )


@pytest.mark.parametrize("mutation", ["major", "escape", "scope", "effort"])
def test_rollout_rejects_each_failure(mutation):
    tasks, releases = trial_tasks(), cycles()
    if mutation == "major":
        tasks[0]["major_misses_assisted"] = 1
    elif mutation == "escape":
        releases[1]["assisted_escaped_defects"] = 1
    elif mutation == "scope":
        tasks[0]["comparable_scope_confirmed"] = False
    else:
        tasks = trial_tasks(75)
    assert (
        calculate(
            EconomicsInput(trial_tasks=tasks, release_cycles=releases)
        ).expansion_gate_evaluation.verdict
        == "HOLD_EXTEND_TRIAL"
    )


def test_quality_regressions_cannot_be_cancelled_by_other_tasks_or_cycles():
    tasks, releases = trial_tasks(), cycles()
    tasks[0]["major_misses_assisted"] = 1
    tasks[1]["major_misses_baseline"] = 1
    releases[0]["assisted_escaped_defects"] = 1
    releases[1]["baseline_escaped_defects"] = 1
    gate = calculate(
        EconomicsInput(trial_tasks=tasks, release_cycles=releases)
    ).expansion_gate_evaluation
    assert gate.major_visual_misses_delta == gate.escaped_defects_2_cycles_delta == 0
    assert gate.verdict == "HOLD_EXTEND_TRIAL"


def test_trial_uses_medians_not_combined_effort_or_pilot_sliders():
    tasks = trial_tasks()
    tasks[0]["manual_baseline_mins"] = 1000
    report = calculate(
        EconomicsInput(prep_time_mins=60, trial_tasks=tasks, release_cycles=cycles())
    )
    assert report.expansion_gate_evaluation.median_effort_reduction_pct == 21.43
    assert report.expansion_gate_evaluation.verdict == "APPROVED_FOR_ROLLOUT"


@pytest.mark.parametrize("workflow", ["CRO_HYPOTHESIS", "PPC_COPY"])
def test_reuse_templates_are_labeled_and_have_their_own_rules(workflow):
    packet = evaluate(
        PreflightInput(workflow_type=workflow, raw_items=deepcopy(SCENARIOS[workflow]["raw_items"]))
    )
    assert packet.simulated
    assert packet.checklist_rules == SCENARIOS[workflow]["checklist_rules"]
    assert packet.overall_status == "NEEDS_EVIDENCE"
    assert calculate(EconomicsInput(workflow_type=workflow)).simulated
