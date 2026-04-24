"""
Tests for the Scoring module.

Covers:
  Part A — Calculator pure functions (no DB, no HTTP)
  Part B — Score config CRUD
  Part C — Scoring engine: compute, retrieve, adjust, finalise
  Part D — Calibration session workflow

All integration tests use the shared in-memory SQLite fixture from conftest.py.
Each test registers its own user+org via /auth/register to stay isolated.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.scoring.calculator import (
    compute_achievement_percentage,
    compute_composite_score,
    compute_score_distribution,
    compute_weighted_score,
    determine_rating,
    validate_adjustment,
)
from app.scoring.enums import RatingLabel
from app.kpis.enums import ScoringDirection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reg(suffix: str, role: str = "hr_admin") -> dict:
    return {
        "user": {
            "username": f"{suffix}_user",
            "email": f"{suffix}@scoring-test.com",
            "full_name": f"{suffix.title()} Scorer",
            "role": role,
            "password": "testpass123",
        },
        "organisation": {
            "name": f"{suffix.title()} Scoring Org",
            "slug": f"{suffix}-scoring-org",
        },
    }


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup_scored_cycle(
    client: AsyncClient,
    token: str,
    kpi_code: str,
    suffix: str,
    target_value: str = "100.00",
    actual_value: str = "90.00",
    weight: str = "100.00",
) -> dict:
    """
    Full setup: KPI → cycle (active) → target (locked) → actual (approved) → compute scores.

    Returns dict with:
        kpi_id, cycle_id, target_id, user_id, org_id,
        composite_id, kpi_score_id, composite_score (float)
    """
    # Create and activate KPI
    kpi_resp = await client.post(
        "/api/v1/kpis/",
        json={
            "name": f"Score KPI {suffix}",
            "code": kpi_code,
            "unit": "count",
            "frequency": "monthly",
            "data_source": "manual",
            "scoring_direction": "higher_is_better",
        },
        headers=_auth(token),
    )
    assert kpi_resp.status_code == 201, kpi_resp.text
    kpi_id = kpi_resp.json()["id"]
    await client.patch(f"/api/v1/kpis/{kpi_id}/status", json={"status": "active"}, headers=_auth(token))

    # Create and activate review cycle
    cycle_resp = await client.post(
        "/api/v1/review-cycles/",
        json={
            "name": f"Score Cycle {suffix}",
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
    org_id = me_resp.json()["organisation_id"]

    # Create target (automatically LOCKED in active cycle)
    tgt_resp = await client.post(
        "/api/v1/targets/",
        json={
            "kpi_id": kpi_id,
            "review_cycle_id": cycle_id,
            "assignee_type": "individual",
            "assignee_user_id": user_id,
            "target_value": target_value,
            "weight": weight,
        },
        headers=_auth(token),
    )
    assert tgt_resp.status_code == 201, tgt_resp.text
    assert tgt_resp.json()["status"] == "locked"
    target_id = tgt_resp.json()["id"]

    # Submit actual
    actual_resp = await client.post(
        "/api/v1/actuals/",
        json={
            "target_id": target_id,
            "period_date": "2025-06-01",
            "actual_value": actual_value,
        },
        headers=_auth(token),
    )
    assert actual_resp.status_code == 201, actual_resp.text
    actual_id = actual_resp.json()["id"]

    # Approve actual if not already approved (hr_admin can approve)
    if actual_resp.json()["status"] == "pending_approval":
        review_resp = await client.patch(
            f"/api/v1/actuals/{actual_id}/review",
            json={"action": "approve"},
            headers=_auth(token),
        )
        assert review_resp.status_code == 200, review_resp.text

    # Compute scores
    compute_resp = await client.post(
        f"/api/v1/scoring/compute/{cycle_id}",
        headers=_auth(token),
    )
    assert compute_resp.status_code == 200, compute_resp.text
    compute_data = compute_resp.json()
    assert compute_data["users_scored"] == 1
    assert len(compute_data["composite_scores"]) == 1
    composite_id = compute_data["composite_scores"][0]["id"]
    composite_score = float(compute_data["composite_scores"][0]["final_weighted_average"])

    # Get detailed score to find kpi_score_id
    detail_resp = await client.get(
        f"/api/v1/scoring/users/{user_id}/{cycle_id}",
        headers=_auth(token),
    )
    assert detail_resp.status_code == 200, detail_resp.text
    kpi_score_id = detail_resp.json()["kpi_scores"][0]["id"]

    return {
        "kpi_id": kpi_id,
        "cycle_id": cycle_id,
        "target_id": target_id,
        "user_id": user_id,
        "org_id": org_id,
        "composite_id": composite_id,
        "kpi_score_id": kpi_score_id,
        "composite_score": composite_score,
    }


# ===========================================================================
# PART A — Calculator pure functions
# ===========================================================================


class TestComputeAchievementPercentage:
    """Higher-is-better and lower-is-better scenarios, edge cases."""

    def test_higher_is_better_standard(self):
        """90 achieved out of 100 target → 90 %."""
        result = compute_achievement_percentage(
            Decimal("90"), Decimal("100"), ScoringDirection.HIGHER_IS_BETTER
        )
        assert result == Decimal("90.0000")

    def test_higher_is_better_over_target(self):
        """150 achieved out of 100 target → 150 %."""
        result = compute_achievement_percentage(
            Decimal("150"), Decimal("100"), ScoringDirection.HIGHER_IS_BETTER
        )
        assert result == Decimal("150.0000")

    def test_higher_is_better_cap_at_200(self):
        """250 % achievement is capped at 200 %."""
        result = compute_achievement_percentage(
            Decimal("250"), Decimal("100"), ScoringDirection.HIGHER_IS_BETTER
        )
        assert result == Decimal("200.0000")

    def test_lower_is_better_under_target_is_good(self):
        """Cost target 100, actual 80 → (100/80) × 100 = 125 % (beat the target)."""
        result = compute_achievement_percentage(
            Decimal("80"), Decimal("100"), ScoringDirection.LOWER_IS_BETTER
        )
        assert result == Decimal("125.0000")

    def test_lower_is_better_over_target_is_bad(self):
        """Cost target 100, actual 120 → (100/120) × 100 ≈ 83.33%."""
        result = compute_achievement_percentage(
            Decimal("120"), Decimal("100"), ScoringDirection.LOWER_IS_BETTER
        )
        assert float(result) == pytest.approx(83.3333, rel=1e-3)

    def test_zero_target_returns_zero(self):
        """Division by zero when target is 0 must return 0, not raise."""
        result = compute_achievement_percentage(
            Decimal("90"), Decimal("0"), ScoringDirection.HIGHER_IS_BETTER
        )
        assert result == Decimal("0.0000")

    def test_actual_below_minimum_returns_zero(self):
        """Actual below the hard floor → 0 % regardless of target."""
        result = compute_achievement_percentage(
            Decimal("30"),
            Decimal("100"),
            ScoringDirection.HIGHER_IS_BETTER,
            minimum_value=Decimal("50"),
        )
        assert result == Decimal("0.0000")

    def test_actual_at_minimum_scores_normally(self):
        """Actual exactly at the minimum floor → normal calculation applies."""
        result = compute_achievement_percentage(
            Decimal("50"),
            Decimal("100"),
            ScoringDirection.HIGHER_IS_BETTER,
            minimum_value=Decimal("50"),
        )
        assert result == Decimal("50.0000")


class TestComputeWeightedScore:
    def test_half_weight(self):
        """Achievement 100%, weight 50 → weighted = 50."""
        assert compute_weighted_score(Decimal("100"), Decimal("50")) == Decimal("50.0000")

    def test_full_weight(self):
        """Achievement 90%, weight 100 → weighted = 90."""
        assert compute_weighted_score(Decimal("90"), Decimal("100")) == Decimal("90.0000")

    def test_zero_weight(self):
        """Zero-weight KPI contributes nothing."""
        assert compute_weighted_score(Decimal("100"), Decimal("0")) == Decimal("0.0000")


class TestComputeCompositeScore:
    def test_single_kpi(self):
        """One KPI with weight=100, weighted_score=90 → composite=90."""
        scores = [{"weighted_score": Decimal("90"), "weight": Decimal("100")}]
        assert compute_composite_score(scores) == Decimal("90.0000")

    def test_two_kpis_equal_weight(self):
        """Two KPIs each with weight=50. KPI1: 90% achievement → w=45. KPI2: 70% → w=35."""
        scores = [
            {"weighted_score": Decimal("45"), "weight": Decimal("50")},  # 45 = 90 × 50/100
            {"weighted_score": Decimal("35"), "weight": Decimal("50")},  # 35 = 70 × 50/100
        ]
        # (45+35)/(50+50) × 100 = 80/100 × 100 = 80
        assert compute_composite_score(scores) == Decimal("80.0000")

    def test_missing_actual_penalises(self):
        """A KPI with 0 % achievement (no actual) reduces the composite."""
        scores = [
            {"weighted_score": Decimal("45"), "weight": Decimal("50")},  # 45 = 90 × 50/100
            {"weighted_score": Decimal("0"), "weight": Decimal("50")},   # no actual
        ]
        # (45+0)/(50+50) × 100 = 45/100 × 100 = 45
        assert compute_composite_score(scores) == Decimal("45.0000")

    def test_empty_scores_returns_zero(self):
        assert compute_composite_score([]) == Decimal("0.0000")


class TestDetermineRating:
    """Verify correct band assignment at and around each threshold."""

    _CONFIG = SimpleNamespace(
        exceptional_min=Decimal("120"),
        exceeds_min=Decimal("100"),
        meets_min=Decimal("80"),
        partially_meets_min=Decimal("60"),
        does_not_meet_min=Decimal("0"),
    )

    def test_exceptional(self):
        assert determine_rating(Decimal("130"), self._CONFIG) == RatingLabel.EXCEPTIONAL

    def test_exceptional_at_boundary(self):
        assert determine_rating(Decimal("120"), self._CONFIG) == RatingLabel.EXCEPTIONAL

    def test_exceeds_just_below_exceptional(self):
        assert determine_rating(Decimal("119.99"), self._CONFIG) == RatingLabel.EXCEEDS_EXPECTATIONS

    def test_meets_expectations(self):
        assert determine_rating(Decimal("90"), self._CONFIG) == RatingLabel.MEETS_EXPECTATIONS

    def test_partially_meets(self):
        assert determine_rating(Decimal("70"), self._CONFIG) == RatingLabel.PARTIALLY_MEETS

    def test_does_not_meet(self):
        assert determine_rating(Decimal("30"), self._CONFIG) == RatingLabel.DOES_NOT_MEET

    def test_zero_score_does_not_meet(self):
        assert determine_rating(Decimal("0"), self._CONFIG) == RatingLabel.DOES_NOT_MEET


class TestValidateAdjustment:
    def test_within_cap(self):
        assert validate_adjustment(Decimal("90"), Decimal("98"), Decimal("10")) is True

    def test_exactly_at_cap(self):
        assert validate_adjustment(Decimal("90"), Decimal("100"), Decimal("10")) is True

    def test_exceeds_cap(self):
        assert validate_adjustment(Decimal("90"), Decimal("105"), Decimal("10")) is False

    def test_negative_adjustment_within_cap(self):
        assert validate_adjustment(Decimal("90"), Decimal("82"), Decimal("10")) is True

    def test_negative_adjustment_exceeds_cap(self):
        assert validate_adjustment(Decimal("90"), Decimal("75"), Decimal("10")) is False


class TestComputeScoreDistribution:
    def test_basic_distribution(self):
        scores = [Decimal(v) for v in ["60", "70", "80", "90", "100"]]
        dist = compute_score_distribution(scores)
        assert dist["mean"] == Decimal("80.0000")
        assert dist["median"] == Decimal("80.0000")
        assert "p25" in dist["percentiles"]
        assert "p75" in dist["percentiles"]
        assert "rating_counts" in dist
        assert "rating_percentages" in dist

    def test_single_score(self):
        """Single score should not raise even with std_dev=0."""
        dist = compute_score_distribution([Decimal("95")])
        assert dist["mean"] == Decimal("95.0000")
        assert dist["std_dev"] == Decimal("0.0000")

    def test_empty_scores(self):
        """Empty list should return zeros without raising."""
        dist = compute_score_distribution([])
        assert dist["mean"] == Decimal("0.0000")
        assert all(v == 0 for v in dist["rating_counts"].values())


# ===========================================================================
# PART B — Score config CRUD
# ===========================================================================


@pytest.mark.asyncio
async def test_create_score_config(async_client: AsyncClient) -> None:
    """HR admin can create a score config for their cycle."""
    token = await _register_and_login(async_client, _reg("cfg_create"))

    # Create a cycle first
    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Config Test Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    assert cycle_resp.status_code == 201
    cycle_id = cycle_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/scoring/config",
        json={"review_cycle_id": cycle_id},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["review_cycle_id"] == cycle_id
    assert float(data["exceptional_min"]) == pytest.approx(120.0)
    assert data["requires_calibration"] is False


@pytest.mark.asyncio
async def test_create_score_config_duplicate_fails(async_client: AsyncClient) -> None:
    """Creating a second config for the same cycle returns 409."""
    token = await _register_and_login(async_client, _reg("cfg_dup"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Dup Config Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]

    await async_client.post("/api/v1/scoring/config", json={"review_cycle_id": cycle_id}, headers=_auth(token))

    resp = await async_client.post(
        "/api/v1/scoring/config",
        json={"review_cycle_id": cycle_id},
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_create_score_config_bad_thresholds(async_client: AsyncClient) -> None:
    """Thresholds not in strictly descending order → 400."""
    token = await _register_and_login(async_client, _reg("cfg_bad"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Bad Config Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/scoring/config",
        json={
            "review_cycle_id": cycle_id,
            "exceptional_min": "80.00",
            "exceeds_min": "100.00",  # wrong: should be less than exceptional
            "meets_min": "80.00",
            "partially_meets_min": "60.00",
            "does_not_meet_min": "0.00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_get_score_config(async_client: AsyncClient) -> None:
    """GET /scoring/config?cycle_id= returns the existing config."""
    token = await _register_and_login(async_client, _reg("cfg_get"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Get Config Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]
    await async_client.post("/api/v1/scoring/config", json={"review_cycle_id": cycle_id}, headers=_auth(token))

    resp = await async_client.get(
        f"/api/v1/scoring/config?cycle_id={cycle_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_cycle_id"] == cycle_id


@pytest.mark.asyncio
async def test_get_score_config_not_found(async_client: AsyncClient) -> None:
    """Requesting config for a cycle that has none → 404."""
    import uuid

    token = await _register_and_login(async_client, _reg("cfg_404"))
    resp = await async_client.get(
        f"/api/v1/scoring/config?cycle_id={uuid.uuid4()}",
        headers=_auth(token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_update_score_config(async_client: AsyncClient) -> None:
    """HR admin can update thresholds before scoring starts."""
    token = await _register_and_login(async_client, _reg("cfg_upd"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Update Config Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]
    create_resp = await async_client.post(
        "/api/v1/scoring/config",
        json={"review_cycle_id": cycle_id},
        headers=_auth(token),
    )
    config_id = create_resp.json()["id"]

    resp = await async_client.put(
        f"/api/v1/scoring/config/{config_id}",
        json={"requires_calibration": True, "max_adjustment_points": "5.00"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["requires_calibration"] is True
    assert float(data["max_adjustment_points"]) == pytest.approx(5.0)


# ===========================================================================
# PART C — Scoring engine
# ===========================================================================


@pytest.mark.asyncio
async def test_compute_scores_creates_composite(async_client: AsyncClient) -> None:
    """After compute, a composite score row is created with correct achievement."""
    token = await _register_and_login(async_client, _reg("eng_compute"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_COMPUTE_KPI", "eng_compute")

    # Achievement = 90/100 × 100 = 90%
    # Composite = 90 (single KPI, weight=100)
    assert ctx["composite_score"] == pytest.approx(90.0, abs=0.01)


@pytest.mark.asyncio
async def test_compute_scores_rerun_is_idempotent(async_client: AsyncClient) -> None:
    """Re-running compute on the same cycle returns the same result without duplicates."""
    token = await _register_and_login(async_client, _reg("eng_rerun"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_RERUN_KPI", "eng_rerun")

    # Run compute again
    resp2 = await async_client.post(
        f"/api/v1/scoring/compute/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp2.status_code == 200
    assert resp2.json()["users_scored"] == 1  # no duplicate user entries


@pytest.mark.asyncio
async def test_compute_scores_meets_expectations_rating(async_client: AsyncClient) -> None:
    """90% achievement falls in MEETS_EXPECTATIONS band (80–100)."""
    token = await _register_and_login(async_client, _reg("eng_rating"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_RATING_KPI", "eng_rating")

    detail_resp = await async_client.get(
        f"/api/v1/scoring/users/{ctx['user_id']}/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["rating"] == "meets_expectations"


@pytest.mark.asyncio
async def test_compute_scores_exceptional_rating(async_client: AsyncClient) -> None:
    """150% achievement falls in EXCEPTIONAL band (≥120)."""
    token = await _register_and_login(async_client, _reg("eng_except"))
    ctx = await _setup_scored_cycle(
        async_client, token, "ENG_EXCEPT_KPI", "eng_except",
        target_value="100.00", actual_value="150.00"
    )
    detail_resp = await async_client.get(
        f"/api/v1/scoring/users/{ctx['user_id']}/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert detail_resp.json()["rating"] == "exceptional"


@pytest.mark.asyncio
async def test_get_user_score_detail(async_client: AsyncClient) -> None:
    """Score detail endpoint returns KPI name, target value, and weight."""
    token = await _register_and_login(async_client, _reg("eng_detail"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_DETAIL_KPI", "eng_detail")

    resp = await async_client.get(
        f"/api/v1/scoring/users/{ctx['user_id']}/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == ctx["composite_id"]
    assert len(data["kpi_scores"]) == 1
    kpi = data["kpi_scores"][0]
    assert kpi["kpi_code"] == "ENG_DETAIL_KPI"
    assert float(kpi["target_value"]) == pytest.approx(100.0)
    assert float(kpi["weight"]) == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_get_user_score_not_found_raises_404(async_client: AsyncClient) -> None:
    """Requesting scores for a user with no compute run → 404."""
    import uuid

    token = await _register_and_login(async_client, _reg("eng_no_score"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "No Score Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]
    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.get(
        f"/api/v1/scoring/users/{user_id}/{cycle_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_team_scores_empty_team(async_client: AsyncClient) -> None:
    """Manager/hr_admin with no direct reports returns empty list."""
    token = await _register_and_login(async_client, _reg("eng_team_empty"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_TEAM_EMPTY_KPI", "eng_team_empty")

    resp = await async_client.get(
        f"/api/v1/scoring/team/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_org_distribution(async_client: AsyncClient) -> None:
    """Org distribution returns statistical keys after compute."""
    token = await _register_and_login(async_client, _reg("eng_org_dist"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_ORG_DIST_KPI", "eng_org_dist")

    resp = await async_client.get(
        f"/api/v1/scoring/org/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "mean" in data
    assert "median" in data
    assert "total_employees" in data
    assert data["total_employees"] == 1


@pytest.mark.asyncio
async def test_manager_adjustment_within_cap(async_client: AsyncClient) -> None:
    """Manager adjusts KPI score by 5 points (≤ 10 cap). Composite updates."""
    token = await _register_and_login(async_client, _reg("eng_adj_ok"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_ADJ_OK_KPI", "eng_adj_ok")

    # Adjust from ~90 to 95 (5 points)
    resp = await async_client.patch(
        f"/api/v1/scoring/kpi-score/{ctx['kpi_score_id']}/adjust",
        json={
            "new_score": "95.00",
            "reason": "Employee demonstrated exceptional effort in Q2 deliverables.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    # Composite should now reflect the adjusted KPI score
    assert float(resp.json()["final_weighted_average"]) == pytest.approx(95.0, abs=0.01)


@pytest.mark.asyncio
async def test_manager_adjustment_exceeds_cap(async_client: AsyncClient) -> None:
    """Adjustment exceeding max_adjustment_points cap returns 400."""
    token = await _register_and_login(async_client, _reg("eng_adj_cap"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_ADJ_CAP_KPI", "eng_adj_cap")

    # Try to adjust from ~90 to 110 (20 points > 10 cap)
    resp = await async_client.patch(
        f"/api/v1/scoring/kpi-score/{ctx['kpi_score_id']}/adjust",
        json={
            "new_score": "110.00",
            "reason": "Trying to adjust too much without proper justification.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_manager_adjustment_creates_audit_record(async_client: AsyncClient) -> None:
    """An accepted adjustment must create a ScoreAdjustment audit record."""
    token = await _register_and_login(async_client, _reg("eng_adj_audit"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_ADJ_AUDIT_KPI", "eng_adj_audit")

    await async_client.patch(
        f"/api/v1/scoring/kpi-score/{ctx['kpi_score_id']}/adjust",
        json={
            "new_score": "93.00",
            "reason": "Performance review board approved the qualitative uplift.",
        },
        headers=_auth(token),
    )

    detail_resp = await async_client.get(
        f"/api/v1/scoring/users/{ctx['user_id']}/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    kpi = detail_resp.json()["kpi_scores"][0]
    assert len(kpi["adjustments"]) == 1
    adj = kpi["adjustments"][0]
    assert adj["before_value"] is not None
    assert float(adj["after_value"]) == pytest.approx(93.0, abs=0.01)
    assert adj["adjustment_type"] == "manager_review"


@pytest.mark.asyncio
async def test_composite_direct_adjustment(async_client: AsyncClient) -> None:
    """HR admin can directly adjust the composite score."""
    token = await _register_and_login(async_client, _reg("eng_comp_adj"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_COMP_ADJ_KPI", "eng_comp_adj")

    resp = await async_client.patch(
        f"/api/v1/scoring/composite/{ctx['composite_id']}/adjust",
        json={
            "new_weighted_average": "88.00",
            "reason": "Calibration session agreed on adjusted composite score.",
            "manager_comment": "Strong performer with exceptional soft skills.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert float(data["final_weighted_average"]) == pytest.approx(88.0, abs=0.01)
    assert data["manager_comment"] == "Strong performer with exceptional soft skills."


@pytest.mark.asyncio
async def test_finalise_scores_requires_closed_cycle(async_client: AsyncClient) -> None:
    """Finalising scores on an ACTIVE cycle returns 400."""
    token = await _register_and_login(async_client, _reg("eng_fin_active"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_FIN_ACTIVE_KPI", "eng_fin_active")

    resp = await async_client.post(
        f"/api/v1/scoring/finalise/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_finalise_scores_on_closed_cycle(async_client: AsyncClient) -> None:
    """Finalising on a CLOSED cycle locks all scores and returns count."""
    token = await _register_and_login(async_client, _reg("eng_fin_closed"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_FIN_CLOSED_KPI", "eng_fin_closed")

    # Close the cycle
    await async_client.patch(
        f"/api/v1/review-cycles/{ctx['cycle_id']}/status",
        json={"status": "closed"},
        headers=_auth(token),
    )

    resp = await async_client.post(
        f"/api/v1/scoring/finalise/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scores_finalised"] == 1


@pytest.mark.asyncio
async def test_cannot_adjust_finalised_score(async_client: AsyncClient) -> None:
    """Adjusting a FINAL KPI score is forbidden (403)."""
    token = await _register_and_login(async_client, _reg("eng_fin_adj"))
    ctx = await _setup_scored_cycle(async_client, token, "ENG_FIN_ADJ_KPI", "eng_fin_adj")

    await async_client.patch(
        f"/api/v1/review-cycles/{ctx['cycle_id']}/status",
        json={"status": "closed"},
        headers=_auth(token),
    )
    await async_client.post(
        f"/api/v1/scoring/finalise/{ctx['cycle_id']}",
        headers=_auth(token),
    )

    resp = await async_client.patch(
        f"/api/v1/scoring/kpi-score/{ctx['kpi_score_id']}/adjust",
        json={
            "new_score": "95.00",
            "reason": "Attempting to adjust after finalisation should fail.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 403, resp.text


# ===========================================================================
# PART D — Calibration
# ===========================================================================


@pytest.mark.asyncio
async def test_create_calibration_session(async_client: AsyncClient) -> None:
    """HR admin can create a calibration session after compute has run."""
    token = await _register_and_login(async_client, _reg("cal_create"))
    ctx = await _setup_scored_cycle(async_client, token, "CAL_CREATE_KPI", "cal_create")

    resp = await async_client.post(
        "/api/v1/scoring/calibration",
        json={
            "review_cycle_id": ctx["cycle_id"],
            "name": "Q4 Calibration — Engineering",
            "scope_user_ids": [ctx["user_id"]],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Q4 Calibration — Engineering"
    assert data["status"] == "open"


@pytest.mark.asyncio
async def test_calibration_session_requires_computed_scores(async_client: AsyncClient) -> None:
    """Creating a calibration session for a user without scores → 400."""
    import uuid

    token = await _register_and_login(async_client, _reg("cal_no_scores"))

    cycle_resp = await async_client.post(
        "/api/v1/review-cycles/",
        json={"name": "Cal No Scores Cycle", "cycle_type": "annual",
              "start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth(token),
    )
    cycle_id = cycle_resp.json()["id"]
    me_resp = await async_client.get("/api/v1/users/me", headers=_auth(token))
    user_id = me_resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/scoring/calibration",
        json={
            "review_cycle_id": cycle_id,
            "name": "Cal Without Scores",
            "scope_user_ids": [user_id],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_list_calibration_sessions(async_client: AsyncClient) -> None:
    """Created sessions are visible via list endpoint."""
    token = await _register_and_login(async_client, _reg("cal_list"))
    ctx = await _setup_scored_cycle(async_client, token, "CAL_LIST_KPI", "cal_list")

    await async_client.post(
        "/api/v1/scoring/calibration",
        json={
            "review_cycle_id": ctx["cycle_id"],
            "name": "List Test Session",
            "scope_user_ids": [ctx["user_id"]],
        },
        headers=_auth(token),
    )

    resp = await async_client.get(
        f"/api/v1/scoring/calibration?cycle_id={ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    sessions = resp.json()
    assert len(sessions) >= 1
    assert sessions[0]["name"] == "List Test Session"


@pytest.mark.asyncio
async def test_calibration_update_score_and_complete(async_client: AsyncClient) -> None:
    """Calibration score update moves status to in_progress; complete → completed."""
    token = await _register_and_login(async_client, _reg("cal_workflow"))
    ctx = await _setup_scored_cycle(async_client, token, "CAL_WORKFLOW_KPI", "cal_workflow")

    # Create session
    session_resp = await async_client.post(
        "/api/v1/scoring/calibration",
        json={
            "review_cycle_id": ctx["cycle_id"],
            "name": "Workflow Session",
            "scope_user_ids": [ctx["user_id"]],
        },
        headers=_auth(token),
    )
    session_id = session_resp.json()["id"]

    # Update a score during calibration
    update_resp = await async_client.patch(
        f"/api/v1/scoring/calibration/{session_id}/scores/{ctx['composite_id']}",
        json={"new_score": "87.00", "note": "Agreed calibrated score after discussion"},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200, update_resp.text
    assert float(update_resp.json()["final_weighted_average"]) == pytest.approx(87.0, abs=0.01)

    # Verify session is IN_PROGRESS
    session_detail = await async_client.get(
        f"/api/v1/scoring/calibration/{session_id}",
        headers=_auth(token),
    )
    assert session_detail.json()["status"] == "in_progress"

    # Complete the session
    complete_resp = await async_client.post(
        f"/api/v1/scoring/calibration/{session_id}/complete",
        headers=_auth(token),
    )
    assert complete_resp.status_code == 200, complete_resp.text
    assert complete_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_finalise_requires_calibration_when_configured(async_client: AsyncClient) -> None:
    """If requires_calibration=True and no completed session, finalise returns 400."""
    token = await _register_and_login(async_client, _reg("cal_reqd"))
    ctx = await _setup_scored_cycle(async_client, token, "CAL_REQD_KPI", "cal_reqd")

    # Create config that requires calibration
    await async_client.post(
        "/api/v1/scoring/config",
        json={"review_cycle_id": ctx["cycle_id"], "requires_calibration": True},
        headers=_auth(token),
    )

    # Close the cycle
    await async_client.patch(
        f"/api/v1/review-cycles/{ctx['cycle_id']}/status",
        json={"status": "closed"},
        headers=_auth(token),
    )

    # Try to finalise without a completed calibration session
    resp = await async_client.post(
        f"/api/v1/scoring/finalise/{ctx['cycle_id']}",
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert "calibration" in resp.json()["detail"].lower()
