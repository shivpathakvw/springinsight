"""Scoring logic — compute aggregate scores from findings."""

from __future__ import annotations


# Deduction per finding severity within a dimension
SEVERITY_DEDUCTION = {"CRITICAL": 25, "HIGH": 10, "MEDIUM": 4, "LOW": 1, "INFO": 0}

# Category → dimension mapping
CATEGORY_TO_DIM: dict[str, str] = {
    # Security
    "Security": "security",
    "CVE": "security",
    "Crypto": "security",
    "Authentication": "security",
    "Authorization": "security",
    # Code Quality
    "Code Quality": "code_quality",
    "Dead Code": "code_quality",
    "Concurrency": "code_quality",
    "Performance": "code_quality",
    # Architecture
    "Architecture": "architecture",
    "Layering": "architecture",
    "SOLID": "architecture",
    "Dependency": "architecture",
    # API Design
    "API Design": "api_design",
    "REST": "api_design",
    # Test Coverage
    "Testing": "test_coverage",
    "LLD": "test_coverage",
    # Production Readiness
    "Config": "production_readiness",
    "Infrastructure": "production_readiness",
    "License": "production_readiness",
    "Database": "production_readiness",
}

# Weight of each dimension in the overall score (must sum to 1.0)
DIMENSION_WEIGHTS: dict[str, float] = {
    "security":             0.30,
    "code_quality":         0.20,
    "architecture":         0.15,
    "api_design":           0.15,
    "production_readiness": 0.12,
    "test_coverage":        0.08,
}


def calculate_scores(findings: list[dict]) -> dict[str, int]:
    """Compute scores (0–100) per dimension from a list of findings.

    Each dimension starts at 100 and loses points per finding in its category.
    Overall = weighted average of all dimensions.
    Higher = better.
    """
    DIMENSIONS = list(DIMENSION_WEIGHTS.keys())

    if not findings:
        return {"overall": 100, **{d: 100 for d in DIMENSIONS}}

    # Accumulate deductions per dimension
    deductions: dict[str, int] = {d: 0 for d in DIMENSIONS}

    for finding in findings:
        severity = finding.get("severity", "LOW").upper()
        category = finding.get("category", "")
        points = SEVERITY_DEDUCTION.get(severity, 0)

        dim = CATEGORY_TO_DIM.get(category)
        if dim and dim in deductions:
            deductions[dim] += points
        else:
            # Uncategorised findings lightly penalise all dimensions
            for d in DIMENSIONS:
                deductions[d] += max(1, points // len(DIMENSIONS))

    # Clamp each dimension to [0, 100]
    dim_scores = {d: max(0, min(100, 100 - deductions[d])) for d in DIMENSIONS}

    # Overall = weighted average
    overall = round(sum(dim_scores[d] * DIMENSION_WEIGHTS[d] for d in DIMENSIONS))

    return {"overall": overall, **dim_scores}
