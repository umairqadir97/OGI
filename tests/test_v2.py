import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.scenarios import SCENARIOS


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "test_v2.sqlite3"))) as test_client:
        yield test_client


def test_inbound_webhook_normalizes_asana_payload_with_extra_fields(client):
    payload = {
        "source": "asana",
        "workflow_type": "VISUAL_QA",
        "task_gid": "120398410293",
        "extra_unrecognized_field": {"foo": "bar", "num": 123},
        "data": {
            "gid": "120398410293",
            "name": "Header visual defect at 390px on Standard-to-Premium popup",
            "notes": "Header is nearly edge to edge at 390px on the Standard-to-Premium upgrade popup.",
            "author": "Asana Webhook Bot",
        },
    }
    response = client.post("/api/v1/webhooks/inbound", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["step_0_scope_status"] == "PASSED"
    assert len(data["queue_items"]) == 1
    assert data["queue_items"][0]["source_id"] == "120398410293"


def test_benchmark_trial_data_endpoint(client):
    res = client.get("/api/v1/benchmark-trial")
    assert res.status_code == 200
    data = res.json()
    assert len(data["trial_tasks"]) == 10
    assert len(data["release_cycles"]) == 2
    assert all(t["comparable_scope_confirmed"] for t in data["trial_tasks"])


def test_staged_write_execution_and_decision_memory(client):
    # Create receipt
    receipt = client.post(
        "/api/v1/preflight/evaluate",
        json={
            "workflow_type": "VISUAL_QA",
            "raw_items": SCENARIOS["VISUAL_QA"]["raw_items"],
        },
    ).json()

    # Recover event with staged actions
    recovery = client.post(
        "/api/v1/copilot/recover",
        json={
            "validation_id": receipt["validation_id"],
            "time_in_current_state_mins": 300,
            "incident_key": "v2-test-staged",
            "autonomy_mode": "STAGED_APPROVAL",
        },
    ).json()

    assert len(recovery["staged_actions"]) >= 1
    first_action = recovery["staged_actions"][0]
    assert first_action["status"] == "STAGED_FOR_APPROVAL"

    # Execute staged action
    exec_res = client.post(
        "/api/v1/copilot/staged-write/execute",
        json={
            "event_id": recovery["event_id"],
            "action_id": first_action["action_id"],
            "actor": "Umair Qadir",
            "role": "COO / Transformation",
            "rationale": "Approved staged write to Asana under SLA boundary.",
        },
    )
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["status"] == "ok"
    updated_action = next(
        a for a in exec_data["event"]["staged_actions"] if a["action_id"] == first_action["action_id"]
    )
    assert updated_action["status"] == "EXECUTED_WRITEBACK_CONFIRMED"
    assert "RECEIPT-" in updated_action["execution_receipt"]

    # Verify institutional decision memory
    memory = client.get("/api/v1/decision-memory").json()
    assert len(memory) >= 1
    assert memory[0]["actor"] == "Umair Qadir"
    assert memory[0]["human_action"] == "APPROVED"


def test_annualized_economics_with_aed_conversion(client):
    res = client.post(
        "/api/v1/economics/calculate",
        json={
            "workflow_type": "VISUAL_QA",
            "monthly_task_volume": 120,
            "currency": "AED",
            "prep_time_mins": 22,
            "rework_mins": 12,
            "duplicate_count": 8,
            "hourly_blended_cost": 45,
        },
    )
    assert res.status_code == 200
    report = res.json()
    assert report["monthly_task_volume"] == 120
    assert report["currency"] == "AED"
    assert report["exchange_rate_aed"] == 3.6725
    # Annual tasks = 120 * 12 = 1440
    # Capacity = (84 - 66) / 60 = 0.3 hrs
    # Annual capacity hours = 0.3 * 1440 = 432.0 hrs
    assert report["annualized_capacity_hours"] == 432.0
    # Value in USD = 432 * 45 = 19440.0 USD
    # Value in AED = 19440.0 * 3.6725 = 71393.4 AED
    assert report["annualized_capacity_value"] == 71393.4
    assert len(report["portfolio_workflows"]) == 5


def test_portfolio_summary_endpoint(client):
    res = client.get("/api/v1/economics/portfolio-summary?currency=AED&monthly_task_volume=120")
    assert res.status_code == 200
    data = res.json()
    assert data["currency"] == "AED"
    assert data["monthly_task_volume"] == 120
    assert len(data["workflows"]) == 5
    # Verify the 5 expected workflows
    names = [w["workflow_name"] for w in data["workflows"]]
    assert "Visual QA Redesign Pilot (Phase 1B)" in names
    assert "CRO Hypothesis & PDP Pre-Flight" in names
    assert "PPC Claim & ROAS Gate" in names
    assert "TrialSave-365 Return Interceptor" in names
    assert "Unscoped Blog Copy Generator" in names

    # Verify negative-yield sunset bot is flagged
    sunset_bot = next(w for w in data["workflows"] if w["workflow_name"] == "Unscoped Blog Copy Generator")
    assert sunset_bot["governance_verdict"] == "SUNSET_RETIRE_BOT"
    assert sunset_bot["net_effort_delta_pct"] > 0  # net effort drag
    assert sunset_bot["annualized_net_value_usd"] < 0
    assert data["active_sunset_alerts_count"] == 1


def test_trialsave_365_workflow(client):
    res = client.post(
        "/api/v1/preflight/evaluate",
        json={
            "workflow_type": "TRIALSAVE_365",
            "raw_items": SCENARIOS["TRIALSAVE_365"]["raw_items"],
        },
    )
    assert res.status_code == 200
    packet = res.json()
    assert len(packet["queue_items"]) == 3
    # Check ticket 8821 routes to CX Retention Lead
    t1 = next(i for i in packet["queue_items"] if i["source_id"] == "T1")
    assert t1["accountable_role"] == "CX Retention Lead"

    # Check recovery creates Shopify $0 draft order staged action
    rec = client.post(
        "/api/v1/copilot/recover",
        json={
            "validation_id": packet["validation_id"],
            "time_in_current_state_mins": 300,
            "incident_key": "trialsave-test",
        },
    ).json()
    shopify_action = next((a for a in rec["staged_actions"] if a["target_system"] == "Shopify GraphQL"), None)
    assert shopify_action is not None
    assert "Topper" in shopify_action["description"]


def test_llm_logs_endpoint(client):
    res = client.get("/api/v1/llm/logs")
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) >= 3
    first = logs[0]
    assert "model" in first
    assert "prompt_tokens" in first
    assert "latency_ms" in first
    assert "sha256" in first


