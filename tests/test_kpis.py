"""
Tests for the KPI module: categories, tags, KPI CRUD, formula engine,
status workflow, templates, and history.

Uses the same in-memory SQLite test database set up in conftest.py.
All tests requiring the API first register a user + org via /auth/register.
"""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HR_ADMIN_PAYLOAD = {
    "user": {
        "username": "kpi_hr_admin",
        "email": "kpi_hradmin@testcorp.com",
        "full_name": "KPI HR Admin",
        "role": "hr_admin",
        "password": "testpass123",
    },
    "organisation": {
        "name": "KPI Test Corp",
        "slug": "kpi-test-corp",
    },
}

_MANAGER_PAYLOAD = {
    "user": {
        "username": "kpi_manager",
        "email": "kpi_manager@testcorp.com",
        "full_name": "KPI Manager",
        "role": "manager",
        "password": "testpass123",
    },
    "organisation": {
        "name": "KPI Manager Org",
        "slug": "kpi-manager-org",
    },
}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    """Register a user+org and return the access token."""
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# test_create_kpi_manual
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_manual(async_client: AsyncClient) -> None:
    """Creating a basic manual KPI should return 201 with all fields."""
    token = await _register_and_login(async_client, _HR_ADMIN_PAYLOAD)

    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Monthly Revenue",
            "code": "MONTHLY_REVENUE",
            "unit": "currency",
            "frequency": "monthly",
            "data_source": "manual",
            "scoring_direction": "higher_is_better",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["code"] == "MONTHLY_REVENUE"
    assert data["status"] == "draft"
    assert data["version"] == 1
    assert data["data_source"] == "manual"


# ---------------------------------------------------------------------------
# test_create_kpi_duplicate_code_fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_duplicate_code_fails(async_client: AsyncClient) -> None:
    """Creating a KPI with a duplicate code within the same org should return 409."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "dup_hr",
                "email": "dup_hr@testcorp.com",
                "full_name": "Dup HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {
                "name": "Dup Org",
                "slug": "dup-org",
            },
        },
    )

    kpi_body = {
        "name": "Win Rate",
        "code": "WIN_RATE",
        "unit": "percentage",
        "frequency": "monthly",
        "data_source": "manual",
    }
    resp1 = await async_client.post("/api/v1/kpis/", json=kpi_body, headers=_auth(token))
    assert resp1.status_code == 201, resp1.text

    resp2 = await async_client.post("/api/v1/kpis/", json=kpi_body, headers=_auth(token))
    assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# test_create_kpi_formula_valid
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_formula_valid(async_client: AsyncClient) -> None:
    """Creating a formula KPI that references an existing KPI code should succeed."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "formula_hr",
                "email": "formula_hr@corp.com",
                "full_name": "Formula HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Formula Org", "slug": "formula-org"},
        },
    )

    # Create base KPIs
    await async_client.post(
        "/api/v1/kpis/",
        json={"name": "Revenue", "code": "REVENUE", "unit": "currency", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )
    await async_client.post(
        "/api/v1/kpis/",
        json={"name": "Cost", "code": "COST", "unit": "currency", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )

    # Create formula KPI
    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Gross Profit Margin",
            "code": "GROSS_PROFIT_MARGIN",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "formula",
            "formula_expression": "(REVENUE - COST) / REVENUE * 100",
            "scoring_direction": "higher_is_better",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["data_source"] == "formula"
    assert data["formula_expression"] == "(REVENUE - COST) / REVENUE * 100"


# ---------------------------------------------------------------------------
# test_create_kpi_formula_invalid_syntax
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_formula_invalid_syntax(async_client: AsyncClient) -> None:
    """A formula with invalid syntax should be rejected at the validation layer."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "syntax_hr",
                "email": "syntax_hr@corp.com",
                "full_name": "Syntax HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Syntax Org", "slug": "syntax-org"},
        },
    )

    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Bad KPI",
            "code": "BAD_KPI",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "formula",
            "formula_expression": "REVENUE +* COST",  # invalid syntax
        },
        headers=_auth(token),
    )
    # Validation error from the formula parser
    assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# test_create_kpi_formula_circular_dep_fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_formula_circular_dep_fails(async_client: AsyncClient) -> None:
    """A formula that creates a circular dependency should be rejected with 400."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "circ_hr",
                "email": "circ_hr@corp.com",
                "full_name": "Circular HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Circular Org", "slug": "circular-org"},
        },
    )

    # Create KPI A — manual base
    resp_a = await async_client.post(
        "/api/v1/kpis/",
        json={"name": "KPI Alpha", "code": "KPI_A", "unit": "count", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )
    assert resp_a.status_code == 201

    # Create KPI B that depends on A
    resp_b = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "KPI Beta",
            "code": "KPI_B",
            "unit": "count",
            "frequency": "monthly",
            "data_source": "formula",
            "formula_expression": "KPI_A * 2",
        },
        headers=_auth(token),
    )
    assert resp_b.status_code == 201

    # Attempt to update A to depend on B (would create A → B → A cycle)
    kpi_a_id = resp_a.json()["id"]
    resp_update = await async_client.put(
        f"/api/v1/kpis/{kpi_a_id}",
        json={
            "formula_expression": "KPI_B + 1",
            "change_summary": "Circular test",
        },
        headers=_auth(token),
    )
    # KPI A is currently manual — you can't add formula_expression to it via update
    # (data_source doesn't change), but it should fail with 400 due to circular dep check
    assert resp_update.status_code in (400, 422), resp_update.text


