"""
Tests for the per-KPI Scoring Configuration enhancement (Enhancement 1).

Covers:
  Part A — Pure-function unit tests (resolve_scoring_config, determine_rating_with_config)
  Part B — Schema validation (threshold order)
  Part C — API: CRUD for scoring configs, preset creation
  Part D — Assign config to KPI / target
  Part E — End-to-end: config-aware scoring with snapshot storage
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.scoring.calculator import determine_rating_with_config, resolve_scoring_config
from app.scoring.enums import RatingLabel, ScoringPreset
from app.scoring.kpi_scoring_schemas import KPIScoringConfigCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reg(suffix: str, role: str = "hr_admin") -> dict:
    return {
        "user": {
            "username": f"{suffix}_ksc_user",
            "email": f"{suffix}@ksc-test.com",
            "full_name": f"{suffix.title()} KSC",
            "role": role,
            "password": "testpass123",
        },
        "organisation": {
            "name": f"{suffix.title()} KSC Org",
            "slug": f"{suffix}-ksc-org",
        },
    }


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_config_payload(
    name: str = "Test Config",
    exceptional_min: float = 120,
    exceeds_min: float = 100,
    meets_min: float = 80,
    partially_meets_min: float = 60,
    does_not_meet_min: float = 0,
    achievement_cap: float = 200,
) -> dict:
    return {
        "name": name,
        "preset": "custom",
        "exceptional_min": exceptional_min,
        "exceeds_min": exceeds_min,
        "meets_min": meets_min,
        "partially_meets_min": partially_meets_min,
        "does_not_meet_min": does_not_meet_min,
        "achievement_cap": achievement_cap,
    }


# ---------------------------------------------------------------------------
# Part A — Pure function unit tests
# ---------------------------------------------------------------------------


def _mock_target(
    scoring_config=None,
    scoring_config_id=None,
    kpi_scoring_config=None,
    kpi_scoring_config_id=None,
):
    """Build a minimal target-like namespace for resolver tests."""
    kpi = SimpleNamespace(
        scoring_config=kpi_scoring_config,
        scoring_config_id=kpi_scoring_config_id,
    )
    return SimpleNamespace(
        scoring_config=scoring_config,
        scoring_config_id=scoring_config_id,
        kpi=kpi,
    )


def _mock_cfg(
    name: str,
    exceptional: float = 120,
    exceeds: float = 100,
    meets: float = 80,
    partial: float = 60,
    dne: float = 0,
    cap: float = 200,
):
    return SimpleNamespace(
        name=name,
        exceptional_min=Decimal(str(exceptional)),
        exceeds_min=Decimal(str(exceeds)),
        meets_min=Decimal(str(meets)),
        partially_meets_min=Decimal(str(partial)),
        does_not_meet_min=Decimal(str(dne)),
        achievement_cap=Decimal(str(cap)),
    )


def _mock_cycle_config(
    exceptional: float = 120,
    exceeds: float = 100,
    meets: float = 80,
    partial: float = 60,
):
    return SimpleNamespace(
        exceptional_min=Decimal(str(exceptional)),
        exceeds_min=Decimal(str(exceeds)),
        meets_min=Decimal(str(meets)),
        partially_meets_min=Decimal(str(partial)),
        does_not_meet_min=Decimal("0"),
    )


def test_resolve_uses_target_override():
    """Target-level config has highest precedence."""
    t_cfg = _mock_cfg("Target Config", exceptional=130, exceeds=110, meets=95, partial=80)
    k_cfg = _mock_cfg("KPI Config")
    cycle = _mock_cycle_config()

    target = _mock_target(
        scoring_config=t_cfg,
        scoring_config_id="some-uuid",
        kpi_scoring_config=k_cfg,
        kpi_scoring_config_id="kpi-uuid",
    )
    result = resolve_scoring_config(target, cycle)

    assert result["exceptional_min"] == 130
    assert result["source"] == "target_override:Target Config"


def test_resolve_falls_back_to_kpi_default():
    """With no target config, KPI config is used."""
    k_cfg = _mock_cfg("KPI Config", exceptional=115, exceeds=95, meets=75, partial=55)
    cycle = _mock_cycle_config()

    target = _mock_target(
        scoring_config=None,
        scoring_config_id=None,
        kpi_scoring_config=k_cfg,
        kpi_scoring_config_id="kpi-uuid",
    )
    result = resolve_scoring_config(target, cycle)

    assert result["exceptional_min"] == 115
    assert result["source"] == "kpi_default:KPI Config"


def test_resolve_falls_back_to_cycle_default():
    """With no target or KPI config, cycle config is used."""
    cycle = _mock_cycle_config(exceptional=120, exceeds=100, meets=80, partial=60)

    target = _mock_target(
        scoring_config=None,
        scoring_config_id=None,
        kpi_scoring_config=None,
        kpi_scoring_config_id=None,
    )
    result = resolve_scoring_config(target, cycle)

    assert result["exceptional_min"] == 120.0
    assert result["source"] == "cycle_default"


def test_determine_rating_with_standard_config():
    """Standard config: 88% → MEETS_EXPECTATIONS."""
    config = {
        "exceptional_min": 120, "exceeds_min": 100,
        "meets_min": 80, "partially_meets_min": 60,
        "does_not_meet_min": 0, "achievement_cap": 200, "source": "test",
    }
    label, source = determine_rating_with_config(Decimal("88"), config)
    assert label == RatingLabel.MEETS_EXPECTATIONS


def test_determine_rating_with_strict_config():
    """Strict config: 88% → PARTIALLY_MEETS (meets threshold is 95%)."""
    config = {
        "exceptional_min": 130, "exceeds_min": 110,
        "meets_min": 95, "partially_meets_min": 80,
        "does_not_meet_min": 0, "achievement_cap": 200, "source": "strict",
    }
    label, source = determine_rating_with_config(Decimal("88"), config)
    assert label == RatingLabel.PARTIALLY_MEETS


def test_determine_rating_none_returns_not_rated():
    """None achievement → NOT_RATED."""
    config = {
        "exceptional_min": 120, "exceeds_min": 100,
        "meets_min": 80, "partially_meets_min": 60,
        "does_not_meet_min": 0, "achievement_cap": 200, "source": "test",
    }
    label, _ = determine_rating_with_config(None, config)
    assert label == RatingLabel.NOT_RATED


def test_determine_rating_respects_achievement_cap():
    """Achievement capped at achievement_cap before rating comparison."""
    config = {
        "exceptional_min": 120, "exceeds_min": 100,
        "meets_min": 80, "partially_meets_min": 60,
        "does_not_meet_min": 0, "achievement_cap": 110, "source": "test",
    }
    # Raw 150%, cap=110 → capped to 110% → EXCEEDS not EXCEPTIONAL
    label, _ = determine_rating_with_config(Decimal("150"), config)
    assert label == RatingLabel.EXCEEDS_EXPECTATIONS


# ---------------------------------------------------------------------------
# Part B — Schema validation
# ---------------------------------------------------------------------------


def test_threshold_order_validation_strict():
    """Valid descending thresholds should not raise."""
    cfg = KPIScoringConfigCreate(
        name="Valid Config",
        exceptional_min=Decimal("120"),
        exceeds_min=Decimal("100"),
        meets_min=Decimal("80"),
        partially_meets_min=Decimal("60"),
    )
    assert cfg.exceptional_min == Decimal("120")


def test_threshold_equal_fails():
    """Equal adjacent thresholds should fail validation."""
    import pydantic

    with pytest.raises(pydantic.ValidationError) as exc_info:
        KPIScoringConfigCreate(
            name="Bad Config",
            exceptional_min=Decimal("100"),
            exceeds_min=Decimal("100"),  # equal → invalid
            meets_min=Decimal("80"),
            partially_meets_min=Decimal("60"),
        )
    assert "strictly greater" in str(exc_info.value).lower()


def test_threshold_reversed_fails():
    """Reversed thresholds (exceeds > exceptional) should fail."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        KPIScoringConfigCreate(
            name="Reversed",
            exceptional_min=Decimal("80"),
            exceeds_min=Decimal("100"),  # reversed
            meets_min=Decimal("60"),
            partially_meets_min=Decimal("40"),
        )


