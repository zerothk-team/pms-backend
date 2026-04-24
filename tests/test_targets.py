"""
Tests for the Targets module: review cycles, target CRUD, cascade,
acknowledgement, weight validation, progress, and lock semantics.

All tests use the shared in-memory SQLite fixture from conftest.py.
Each test suite registers its own user+org via /auth/register to stay isolated.
"""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CYCLE = {
    "name": "FY2025 Annual Review",
    "cycle_type": "annual",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "target_setting_deadline": "2025-03-31",
    "actual_entry_deadline": "2025-12-15",
}

_BASE_KPI = {
    "name": "Revenue",
    "code": "REV_TARGET_TEST",
    "unit": "currency",
    "frequency": "monthly",
    "data_source": "manual",
    "scoring_direction": "higher_is_better",
}


def _reg(suffix: str, role: str = "hr_admin") -> dict:
    """Build a unique register payload."""
    return {
        "user": {
            "username": f"{suffix}_user",
            "email": f"{suffix}@targets-test.com",
            "full_name": f"{suffix.title()} User",
            "role": role,
            "password": "testpass123",
        },
        "organisation": {
            "name": f"{suffix.title()} Targets Org",
            "slug": f"{suffix}-targets-org",
        },
    }


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_cycle(client: AsyncClient, token: str, overrides: dict | None = None) -> dict:
    body = {**_BASE_CYCLE, **(overrides or {})}
    resp = await client.post("/api/v1/review-cycles/", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_kpi(client: AsyncClient, token: str, overrides: dict | None = None) -> dict:
    body = {**_BASE_KPI, **(overrides or {})}
    resp = await client.post("/api/v1/kpis/", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _activate_kpi(client: AsyncClient, token: str, kpi_id: str) -> None:
    resp = await client.patch(
        f"/api/v1/kpis/{kpi_id}/status",
        json={"status": "active"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Review Cycle: create and activate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_review_cycle(async_client: AsyncClient) -> None:
    """Creating a review cycle in DRAFT should return 201 with correct fields."""
    token = await _register_and_login(async_client, _reg("rc_create"))

    resp = await async_client.post(
        "/api/v1/review-cycles/",
        json=_BASE_CYCLE,
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "FY2025 Annual Review"
    assert data["status"] == "draft"
    assert data["cycle_type"] == "annual"


@pytest.mark.asyncio
async def test_create_review_cycle_invalid_dates(async_client: AsyncClient) -> None:
    """end_date before start_date must be rejected at schema level (422)."""
    token = await _register_and_login(async_client, _reg("rc_bad_dates"))

    resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={**_BASE_CYCLE, "start_date": "2025-12-31", "end_date": "2025-01-01"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_activate_review_cycle(async_client: AsyncClient) -> None:
    """DRAFT → ACTIVE transition should succeed."""
    token = await _register_and_login(async_client, _reg("rc_activate"))
    cycle = await _create_cycle(async_client, token)

    resp = await async_client.patch(
        f"/api/v1/review-cycles/{cycle['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_cannot_create_overlapping_active_cycle(async_client: AsyncClient) -> None:
    """Two ACTIVE cycles with overlapping dates for same org must be rejected (409)."""
    token = await _register_and_login(async_client, _reg("rc_overlap"))
    cycle1 = await _create_cycle(async_client, token)

    # Activate first cycle
    await async_client.patch(
        f"/api/v1/review-cycles/{cycle1['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    # Attempt second overlapping cycle
    resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={**_BASE_CYCLE, "name": "Duplicate Active Cycle"},
        headers=_auth(token),
    )
    # Must fail: an active cycle already covers this date range
    assert resp.status_code in (409, 400), resp.text


@pytest.mark.asyncio
async def test_update_cycle_only_in_draft(async_client: AsyncClient) -> None:
    """Updating name/deadlines on a non-DRAFT cycle must be rejected (400)."""
    token = await _register_and_login(async_client, _reg("rc_upd_draft"))
    cycle = await _create_cycle(async_client, token)

    # Activate
    await async_client.patch(
        f"/api/v1/review-cycles/{cycle['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    resp = await async_client.put(
        f"/api/v1/review-cycles/{cycle['id']}",
        json={"name": "Renamed Cycle"},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# Target: create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_target_success(async_client: AsyncClient) -> None:
    """Creating an INDIVIDUAL target for an active KPI in an open cycle returns 201."""
    token = await _register_and_login(async_client, _reg("tgt_create"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_CREATE_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    # Get the user's own id
    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "1000000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] in ("draft", "locked")
    assert float(data["target_value"]) == 1_000_000.0


@pytest.mark.asyncio
async def test_create_target_inactive_kpi_fails(async_client: AsyncClient) -> None:
    """Creating a target for a DRAFT (not active) KPI must be rejected (400)."""
    token = await _register_and_login(async_client, _reg("tgt_inactive_kpi"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_INACTIVE_KPI"})
    # KPI stays in DRAFT — not activated
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "500.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_create_duplicate_target_fails(async_client: AsyncClient) -> None:
    """Creating the same target (same kpi + cycle + user) twice returns 409."""
    token = await _register_and_login(async_client, _reg("tgt_dup"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_DUP_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    body = {
        "kpi_id": kpi["id"],
        "review_cycle_id": cycle["id"],
        "assignee_type": "individual",
        "assignee_user_id": user_id,
        "target_value": "800.00",
        "weight": "100.00",
    }
    r1 = await async_client.post("/api/v1/targets/", json=body, headers=_auth(token))
    assert r1.status_code == 201, r1.text

    r2 = await async_client.post("/api/v1/targets/", json=body, headers=_auth(token))
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_create_target_locked_when_cycle_active(async_client: AsyncClient) -> None:
    """Target created while cycle is ACTIVE should start as LOCKED."""
    token = await _register_and_login(async_client, _reg("tgt_locked"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_LOCK_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    # Activate cycle first
    await async_client.patch(
        f"/api/v1/review-cycles/{cycle['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "2000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "locked"


@pytest.mark.asyncio
async def test_target_stretch_must_exceed_target(async_client: AsyncClient) -> None:
    """stretch_target_value <= target_value must be rejected at schema level (422)."""
    token = await _register_and_login(async_client, _reg("tgt_stretch"))
    kpi = await _create_kpi(async_client, token, {"code": "TGT_STRETCH_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)
    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "1000.00",
            "stretch_target_value": "900.00",  # less than target — invalid
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Target: update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_locked_target_fails(async_client: AsyncClient) -> None:
    """Updating a LOCKED target must be rejected with 400."""
    token = await _register_and_login(async_client, _reg("tgt_upd_lock"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_UPD_LOCK_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    # Activate cycle so target is auto-locked
    await async_client.patch(
        f"/api/v1/review-cycles/{cycle['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    create_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "500.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    target_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "locked"

    upd_resp = await async_client.put(
        f"/api/v1/targets/{target_id}",
        json={"target_value": "999.00"},
        headers=_auth(token),
    )
    assert upd_resp.status_code in (400, 403), upd_resp.text


# ---------------------------------------------------------------------------
# Target: bulk create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_create_targets(async_client: AsyncClient) -> None:
    """Bulk creating targets for multiple users returns a list."""
    token = await _register_and_login(async_client, _reg("tgt_bulk"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_BULK_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/targets/bulk",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "user_targets": [
                {
                    "user_id": user_id,
                    "target_value": 750.0,
                    "weight": 100.0,
                }
            ],
        },
        headers=_auth(token),
    )
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acknowledge_target(async_client: AsyncClient) -> None:
    """Assignee can acknowledge a PENDING_ACKNOWLEDGEMENT target."""
    token = await _register_and_login(async_client, _reg("tgt_ack"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_ACK_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    # Create target in DRAFT
    create_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "300.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    target_id = create_resp.json()["id"]

    # Move to PENDING_ACKNOWLEDGEMENT
    status_resp = await async_client.patch(
        f"/api/v1/targets/{target_id}/status",
        json={"status": "pending_acknowledgement"},
        headers=_auth(token),
    )
    assert status_resp.status_code == 200, status_resp.text

    # Acknowledge
    ack_resp = await async_client.patch(
        f"/api/v1/targets/{target_id}/acknowledge",
        headers=_auth(token),
    )
    assert ack_resp.status_code == 200, ack_resp.text
    assert ack_resp.json()["status"] == "acknowledged"


# ---------------------------------------------------------------------------
# Target: weights check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weights_check_warns_when_not_100(async_client: AsyncClient) -> None:
    """weights-check endpoint returns a warning when weights don't sum to 100."""
    token = await _register_and_login(async_client, _reg("tgt_weights"))

    kpi1 = await _create_kpi(async_client, token, {"code": "TGT_W_KPI1"})
    kpi2 = await _create_kpi(async_client, token, {"code": "TGT_W_KPI2"})
    await _activate_kpi(async_client, token, kpi1["id"])
    await _activate_kpi(async_client, token, kpi2["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    # Create two targets with weights that don't sum to 100
    await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi1["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "100.00",
            "weight": "40.00",
        },
        headers=_auth(token),
    )
    await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi2["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "200.00",
            "weight": "30.00",
        },
        headers=_auth(token),
    )

    resp = await async_client.get(
        "/api/v1/targets/weights-check",
        params={"cycle_id": cycle["id"], "user_id": user_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert float(data["total_weight"]) == pytest.approx(70.0, abs=0.01)
    assert data["is_valid"] is False
    assert "warning" in data


# ---------------------------------------------------------------------------
# Target: cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_target_equal_strategy(async_client: AsyncClient) -> None:
    """Cascade with strategy=equal distributes the same target_value to each child."""
    token = await _register_and_login(async_client, _reg("tgt_cascade_eq"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_CASC_EQ_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]
    org_id = me_resp.json()["organisation_id"]

    # Create an ORG-level parent target
    parent_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "organisation",
            "assignee_org_id": org_id,
            "target_value": "9000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    # Cascade to one user (equal) — distribution has user_id + weight, service fills target_value
    cascade_resp = await async_client.post(
        "/api/v1/targets/cascade",
        json={
            "parent_target_id": parent_id,
            "strategy": "equal",
            "distribution": [
                {"user_id": user_id, "weight": 100.0}
            ],
        },
        headers=_auth(token),
    )
    assert cascade_resp.status_code == 201, cascade_resp.text
    children = cascade_resp.json()
    assert len(children) == 1
    assert float(children[0]["target_value"]) == pytest.approx(9000.0, abs=0.01)


@pytest.mark.asyncio
async def test_cascade_target_proportional_strategy(async_client: AsyncClient) -> None:
    """Cascade with strategy=proportional distributes proportionally by weights."""
    token = await _register_and_login(async_client, _reg("tgt_cascade_prop"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_CASC_PROP_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]
    org_id = me_resp.json()["organisation_id"]

    parent_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "organisation",
            "assignee_org_id": org_id,
            "target_value": "1000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    # Proportional: user gets 100% of weight → 100% of target
    cascade_resp = await async_client.post(
        "/api/v1/targets/cascade",
        json={
            "parent_target_id": parent_id,
            "strategy": "proportional",
            "distribution": [
                {"user_id": user_id, "weight": 100.0, "target_value": 1000.0}
            ],
        },
        headers=_auth(token),
    )
    assert cascade_resp.status_code == 201, cascade_resp.text
    children = cascade_resp.json()
    assert float(children[0]["target_value"]) == pytest.approx(1000.0, abs=0.01)


@pytest.mark.asyncio
async def test_cascade_proportional_total_check(async_client: AsyncClient) -> None:
    """A cascade where sum of target_values exceeds parent must fail (400)."""
    token = await _register_and_login(async_client, _reg("tgt_cascade_bad_prop"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_CASC_BADP_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]
    org_id = me_resp.json()["organisation_id"]

    parent_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "organisation",
            "assignee_org_id": org_id,
            "target_value": "5000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    parent_id = parent_resp.json()["id"]

    # target_value of child (9000) > parent (5000) — must fail with total_check=True
    cascade_resp = await async_client.post(
        "/api/v1/targets/cascade",
        json={
            "parent_target_id": parent_id,
            "strategy": "manual",
            "total_check": True,
            "distribution": [
                {"user_id": user_id, "weight": 100.0, "target_value": 9000.0}
            ],
        },
        headers=_auth(token),
    )
    assert cascade_resp.status_code in (400, 422), cascade_resp.text


# ---------------------------------------------------------------------------
# Target: progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_target_progress(async_client: AsyncClient) -> None:
    """GET /targets/{id} returns progress fields (achievement_pct, is_at_risk, trend)."""
    token = await _register_and_login(async_client, _reg("tgt_progress"))

    kpi = await _create_kpi(async_client, token, {"code": "TGT_PROG_KPI"})
    await _activate_kpi(async_client, token, kpi["id"])
    cycle = await _create_cycle(async_client, token)

    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    create_resp = await async_client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi["id"],
            "review_cycle_id": cycle["id"],
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "1000.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    target_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/v1/targets/{target_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "achievement_percentage" in data
    assert "is_at_risk" in data
    assert "trend" in data