# ---------------------------------------------------------------------------
# test_create_kpi_formula_missing_ref_fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_kpi_formula_missing_ref_fails(async_client: AsyncClient) -> None:
    """A formula that references a non-existent KPI code should fail."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "missing_hr",
                "email": "missing_hr@corp.com",
                "full_name": "Missing HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Missing Org", "slug": "missing-org"},
        },
    )

    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Bad Formula",
            "code": "BAD_FORMULA",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "formula",
            "formula_expression": "NONEXISTENT_KPI * 100",
        },
        headers=_auth(token),
    )
    assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# test_kpi_status_workflow_draft_to_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kpi_status_workflow_draft_to_active(async_client: AsyncClient) -> None:
    """hr_admin should be able to move a KPI from DRAFT directly to ACTIVE."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "status_hr",
                "email": "status_hr@corp.com",
                "full_name": "Status HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Status Org", "slug": "status-org"},
        },
    )

    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Revenue Growth",
            "code": "REVENUE_GROWTH",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "manual",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    kpi_id = resp.json()["id"]

    # DRAFT → ACTIVE (hr_admin can skip PENDING_APPROVAL)
    status_resp = await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/status",
        json={"status": "active"},
        headers=_auth(token),
    )
    assert status_resp.status_code == 200, status_resp.text
    assert status_resp.json()["status"] == "active"


