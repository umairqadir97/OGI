"""Versioned, bounded contracts shared by all OGI v2.0 modules."""

from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


Workflow = Literal["VISUAL_QA", "CRO_HYPOTHESIS", "PPC_COPY", "TRIALSAVE_365"]
Role = Literal[
    "QA Lead",
    "Product Owner",
    "Designer",
    "Release Owner",
    "Experiment Owner",
    "Paid Media Lead",
    "CX Retention Lead",
    "Warranty Specialist",
]
Minutes = Annotated[float, Field(ge=0, le=10080)]
Text = Annotated[str, Field(min_length=1, max_length=6000)]
AutonomyMode = Literal["SHADOW", "STAGED_APPROVAL", "BOUNDED_AUTONOMOUS"]


class RawItem(Contract):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    author: str = Field(default="Reviewer", min_length=1, max_length=100)
    comment_text: Text


class PreflightInput(Contract):
    workflow_type: Workflow = "VISUAL_QA"
    has_marked_asana_scope: bool = Field(
        default=True,
        strict=True,
        validation_alias=AliasChoices("has_marked_asana_scope", "has_marked_scope"),
    )
    has_device_matrix: bool = Field(default=True, strict=True)
    raw_items: list[RawItem] = Field(min_length=1, max_length=100)
    checklist_rules: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=30
    )

    @model_validator(mode="after")
    def unique_sources(self):
        if len({i.id for i in self.raw_items}) != len(self.raw_items):
            raise ValueError("Each source ID must be unique.")
        return self


class InboundWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = "asana"  # "asana", "n8n", "shopify"
    workflow_type: Workflow = "VISUAL_QA"
    event_type: str | None = None
    task_gid: str | None = None
    data: dict | list | None = None
    raw_text: str | None = None
    author: str | None = "Webhook"
    has_marked_scope: bool = True
    has_device_matrix: bool = True


class Entities(Contract):
    element: str | None = None
    element_named: bool = False
    viewport_px: int | None = None
    popup_variant: str | None = None
    measured_value: str | None = None


class QueueItem(Contract):
    source_id: str
    issue_summary: str
    status: Literal[
        "UNCONFIRMED",
        "UNCONFIRMED_MISSING_EVIDENCE",
        "BLOCKED_MISSING_SCOPE",
        "CONFIRMED_READY",
    ]
    missing_evidence: list[str]
    merge_guardrail_note: str
    merge_status: Literal["KEEP_SEPARATE_PENDING_EVIDENCE", "NOT_MERGED"] = "NOT_MERGED"
    next_action: str
    accountable_role: Role
    exception_type: Literal[
        "MISSING_SCOPE_BRIEF",
        "MISSING_VIEWPORT_OR_ELEMENT",
        "DESIGN_RULE_AMBIGUITY",
        "PRODUCT_COPY_CONFIRMATION",
    ]
    entities: Entities = Field(default_factory=Entities)


