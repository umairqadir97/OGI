import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.scenarios import SCENARIOS
from app.store import Store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "test.sqlite3"))) as test_client:
        yield test_client


def request_data(**kwargs):
    return {
        "workflow_type": "VISUAL_QA",
        "raw_items": SCENARIOS["VISUAL_QA"]["raw_items"],
        **kwargs,
    }


def create_receipt(client):
    response = client.post("/api/v1/preflight/evaluate", json=request_data())
    assert response.status_code == 200
    return response.json()


def test_end_to_end_persistent_receipts_recovery_and_economics(client):
    packet = create_receipt(client)
    val_id = packet["validation_id"]
    assert client.get(packet["permalink"]).status_code == 200
    assert client.get(f"/api/v1/val/{val_id}").json() == packet
    recovery = {
        "validation_id": val_id,
        "time_in_current_state_mins": 300,
        "incident_key": "test",
    }
    first = client.post("/api/v1/copilot/recover", json=recovery).json()
    second = client.post("/api/v1/copilot/recover", json=recovery).json()
    assert first == second
    assert len(client.get(f"/api/v1/val/{val_id}/events").json()) == 1
    report = client.post("/api/v1/economics/calculate", json={"validation_id": val_id}).json()
    assert report["ai_pilot_breakdown_mins"]["total_assisted_person_mins"] == 96
    assert report["ai_pilot_breakdown_mins"]["exception_rework_mins"] == 30
    history = client.get("/api/v1/validations").json()
    assert history[0]["id"] == val_id
    assert len(history[0]["sha256"]) == 64


def test_restart_keeps_validation_links(tmp_path):
    path = str(tmp_path / "persist.sqlite3")
    with TestClient(create_app(path)) as first:
        packet = create_receipt(first)
    with TestClient(create_app(path)) as second:
        assert second.get(f"/api/v1/val/{packet['validation_id']}").json() == packet


def test_concurrent_duplicate_recovery_is_idempotent(client):
    packet = create_receipt(client)
    body = {"validation_id": packet["validation_id"], "incident_key": "concurrent"}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: client.post("/api/v1/copilot/recover", json=body).json(),
                range(8),
            )
        )
    assert len({event["event_id"] for event in results}) == 1


def test_human_decision_creates_revision_preserving_original(client):
    packet = create_receipt(client)
    val_id = packet["validation_id"]
    client.post("/api/v1/copilot/recover", json={"validation_id": val_id})
    decision = {
        "source_id": "F4",
        "reviewer": "QA Lead",
        "decision": "CONFIRM",
        "rationale": "Checked the body text at 390px on a real device against the approved 18px rule.",
        "evidence_references": ["artifact:font-capture-390"],
    }
    response = client.post(f"/api/v1/val/{val_id}/decisions", json=decision)
    assert response.status_code == 200
    revised = response.json()
    assert revised["validation_id"] != val_id
    assert revised["parent_validation_id"] == val_id
    assert revised["queue_items"][3]["status"] == "CONFIRMED_READY"
    assert client.get(f"/api/v1/val/{val_id}").json() == packet
    # The work already spent on clarification stays in the lineage after evidence resolution.
    client.post("/api/v1/copilot/recover", json={"validation_id": revised["validation_id"]})
    report = client.post(
        "/api/v1/economics/calculate", json={"validation_id": revised["validation_id"]}
    ).json()
    assert report["ai_pilot_breakdown_mins"]["exception_rework_mins"] == 30


def test_confirmation_requires_evidence_and_scope(client):
    packet = create_receipt(client)
    decision = {
        "source_id": "F4",
        "reviewer": "QA Lead",
        "decision": "CONFIRM",
        "rationale": "An unsubstantiated approval.",
    }
    assert (
        client.post(f"/api/v1/val/{packet['validation_id']}/decisions", json=decision).status_code
        == 422
    )
    blocked = client.post(
        "/api/v1/preflight/evaluate", json=request_data(has_marked_asana_scope=False)
    ).json()
    decision["evidence_references"] = ["artifact:evidence"]
    assert (
        client.post(f"/api/v1/val/{blocked['validation_id']}/decisions", json=decision).status_code
        == 409
    )