# ---------------------------------------------------------------------------
# test_kpi_status_invalid_transition_fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kpi_status_invalid_transition_fails(async_client: AsyncClient) -> None:
    """An illegal status transition (e.g., DRAFT → ARCHIVED) should return 400."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "invalid_status_hr",
                "email": "invalid_status_hr@corp.com",
                "full_name": "Invalid HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Invalid Status Org", "slug": "invalid-status-org"},
        },
    )

    resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Defect Rate",
            "code": "DEFECT_RATE",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "manual",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    kpi_id = resp.json()["id"]

    # Attempt invalid transition: DRAFT → ARCHIVED
    bad_resp = await async_client.patch(
        f"/api/v1/kpis/{kpi_id}/status",
        json={"status": "archived"},
        headers=_auth(token),
    )
    assert bad_resp.status_code == 400


# ---------------------------------------------------------------------------
# test_list_kpis_pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_kpis_pagination(async_client: AsyncClient) -> None:
    """Listing KPIs should return a paginated response with correct totals."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "page_hr",
                "email": "page_hr@corp.com",
                "full_name": "Page HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Page Org", "slug": "page-org"},
        },
    )

    # Create 3 KPIs
    for i in range(1, 4):
        r = await async_client.post(
            "/api/v1/kpis/",
            json={
                "name": f"KPI {i}",
                "code": f"KPI_{i:03d}",
                "unit": "count",
                "frequency": "monthly",
                "data_source": "manual",
            },
            headers=_auth(token),
        )
        assert r.status_code == 201

    resp = await async_client.get("/api/v1/kpis/?page=1&size=2", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["pages"] == 2


# ---------------------------------------------------------------------------
# test_list_kpis_filter_by_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_kpis_filter_by_status(async_client: AsyncClient) -> None:
    """Filtering by status=active should only return active KPIs."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "filter_hr",
                "email": "filter_hr@corp.com",
                "full_name": "Filter HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Filter Org", "slug": "filter-org"},
        },
    )

    # Create two KPIs
    r1 = await async_client.post(
        "/api/v1/kpis/",
        json={"name": "Active KPI", "code": "ACTIVE_KPI", "unit": "count", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )
    r2 = await async_client.post(
        "/api/v1/kpis/",
        json={"name": "Draft KPI", "code": "DRAFT_KPI", "unit": "count", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    # Activate one
    await async_client.patch(
        f"/api/v1/kpis/{r1.json()['id']}/status",
        json={"status": "active"},
        headers=_auth(token),
    )

    resp = await async_client.get("/api/v1/kpis/?status=active", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "ACTIVE_KPI"


# ---------------------------------------------------------------------------
# test_list_kpis_filter_by_department
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_kpis_filter_by_department(async_client: AsyncClient) -> None:
    """Filtering by department should return only KPIs in that department's category."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "dept_hr",
                "email": "dept_hr@corp.com",
                "full_name": "Dept HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Dept Org", "slug": "dept-org"},
        },
    )

    # Create sales category
    cat_resp = await async_client.post(
        "/api/v1/kpis/categories/",
        json={"name": "Sales KPIs", "department": "sales", "colour_hex": "#FF5733"},
        headers=_auth(token),
    )
    assert cat_resp.status_code == 201
    cat_id = cat_resp.json()["id"]

    # Create a KPI in that category
    await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Win Rate",
            "code": "DEPT_WIN_RATE",
            "unit": "percentage",
            "frequency": "monthly",
            "data_source": "manual",
            "category_id": cat_id,
        },
        headers=_auth(token),
    )

    resp = await async_client.get("/api/v1/kpis/?department=sales", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(item["code"] == "DEPT_WIN_RATE" for item in data["items"])


# ---------------------------------------------------------------------------
# test_update_kpi_increments_version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_kpi_increments_version(async_client: AsyncClient) -> None:
    """Updating a KPI should increment its version number."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "version_hr",
                "email": "version_hr@corp.com",
                "full_name": "Version HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Version Org", "slug": "version-org"},
        },
    )

    create_resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "Version KPI",
            "code": "VERSION_KPI",
            "unit": "count",
            "frequency": "monthly",
            "data_source": "manual",
        },
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    kpi_id = create_resp.json()["id"]
    assert create_resp.json()["version"] == 1

    update_resp = await async_client.put(
        f"/api/v1/kpis/{kpi_id}",
        json={"name": "Version KPI Updated"},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2


# ---------------------------------------------------------------------------
# test_update_kpi_saves_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_kpi_saves_history(async_client: AsyncClient) -> None:
    """Updating a KPI should create a history entry containing the old snapshot."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "history_hr",
                "email": "history_hr@corp.com",
                "full_name": "History HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "History Org", "slug": "history-org"},
        },
    )

    create_resp = await async_client.post(
        "/api/v1/kpis/",
        json={
            "name": "History KPI",
            "code": "HISTORY_KPI",
            "unit": "count",
            "frequency": "monthly",
            "data_source": "manual",
        },
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    kpi_id = create_resp.json()["id"]

    await async_client.put(
        f"/api/v1/kpis/{kpi_id}",
        json={"name": "History KPI v2"},
        headers=_auth(token),
    )

    history_resp = await async_client.get(
        f"/api/v1/kpis/{kpi_id}/history", headers=_auth(token)
    )
    assert history_resp.status_code == 200
    history = history_resp.json()
    # Version 1 = initial creation, version 2 = after update
    assert len(history) == 2
    assert history[0]["version"] == 1
    assert history[0]["change_summary"] == "Initial creation"
    assert history[1]["version"] == 2


# ---------------------------------------------------------------------------
# test_clone_from_template
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clone_from_template(async_client: AsyncClient) -> None:
    """Cloning a system template should create a new KPI in DRAFT status."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "clone_hr",
                "email": "clone_hr@corp.com",
                "full_name": "Clone HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Clone Org", "slug": "clone-org"},
        },
    )

    # Fetch templates
    templates_resp = await async_client.get("/api/v1/kpis/templates/", headers=_auth(token))
    assert templates_resp.status_code == 200
    templates = templates_resp.json()

    if not templates:
        pytest.skip("No templates seeded — run with DEBUG=True")

    template_id = templates[0]["id"]

    clone_resp = await async_client.post(
        "/api/v1/kpis/templates/clone/",
        json={"template_id": template_id, "code": "CLONED_KPI"},
        headers=_auth(token),
    )
    assert clone_resp.status_code == 201, clone_resp.text
    data = clone_resp.json()
    assert data["code"] == "CLONED_KPI"
    assert data["status"] == "draft"


# ---------------------------------------------------------------------------
# test_validate_formula_endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_formula_endpoint(async_client: AsyncClient) -> None:
    """The validate-formula endpoint should detect syntax errors and missing refs."""
    token = await _register_and_login(
        async_client,
        {
            "user": {
                "username": "valformula_hr",
                "email": "valformula_hr@corp.com",
                "full_name": "Val Formula HR",
                "role": "hr_admin",
                "password": "testpass123",
            },
            "organisation": {"name": "Val Formula Org", "slug": "val-formula-org"},
        },
    )

    # Create a base KPI
    await async_client.post(
        "/api/v1/kpis/",
        json={"name": "Base", "code": "BASE_KPI", "unit": "count", "frequency": "monthly", "data_source": "manual"},
        headers=_auth(token),
    )

    # Valid formula
    resp_valid = await async_client.post(
        "/api/v1/kpis/validate-formula",
        json={"expression": "BASE_KPI * 100"},
        headers=_auth(token),
    )
    assert resp_valid.status_code == 200
    assert resp_valid.json()["valid"] is True
    assert "BASE_KPI" in resp_valid.json()["referenced_codes"]

    # Invalid expression (references a non-existent KPI)
    resp_invalid = await async_client.post(
        "/api/v1/kpis/validate-formula",
        json={"expression": "GHOST_KPI + BASE_KPI"},
        headers=_auth(token),
    )
    assert resp_invalid.status_code == 200
    assert resp_invalid.json()["valid"] is False
    assert len(resp_invalid.json()["errors"]) > 0