# ---------------------------------------------------------------------------
# Part C — API: CRUD for scoring configs
# ---------------------------------------------------------------------------


async def test_list_scoring_configs_returns_ok(async_client: AsyncClient):
    """Authenticated user can list scoring configs."""
    token = await _register_and_login(async_client, _reg("list_cfg"))
    resp = await async_client.get("/api/v1/scoring/configs", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


async def test_create_scoring_config(async_client: AsyncClient):
    """HR admin can create a custom scoring config."""
    token = await _register_and_login(async_client, _reg("create_cfg"))
    payload = _make_config_payload("My Custom Config")
    resp = await async_client.post("/api/v1/scoring/configs", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "My Custom Config"
    assert data["preset"] == "custom"
    assert data["is_system_preset"] is False


async def test_create_config_invalid_thresholds(async_client: AsyncClient):
    """Config with invalid thresholds should return 422."""
    token = await _register_and_login(async_client, _reg("bad_cfg"))
    payload = _make_config_payload(
        "Bad Config",
        exceptional_min=80,
        exceeds_min=100,  # higher than exceptional → invalid
    )
    resp = await async_client.post("/api/v1/scoring/configs", json=payload, headers=_auth(token))
    assert resp.status_code == 422


async def test_create_config_from_preset(async_client: AsyncClient):
    """HR admin can create a config from a named preset."""
    token = await _register_and_login(async_client, _reg("preset_cfg"))
    resp = await async_client.post(
        "/api/v1/scoring/configs/from-preset",
        json={"preset": "strict", "name": "My Strict Config"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["preset"] == "strict"
    # Strict thresholds: exceptional=130
    assert float(data["exceptional_min"]) == 130.0


async def test_get_scoring_config(async_client: AsyncClient):
    """Can retrieve a specific scoring config by ID."""
    token = await _register_and_login(async_client, _reg("get_cfg"))
    create_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Retrievable Config"),
        headers=_auth(token),
    )
    config_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/v1/scoring/configs/{config_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == config_id


async def test_update_scoring_config(async_client: AsyncClient):
    """HR admin can update a custom config's name."""
    token = await _register_and_login(async_client, _reg("upd_cfg"))
    create_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Original Name"),
        headers=_auth(token),
    )
    config_id = create_resp.json()["id"]

    resp = await async_client.put(
        f"/api/v1/scoring/configs/{config_id}",
        json={"name": "Updated Name"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


async def test_delete_scoring_config(async_client: AsyncClient):
    """HR admin can delete a custom config that has no KPI/target assignments."""
    token = await _register_and_login(async_client, _reg("del_cfg"))
    create_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Deletable Config"),
        headers=_auth(token),
    )
    config_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/api/v1/scoring/configs/{config_id}", headers=_auth(token)
    )
    assert resp.status_code == 204

    # Should no longer be found
    get_resp = await async_client.get(
        f"/api/v1/scoring/configs/{config_id}", headers=_auth(token)
    )
    assert get_resp.status_code == 404


async def test_preview_scoring_endpoint(async_client: AsyncClient):
    """Preview endpoint returns correct ratings for test values."""
    token = await _register_and_login(async_client, _reg("preview_cfg"))
    create_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Preview Config"),
        headers=_auth(token),
    )
    config_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/api/v1/scoring/configs/{config_id}/preview",
        params={"test_values": [50, 70, 90, 110, 130]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 5
    labels = [r["rating"] for r in results]
    assert "does_not_meet" in labels
    assert "meets_expectations" in labels
    assert "exceptional" in labels


# ---------------------------------------------------------------------------
# Part D — Assign scoring config to KPI and target
# ---------------------------------------------------------------------------


async def _setup_kpi_and_target(
    client: AsyncClient, token: str, suffix: str
) -> tuple[str, str, str]:
    """Create KPI → cycle → target. Returns (kpi_id, target_id, cycle_id)."""
    kpi_resp = await client.post(
        "/api/v1/kpis/",
        json={
            "name": f"KSC KPI {suffix}",
            "code": f"KSC{suffix.upper()}",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "manual",
            "scoring_direction": "higher_is_better",
        },
        headers=_auth(token),
    )
    assert kpi_resp.status_code == 201, kpi_resp.text
    kpi_id = kpi_resp.json()["id"]
    await client.patch(f"/api/v1/kpis/{kpi_id}/status", json={"status": "active"}, headers=_auth(token))

    cycle_resp = await client.post(
        "/api/v1/review-cycles/",
        json={
            "name": f"KSC Cycle {suffix}",
            "cycle_type": "annual",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        },
        headers=_auth(token),
    )
    assert cycle_resp.status_code == 201, cycle_resp.text
    cycle_id = cycle_resp.json()["id"]
    await client.patch(
        f"/api/v1/review-cycles/{cycle_id}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    me_resp = await client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    tgt_resp = await client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi_id,
            "review_cycle_id": cycle_id,
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": "100.00",
            "weight": "100.00",
        },
        headers=_auth(token),
    )
    assert tgt_resp.status_code == 201, tgt_resp.text
    target_id = tgt_resp.json()["id"]
    return kpi_id, target_id, cycle_id


async def test_assign_config_to_kpi(async_client: AsyncClient):
    """HR admin can assign a scoring config to a KPI."""
    token = await _register_and_login(async_client, _reg("assign_kpi"))
    kpi_id, _, _ = await _setup_kpi_and_target(async_client, token, "a_kpi")

    cfg_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("KPI-level Config"),
        headers=_auth(token),
    )
    config_id = cfg_resp.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/scoring-config",
        json={"scoring_config_id": config_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scoring_config_id"] == config_id


async def test_assign_config_to_target(async_client: AsyncClient):
    """HR admin can assign a scoring config to a locked target."""
    token = await _register_and_login(async_client, _reg("assign_tgt"))
    _, target_id, _ = await _setup_kpi_and_target(async_client, token, "a_tgt")

    cfg_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Target-level Config"),
        headers=_auth(token),
    )
    config_id = cfg_resp.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/targets/{target_id}/scoring-config",
        json={"scoring_config_id": config_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scoring_config_id"] == config_id


async def test_remove_config_from_kpi(async_client: AsyncClient):
    """Assigning null removes the scoring config from a KPI."""
    token = await _register_and_login(async_client, _reg("remove_kpi"))
    kpi_id, _, _ = await _setup_kpi_and_target(async_client, token, "rm_kpi")

    cfg_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("Removable Config"),
        headers=_auth(token),
    )
    config_id = cfg_resp.json()["id"]

    await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/scoring-config",
        json={"scoring_config_id": config_id},
        headers=_auth(token),
    )

    resp = await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/scoring-config",
        json={"scoring_config_id": None},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["scoring_config_id"] is None


async def test_get_effective_config_for_target_no_override(async_client: AsyncClient):
    """Target with no overrides returns cycle_default source."""
    token = await _register_and_login(async_client, _reg("eff_cfg"))
    _, target_id, _ = await _setup_kpi_and_target(async_client, token, "eff")

    resp = await async_client.get(
        f"/api/v1/targets/{target_id}/scoring-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "cycle_default"


async def test_get_effective_config_for_target_with_kpi_config(async_client: AsyncClient):
    """Target whose KPI has a config returns kpi_default source."""
    token = await _register_and_login(async_client, _reg("eff_kpi_cfg"))
    kpi_id, target_id, _ = await _setup_kpi_and_target(async_client, token, "eff_kpi")

    cfg_resp = await async_client.post(
        "/api/v1/scoring/configs",
        json=_make_config_payload("KPI Default Config"),
        headers=_auth(token),
    )
    config_id = cfg_resp.json()["id"]

    await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/scoring-config",
        json={"scoring_config_id": config_id},
        headers=_auth(token),
    )

    resp = await async_client.get(
        f"/api/v1/targets/{target_id}/scoring-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"].startswith("kpi_default:")