class HumanDecision(Contract):
    source_id: str
    reviewer: str = Field(min_length=2, max_length=100)
    decision: Literal["CONFIRM", "REQUEST_EVIDENCE"]
    rationale: str = Field(min_length=10, max_length=3000)
    evidence_references: list[Annotated[str, Field(min_length=3, max_length=2000)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def evidence_required(self):
        if self.decision == "CONFIRM" and not self.evidence_references:
            raise ValueError("Confirmation requires at least one evidence reference.")
        return self


class ValidationPacket(Contract):
    schema_version: str = "2.0"
    validation_id: str
    parent_validation_id: str | None = None
    workflow_type: Workflow
    timestamp_utc: str
    step_0_scope_status: Literal["PASSED", "BLOCKED_MISSING_SCOPE"]
    overall_status: Literal["PASS", "NEEDS_EVIDENCE", "FAIL"]
    reusable_prompt_used: str
    initial_ai_output_excerpt: str | None = None
    engine_mode: str = "HYBRID_DETERMINISTIC_AND_SEMANTIC"
    ai_tokens_spent: int = 0
    raw_input: PreflightInput
    checklist_rules: list[str]
    verification_check_log: list[str]
    queue_items: list[QueueItem]
    human_override_decisions: list[HumanDecision] = Field(default_factory=list)
    permalink: str
    simulated: bool = False


class RecoveryInput(Contract):
    validation_id: str
    time_in_current_state_mins: Minutes = 300
    incident_key: str = Field(default="cross-hub-demo", min_length=1, max_length=100)
    autonomy_mode: AutonomyMode = "STAGED_APPROVAL"


class AsanaComment(Contract):
    target_role: Role
    items: list[str]
    steps: list[str]
    plain_english_runbook: str
    sla_window: str = "Resolve before Dubai GST → LA PST Handoff (4h SLA)"
    do_not_do_guardrail: str | None = None
    numbered_action_steps: list[str] = Field(default_factory=list)
    self_heal_verification_check: str | None = None


class StagedWriteAction(Contract):
    action_id: str
    action_type: str  # "ASANA_COMMENT", "ASANA_REASSIGN", "SHOPIFY_DRAFT_ORDER", "N8N_REDIS_RETRY"
    target_system: str  # "Asana", "Shopify GraphQL", "n8n Redis"
    description: str
    payload_preview: dict
    status: Literal["STAGED_FOR_APPROVAL", "EXECUTED_WRITEBACK_CONFIRMED"] = "STAGED_FOR_APPROVAL"
    execution_receipt: str | None = None
    executed_at_utc: str | None = None
    executed_by: str | None = None


class ExceptionRunbookEvent(Contract):
    event_id: str
    validation_id: str
    timestamp_utc: str
    incident_key: str
    stalled_hub_handoff: str = "Asia/Dubai → America/Los_Angeles"
    is_stalled: bool
    blocked_item_ids: list[str]
    total_rework_minutes_added: float
    minutes_classification: str = "ESTIMATE_NOT_OBSERVED"
    asana_delivery_status: str = "DRAFT_ONLY_NOT_CONNECTED"
    asana_auto_comments: list[AsanaComment]
    autonomy_mode: AutonomyMode = "STAGED_APPROVAL"
    staged_actions: list[StagedWriteAction] = Field(default_factory=list)


class StagedWriteExecutionRequest(Contract):
    event_id: str
    action_id: str
    actor: str = "Operations Lead"
    role: str = "COO / Transformation"
    rationale: str = "Approved staged execution under bounded governance rule."


class DecisionMemoryEntry(Contract):
    entry_id: str
    timestamp_utc: str
    actor: str
    role: str
    workflow_type: str
    ai_recommendation: str
    human_action: Literal["APPROVED", "OVERRIDDEN"]
    rationale: str
    governance_rule: str
    predicted_vs_verified_impact: str


class TrialTask(Contract):
    task_id: str = Field(min_length=1, max_length=100)
    manual_baseline_mins: float = Field(gt=0, le=10080)
    prep_mins: Minutes
    ai_mins: Minutes
    review_mins: Minutes
    logging_mins: Minutes
    rework_mins: Minutes
    major_misses_baseline: int = Field(ge=0, le=10000, strict=True)
    major_misses_assisted: int = Field(ge=0, le=10000, strict=True)
    comparable_scope_confirmed: bool = Field(default=False, strict=True)


class ReleaseCycle(Contract):
    cycle_id: str = Field(min_length=1, max_length=100)
    baseline_escaped_defects: int = Field(ge=0, le=10000, strict=True)
    assisted_escaped_defects: int = Field(ge=0, le=10000, strict=True)


class TrialEvidenceInput(Contract):
    workflow_type: Workflow = "VISUAL_QA"
    trial_tasks: list[TrialTask] = Field(default_factory=list, max_length=10)
    release_cycles: list[ReleaseCycle] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def distinct_records(self):
        for records, attr in [
            (self.trial_tasks, "task_id"),
            (self.release_cycles, "cycle_id"),
        ]:
            if len({getattr(r, attr) for r in records}) != len(records):
                raise ValueError(f"Duplicate {attr} is not allowed.")
        return self


class TrialLedgerSnapshot(Contract):
    snapshot_id: str
    timestamp_utc: str
    evidence: TrialEvidenceInput


class EconomicsInput(TrialEvidenceInput):
    prep_time_mins: float = Field(default=22, ge=0, le=60)
    rework_mins: float = Field(default=12, ge=0, le=40)
    duplicate_count: int = Field(default=8, ge=0, le=24, strict=True)
    hourly_blended_cost: float = Field(default=45, ge=0, le=1000)
    software_cost_per_task: float = Field(default=0, ge=0, le=10000)
    maintenance_cost_per_task: float = Field(default=0, ge=0, le=10000)
    validation_id: str | None = None
    monthly_task_volume: int = Field(default=120, ge=10, le=5000)
    currency: Literal["USD", "AED"] = "USD"


class EffortBreakdown(Contract):
    unrecorded_prep_mins: float
    ai_generation_mins: float
    human_review_mins: float
    rework_and_logging_mins: float
    exception_rework_mins: float
    total_assisted_person_mins: float


class QualityAudit(Contract):
    raw_ai_entries: int = 40
    gross_valid_in_scope: int = 24
    estimated_duplicates: int
    true_unique_valid: int
    true_unique_precision_pct: float
    false_positives_not_issues: int = 10
    valid_out_of_scope: int = 2
    by_design_noise: int = 4
    manual_grouped_concerns: int = 17
    direct_matches: int = 2
    related_concerns: int = 5
    unreported_manual_concerns: int = 10
    recall_status: str = "UNMEASURABLE_PENDING_MANUAL_ACCEPTANCE"


class ExpansionGate(Contract):
    target_effort_reduction_pct: float = 20
    meets_effort_threshold: bool
    trial_task_count: int
    release_cycle_count: int
    median_effort_reduction_pct: float | None
    major_visual_misses_delta: int | None
    escaped_defects_2_cycles_delta: int | None
    verdict: Literal["HOLD_EXTEND_TRIAL", "CONTROLLED_10_TASK_TRIAL_ONLY", "APPROVED_FOR_ROLLOUT"]
    reasons: list[str]
    reporting_classification: str = "CAPACITY_RELEASED_NOT_CASH_SAVINGS"


class PortfolioWorkflowItem(Contract):
    workflow_name: str
    owner: str
    baseline_effort: str
    post_ai_effort: str
    net_effort_delta_pct: float
    economic_classification: Literal["CAPACITY_RELEASED", "HARD_CASH_SAVINGS", "REWORK_TAX_LIABILITY"]
    annualized_net_value_usd: float
    annualized_net_value_aed: float
    governance_verdict: Literal["APPROVED_FOR_ROLLOUT", "CONTROLLED_10_TASK_TRIAL", "SUNSET_RETIRE_BOT"]
    description: str


class PortfolioEconomicsReport(Contract):
    workflow_name: str
    simulated: bool
    baseline_manual_combined_mins: float
    baseline_manual_avg_mins: float
    baseline_caveat: str
    ai_pilot_breakdown_mins: EffortBreakdown
    net_effort_reduction_pct: float
    capacity_released_hours: float
    capacity_value: float
    net_capacity_value_after_costs: float
    cash_savings: float = 0
    quality_audit: QualityAudit
    expansion_gate_evaluation: ExpansionGate
    monthly_task_volume: int = 120
    currency: Literal["USD", "AED"] = "USD"
    exchange_rate_aed: float = 3.6725
    annualized_capacity_hours: float = 0
    annualized_capacity_value: float = 0
    annualized_net_benefit: float = 0
    portfolio_workflows: list[PortfolioWorkflowItem] = Field(default_factory=list)


class PortfolioSummaryResponse(Contract):
    currency: Literal["USD", "AED"] = "USD"
    monthly_task_volume: int = 120
    exchange_rate_aed: float = 3.6725
    total_net_value_usd: float
    total_net_value_aed: float
    total_cash_savings_usd: float
    total_cash_savings_aed: float
    active_sunset_alerts_count: int = 1
    workflows: list[PortfolioWorkflowItem]


class LLMAuditLogEntry(Contract):
    id: str
    timestamp_utc: str
    model: str
    task_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    status: str
    prompt_snippet: str
    response_snippet: str
    sha256: str


class AsanaTaskSubmission(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str = Field(default="ASANA-101", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=6000)
    workflow_type: Workflow = "VISUAL_QA"
    has_marked_scope: bool = True
    has_device_matrix: bool = True
    viewport_spec: str = "390px iOS Safari"
    figma_spec_url: str = ""
    author: str = "Asana Operator"
    autonomy_mode: AutonomyMode = "STAGED_APPROVAL"
