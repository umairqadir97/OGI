import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .engine import (
    build_portfolio_summary,
    calculate,
    evaluate,
    identifier,
    recover,
    utc_now,
)
from .models import (
    AsanaTaskSubmission,
    DecisionMemoryEntry,
    EconomicsInput,
    ExceptionRunbookEvent,
    HumanDecision,
    InboundWebhookPayload,
    LLMAuditLogEntry,
    PortfolioEconomicsReport,
    PortfolioSummaryResponse,
    PreflightInput,
    RawItem,
    RecoveryInput,
    StagedWriteExecutionRequest,
    TrialEvidenceInput,
    TrialLedgerSnapshot,
    ValidationPacket,
    Workflow,
)
from .llm import call_gemini_api, process_asana_ticket
from .scenarios import BENCHMARK_TRIAL_DATA, SCENARIOS
from .store import Store

ROOT = Path(__file__).resolve().parent


def create_app(db_path: str | None = None) -> FastAPI:
    resolved_db_path = db_path or os.environ.get(
        "OGI_DB_PATH", str(ROOT.parent / "data" / "ogi.sqlite3")
    )

    @asynccontextmanager
    async def lifespan(app):
        if not hasattr(app.state, "store") or app.state.store is None:
            app.state.store = Store(resolved_db_path)
        yield

    app = FastAPI(
        title="OpsGate AI (OGI v2.0)",
        version="2.0.0",
        description="Local operational governance & decision intelligence workbench. Deterministic checks, staged writes, and closed-loop memory.",
        lifespan=lifespan,
    )
    app.state.store = Store(resolved_db_path)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def receipt(val_id: str):
        packet = app.state.store.get(val_id)
        if packet is None:
            raise HTTPException(404, "Validation receipt not found.")
        return packet

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/val/{val_id}", include_in_schema=False)
    def permalink(val_id: str):
        receipt(val_id)
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "2.0.0", "engine": "hybrid_deterministic_semantic", "asana": "staged_writes_ready"}

    @app.get("/api/v1/scenarios")
    def scenarios():
        return SCENARIOS

    @app.get("/api/v1/benchmark-trial")
    def benchmark_trial():
        return BENCHMARK_TRIAL_DATA

    @app.post(
        "/api/v1/preflight/validate",
        response_model=ValidationPacket,
        include_in_schema=False,
    )
    @app.post("/api/v1/preflight/evaluate", response_model=ValidationPacket)
    def preflight(data: PreflightInput):
        return app.state.store.save(evaluate(data))

    @app.post("/api/v1/webhooks/inbound", response_model=ValidationPacket)
    def inbound_webhook(payload: InboundWebhookPayload):
        raw_items = []
        if payload.raw_text:
            raw_items.append(
                RawItem(
                    id="WH-1",
                    author=payload.author or "Webhook",
                    comment_text=payload.raw_text,
                )
            )
        elif isinstance(payload.data, list) and payload.data:
            for idx, item in enumerate(payload.data, 1):
                if isinstance(item, dict):
                    c_id = str(item.get("id") or item.get("gid") or f"WH-{idx}")
                    auth = str(item.get("author") or item.get("user") or payload.author or "Webhook")
                    txt = str(item.get("text") or item.get("notes") or item.get("comment_text") or str(item))
                    raw_items.append(RawItem(id=c_id, author=auth, comment_text=txt))
                else:
                    raw_items.append(RawItem(id=f"WH-{idx}", author=payload.author or "Webhook", comment_text=str(item)))
        elif isinstance(payload.data, dict):
            c_id = str(payload.data.get("id") or payload.data.get("gid") or payload.task_gid or "WH-1")
            auth = str(payload.data.get("author") or payload.author or "Webhook")
            txt = str(payload.data.get("text") or payload.data.get("notes") or payload.data.get("name") or "Inbound Task")
            raw_items.append(RawItem(id=c_id, author=auth, comment_text=txt))
        else:
            raw_items.append(
                RawItem(
                    id="WH-1",
                    author=payload.author or "Webhook",
                    comment_text="Inbound Asana/n8n event received.",
                )
            )

        preflight_input = PreflightInput(
            workflow_type=payload.workflow_type,
            has_marked_asana_scope=payload.has_marked_scope,
            has_device_matrix=payload.has_device_matrix,
            raw_items=raw_items,
        )
        return app.state.store.save(evaluate(preflight_input))

    @app.get("/api/v1/val/{val_id}", response_model=ValidationPacket)
    def get_receipt(val_id: str):
        return receipt(val_id)

    @app.get("/api/v1/validations")
    def history(workflow_type: Workflow = "VISUAL_QA"):
        return app.state.store.history(workflow_type)

    @app.post("/api/v1/val/{val_id}/decisions", response_model=ValidationPacket)
    def decide(val_id: str, decision: HumanDecision):
        original = receipt(val_id)
        if original.step_0_scope_status != "PASSED":
            raise HTTPException(
                409,
                "Resolve the scope gate and rerun validation before reviewing evidence.",
            )
        revised = original.model_copy(deep=True)
        item = next((i for i in revised.queue_items if i.source_id == decision.source_id), None)
        if not item:
            raise HTTPException(404, "Source item not found in this receipt.")
        item.status = (
            "CONFIRMED_READY" if decision.decision == "CONFIRM" else "UNCONFIRMED_MISSING_EVIDENCE"
        )
        item.missing_evidence = [] if decision.decision == "CONFIRM" else [decision.rationale]
        item.next_action = (
            "Evidence accepted by the named reviewer; ready for the accountable owner."
            if decision.decision == "CONFIRM"
            else decision.rationale
        )
        revised.human_override_decisions.append(decision)
        revised.parent_validation_id = original.validation_id
        revised.validation_id = identifier("VAL")
        revised.timestamp_utc = utc_now()
        revised.permalink = f"/val/{revised.validation_id}"
        revised.overall_status = (
            "PASS"
            if all(i.status == "CONFIRMED_READY" for i in revised.queue_items)
            else "NEEDS_EVIDENCE"
        )
        revised.verification_check_log.append(
            f"Human decision: {decision.reviewer} recorded {decision.decision} for {decision.source_id}. Evidence references are reviewer attestations; not independently fetched."
        )
        return app.state.store.save(revised)

    @app.post("/api/v1/copilot/recover", response_model=ExceptionRunbookEvent)
    def recovery(data: RecoveryInput):
        return app.state.store.save_event(
            recover(
                receipt(data.validation_id),
                data.time_in_current_state_mins,
                data.incident_key,
                data.autonomy_mode,
            )
        )

    @app.post("/api/v1/copilot/staged-write/execute")
    def execute_staged_write(req: StagedWriteExecutionRequest):
        event, memory = app.state.store.execute_staged_action(
            req.event_id, req.action_id, req.actor, req.role, req.rationale
        )
        if not event:
            raise HTTPException(404, "Event or staged action not found.")
        return {"status": "ok", "event": event, "decision_memory": memory}

    @app.get("/api/v1/decision-memory", response_model=list[DecisionMemoryEntry])
    def decision_memory(limit: int = 50):
        return app.state.store.list_decision_memory(limit)

    @app.get("/api/v1/val/{val_id}/events", response_model=list[ExceptionRunbookEvent])
    def events(val_id: str):
        receipt(val_id)
        return app.state.store.events(val_id)

    @app.post("/api/v1/trials", response_model=TrialLedgerSnapshot)
    def save_trial(data: TrialEvidenceInput):
        return app.state.store.save_trial(
            TrialLedgerSnapshot(
                snapshot_id=identifier("TRIAL"),
                timestamp_utc=utc_now(),
                evidence=data,
            )
        )

    @app.get("/api/v1/trials/{workflow_type}", response_model=TrialLedgerSnapshot | None)
    def latest_trial(workflow_type: Workflow):
        return app.state.store.latest_trial(workflow_type)

    @app.post("/api/v1/economics/calculate", response_model=PortfolioEconomicsReport)
    def economics(data: EconomicsInput):
        if data.validation_id:
            packet = receipt(data.validation_id)
            if packet.workflow_type != data.workflow_type:
                raise HTTPException(422, "Validation receipt belongs to a different workflow.")
        return calculate(
            data,
            app.state.store.rework(data.validation_id) if data.validation_id else 0,
        )

    @app.get(
        "/api/v1/economics/portfolio-summary",
        response_model=PortfolioSummaryResponse,
    )
    def portfolio_summary(
        currency: str = "USD",
        monthly_task_volume: int = 120,
    ):
        curr = "AED" if currency.upper() == "AED" else "USD"
        return build_portfolio_summary(curr, monthly_task_volume)

    @app.get("/api/v1/llm/logs", response_model=list[LLMAuditLogEntry])
    def llm_logs(limit: int = 50):
        return app.state.store.list_llm_logs(limit)

    @app.post("/api/v1/asana/ingest")
    def ingest_asana_task(ticket: AsanaTaskSubmission):
        packet, llm_entry, event = process_asana_ticket(ticket, app.state.store)
        return {
            "status": "ok",
            "validation_id": packet.validation_id,
            "packet": packet,
            "llm_log": llm_entry,
            "event": event,
        }

    @app.post("/api/v1/asana/simulate")
    def simulate_asana_task(preset: str = "visual_qa_clip"):
        presets = {
            "visual_qa_clip": AsanaTaskSubmission(
                task_id="ASN-10924-QA",
                title="PDP Mobile Checkout CTA Button 375px Padding Clipping",
                description="Reviewer identified Monarch King checkout drawer CTA button overlaps bottom navigation bar when rendered on iPhone 15 Pro viewport at 375px.",
                author="Head of QA",
                workflow_type="VISUAL_QA",
                viewport_spec="375px Mobile (iPhone 15 Pro / Safari)",
                figma_spec_url="https://figma.com/file/puffy-pdp-redesign#node-104",
                has_marked_scope=True,
                has_device_matrix=True,
                autonomy_mode="STAGED_APPROVAL",
            ),
            "cro_hypothesis": AsanaTaskSubmission(
                task_id="ASN-10931-CRO",
                title="PDP Sleep Trial Guarantee vs Saatva Comparison Table MDE",
                description="Experiment proposed to surface 365-night trial guarantee above fold. Requires MDE statistical power confirmation and mobile comparison table hierarchy check.",
                author="VP Digital Experience & Conversion",
                workflow_type="CRO_HYPOTHESIS",
                viewport_spec="390px Mobile & 1440px Desktop",
                figma_spec_url="https://figma.com/file/puffy-cro-tests#v2",
                has_marked_scope=True,
                has_device_matrix=True,
                autonomy_mode="STAGED_APPROVAL",
            ),
            "ppc_claim_gate": AsanaTaskSubmission(
                task_id="ASN-10940-PPC",
                title="Google Ads Copy: Puffy Cloud Mattress Pocketed Coils",
                description="Ad creative submitted claiming Puffy Cloud has pocketed coils. Source pack verification flagged false SKU specification (Puffy Cloud is all-foam, Lux is hybrid).",
                author="Director of Paid Media",
                workflow_type="PPC_COPY",
                viewport_spec="Google Ads Responsive Search Format",
                has_marked_scope=True,
                has_device_matrix=True,
                autonomy_mode="STAGED_APPROVAL",
            ),
            "trialsave_concession": AsanaTaskSubmission(
                task_id="ASN-10955-CX",
                title="TrialSave-365 Day 82 Return Request: Lower Back Firmness",
                description="Customer requesting mattress return for Day 82 Puffy Lux Hybrid citing lower back discomfort. Candidate for automated $0 Firm Orthopedic Topper draft order concession.",
                author="Customer Operations Lead",
                workflow_type="TRIALSAVE_365",
                viewport_spec="Zendesk Ticket #88412 / Shopify GraphQL",
                has_marked_scope=True,
                has_device_matrix=True,
                autonomy_mode="STAGED_APPROVAL",
            ),
            "step_0_sabotage": AsanaTaskSubmission(
                task_id="ASN-10960-UNSCOPED",
                title="Unscoped PDP Redesign Review Request (Missing Scope)",
                description="Ticket submitted without marked changed sections and without mobile 390px viewport crop references.",
                author="Product Owner",
                workflow_type="VISUAL_QA",
                viewport_spec="Unspecified",
                has_marked_scope=False,
                has_device_matrix=False,
                autonomy_mode="SHADOW",
            ),
        }
        ticket = presets.get(preset, presets["visual_qa_clip"])
        packet, llm_entry, event = process_asana_ticket(ticket, app.state.store)
        return {
            "status": "ok",
            "preset": preset,
            "validation_id": packet.validation_id,
            "packet": packet,
            "llm_log": llm_entry,
            "event": event,
        }

    return app


app = create_app()

