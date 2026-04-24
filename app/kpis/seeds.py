"""
Seed script for KPI templates.

Called from app.main lifespan when settings.DEBUG=True and the templates table is empty.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kpis.enums import (
    DepartmentCategory,
    MeasurementFrequency,
    MeasurementUnit,
    ScoringDirection,
)
from app.kpis.models import KPITemplate

_TEMPLATES = [
    # --- Sales ---
    {
        "name": "Monthly Revenue Growth",
        "description": "Measures the percentage growth in revenue month over month.",
        "department": DepartmentCategory.SALES,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["revenue", "growth", "sales"],
    },
    {
        "name": "Sales Win Rate",
        "description": "Percentage of sales opportunities that result in a closed deal.",
        "department": DepartmentCategory.SALES,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["sales", "win-rate", "pipeline"],
    },
    {
        "name": "Average Deal Size",
        "description": "Average monetary value of closed deals.",
        "department": DepartmentCategory.SALES,
        "unit": MeasurementUnit.CURRENCY,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["sales", "deal", "revenue"],
    },
    {
        "name": "Customer Acquisition Cost",
        "description": "Total cost to acquire a new customer, including marketing and sales expenses.",
        "department": DepartmentCategory.SALES,
        "unit": MeasurementUnit.CURRENCY,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.LOWER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["sales", "cac", "cost"],
    },
    # --- HR ---
    {
        "name": "Employee Turnover Rate",
        "description": "Percentage of employees who left the organisation during the period.",
        "department": DepartmentCategory.HR,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.QUARTERLY,
        "scoring_direction": ScoringDirection.LOWER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["hr", "retention", "turnover"],
    },
    {
        "name": "Time to Hire",
        "description": "Average number of hours from job posting to offer acceptance.",
        "department": DepartmentCategory.HR,
        "unit": MeasurementUnit.DURATION_HOURS,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.LOWER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["hr", "recruitment", "hiring"],
    },
    {
        "name": "Employee Satisfaction Score",
        "description": "Overall employee satisfaction measured via surveys (0–10 scale).",
        "department": DepartmentCategory.HR,
        "unit": MeasurementUnit.SCORE,
        "frequency": MeasurementFrequency.QUARTERLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["hr", "engagement", "satisfaction"],
    },
    # --- Finance ---
    {
        "name": "Gross Profit Margin",
        "description": "Percentage of revenue remaining after cost of goods sold.",
        "department": DepartmentCategory.FINANCE,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["finance", "profit", "margin"],
    },
    {
        "name": "Operating Cash Flow",
        "description": "Net cash generated from core business operations.",
        "department": DepartmentCategory.FINANCE,
        "unit": MeasurementUnit.CURRENCY,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["finance", "cashflow", "operations"],
    },
    # --- Operations ---
    {
        "name": "Defect Rate",
        "description": "Percentage of products or outputs that do not meet quality standards.",
        "department": DepartmentCategory.OPERATIONS,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.LOWER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["operations", "quality", "defects"],
    },
    {
        "name": "On-Time Delivery Rate",
        "description": "Percentage of deliveries completed on or before the scheduled date.",
        "department": DepartmentCategory.OPERATIONS,
        "unit": MeasurementUnit.PERCENTAGE,
        "frequency": MeasurementFrequency.MONTHLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["operations", "delivery", "logistics"],
    },
    # --- Engineering ---
    {
        "name": "Sprint Velocity",
        "description": "Number of story points completed per sprint.",
        "department": DepartmentCategory.ENGINEERING,
        "unit": MeasurementUnit.COUNT,
        "frequency": MeasurementFrequency.WEEKLY,
        "scoring_direction": ScoringDirection.HIGHER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["engineering", "agile", "velocity"],
    },
    {
        "name": "Bug Resolution Time",
        "description": "Average hours from bug report to verified fix.",
        "department": DepartmentCategory.ENGINEERING,
        "unit": MeasurementUnit.DURATION_HOURS,
        "frequency": MeasurementFrequency.WEEKLY,
        "scoring_direction": ScoringDirection.LOWER_IS_BETTER,
        "suggested_formula": None,
        "tags": ["engineering", "bugs", "quality"],
    },
]


async def seed_kpi_templates(db: AsyncSession) -> None:
    """Insert pre-built KPI templates if the templates table is empty."""
    count_result = await db.execute(select(func.count()).select_from(KPITemplate))
    count = count_result.scalar_one()
    if count > 0:
        return

    for tmpl_data in _TEMPLATES:
        template = KPITemplate(
            name=tmpl_data["name"],
            description=tmpl_data["description"],
            department=tmpl_data["department"],
            unit=tmpl_data["unit"],
            frequency=tmpl_data["frequency"],
            scoring_direction=tmpl_data["scoring_direction"],
            suggested_formula=tmpl_data.get("suggested_formula"),
            tags=tmpl_data["tags"],
            usage_count=0,
            is_active=True,
        )
        db.add(template)

    await db.commit()