def test_asana_task_ingestion_and_llm_telemetry(client):
    payload = {
        "task_id": "ASN-9901-QA",
        "title": "Mobile Drawer CTA button clipping at 375px",
        "description": "On iPhone 15 Pro Safari viewport, the sticky CTA button overlaps the footer drawer.",
        "author": "Rhogie Domingo",
        "workflow_type": "VISUAL_QA",
        "viewport_spec": "375px mobile",
        "figma_spec_url": "https://figma.com/test",
        "has_marked_scope": True,
        "has_device_matrix": True,
        "autonomy_mode": "STAGED_APPROVAL",
    }
    res = client.post("/api/v1/asana/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["packet"]["step_0_scope_status"] == "PASSED"
    assert len(data["packet"]["queue_items"]) == 1
    assert data["llm_log"]["task_id"] == "ASN-9901-QA"
    assert data["llm_log"]["sha256"] != ""
    assert data["event"]["event_id"] != ""


def test_asana_step_0_rejection_zero_tokens(client):
    payload = {
        "task_id": "ASN-9902-UNSCOPED",
        "title": "Unscoped visual changes without device matrix",
        "description": "Please review redesign without scope defined.",
        "author": "Associate",
        "workflow_type": "VISUAL_QA",
        "has_marked_scope": False,
        "has_device_matrix": False,
    }
    res = client.post("/api/v1/asana/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["packet"]["step_0_scope_status"] == "BLOCKED_MISSING_SCOPE"
    assert data["llm_log"]["prompt_tokens"] == 0
    assert data["llm_log"]["completion_tokens"] == 0
    assert "0 Tokens" in data["llm_log"]["status"]


def test_asana_simulate_preset(client):
    res = client.post("/api/v1/asana/simulate?preset=cro_hypothesis")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["preset"] == "cro_hypothesis"
    assert data["packet"]["workflow_type"] == "CRO_HYPOTHESIS"