def test_unknown_ids_do_not_mint_data(client):
    assert client.get("/api/v1/val/unknown").status_code == 404
    assert client.get("/val/unknown").status_code == 404
    assert (
        client.post("/api/v1/copilot/recover", json={"validation_id": "unknown"}).status_code == 404
    )
    assert (
        client.post("/api/v1/economics/calculate", json={"validation_id": "unknown"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        {"prep_time_mins": -1},
        {"prep_time_mins": 61},
        {"duplicate_count": 25},
        {"duplicate_count": 1.5},
        {"rework_mins": 41},
        {"hourly_blended_cost": "NaN"},
        {"invented": 1},
    ],
)
def test_invalid_economics_rejected(client, body):
    assert client.post("/api/v1/economics/calculate", json=body).status_code == 422


def test_workflow_mismatch_rejected(client):
    packet = create_receipt(client)
    assert (
        client.post(
            "/api/v1/economics/calculate",
            json={
                "validation_id": packet["validation_id"],
                "workflow_type": "PPC_COPY",
            },
        ).status_code
        == 422
    )


def test_duplicate_sources_and_wrong_boolean_rejected(client):
    raw = SCENARIOS["VISUAL_QA"]["raw_items"][0]
    assert (
        client.post("/api/v1/preflight/evaluate", json={"raw_items": [raw, raw]}).status_code == 422
    )
    assert (
        client.post(
            "/api/v1/preflight/evaluate",
            json=request_data(has_marked_asana_scope="false"),
        ).status_code
        == 422
    )


def test_scope_input_and_endpoint_aliases(client):
    response = client.post("/api/v1/preflight/validate", json=request_data(has_marked_scope=False))
    assert response.json()["overall_status"] == "FAIL"


def test_sqlite_enforces_immutability(client):
    packet = create_receipt(client)
    store = client.app.state.store
    for sql in [
        "UPDATE receipts SET workflow='PPC_COPY' WHERE id=?",
        "DELETE FROM receipts WHERE id=?",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            with store.connection() as con:
                con.execute(sql, (packet["validation_id"],))


def test_integrity_verification_detects_tampering(client):
    packet = create_receipt(client)
    store: Store = client.app.state.store
    with store.connection() as con:
        con.execute("DROP TRIGGER immutable_receipt_update")
        con.execute("UPDATE receipts SET sha256='bad' WHERE id=?", (packet["validation_id"],))
    with pytest.raises(ValueError, match="integrity"):
        store.get(packet["validation_id"])


def test_frontend_and_openapi_available(client):
    assert "Confidence before scale." in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert "/api/v1/preflight/evaluate" in client.get("/openapi.json").json()["paths"]
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"


def test_trial_snapshots_survive_restart_and_preserve_previous_versions(tmp_path):
    path = str(tmp_path / "trials.sqlite3")
    evidence = {"workflow_type": "VISUAL_QA", "trial_tasks": [], "release_cycles": []}
    with TestClient(create_app(path)) as client:
        assert client.get("/api/v1/trials/VISUAL_QA").json() is None
        first = client.post("/api/v1/trials", json=evidence).json()
        evidence["release_cycles"] = [
            {"cycle_id": "r1", "baseline_escaped_defects": 0, "assisted_escaped_defects": 1}
        ]
        second = client.post("/api/v1/trials", json=evidence).json()
        assert first["snapshot_id"] != second["snapshot_id"]
        assert client.get("/api/v1/trials/PPC_COPY").json() is None
    with TestClient(create_app(path)) as client:
        assert client.get("/api/v1/trials/VISUAL_QA").json() == second
        result = client.post("/api/v1/economics/calculate", json=second["evidence"]).json()
        assert result["expansion_gate_evaluation"]["verdict"] != "APPROVED_FOR_ROLLOUT"
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM trial_snapshots").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            con.execute("DELETE FROM trial_snapshots")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            con.execute("UPDATE trial_snapshots SET payload='{}'")


def test_trial_evidence_rejects_duplicate_and_unknown_quality(client):
    cycle = {"cycle_id": "r1", "baseline_escaped_defects": 0, "assisted_escaped_defects": 0}
    assert client.post("/api/v1/trials", json={"release_cycles": [cycle, cycle]}).status_code == 422
    assert (
        client.post("/api/v1/trials", json={"release_cycles": [{"cycle_id": "r1"}]}).status_code
        == 422
    )
    assert client.get("/api/v1/trials/unknown").status_code == 422
