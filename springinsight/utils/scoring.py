"""Scoring logic — compute aggregate scores from findings."""

from __future__ import annotations


def calculate_scores(findings: list[dict]) -> dict[str, int]:
    """Compute scores (0-100) from a list of finding dicts.

    Higher score = better. Starts at 100, deducts per finding by severity.
    Weights are different per score dimension.
    """
    if not findings:
        return {
            "overall": 100, "security": 100, "code_quality": 100,
            "architecture": 100, "api_design": 100,
            "test_coverage": 100, "production_readiness": 100,
        }

    # Deduction weights per severity
    SEVERITY_WEIGHT = {"CRITICAL": 20, "HIGH": 8, "MEDIUM": 3, "LOW": 1, "INFO": 0}

    # Category → score dimension mapping
    CAT_TO_DIM = {
        "Security": "security",
        "CVE": "security",
        "Crypto": "security",
        "Authentication": "security",
        "Code Quality": "code_quality",
        "Dead Code": "code_quality",
        "Architecture": "architecture",
        "Layering": "architecture",
        "SOLID": "architecture",
        "API Design": "api_design",
        "REST": "api_design",
        "Testing": "test_coverage",
        "Config": "production_readiness",
        "Infrastructure": "production_readiness",
        "License": "production_readiness",
    }

    deductions: dict[str, int] = {
        "overall": 0, "security": 0, "code_quality": 0,
        "architecture": 0, "api_design": 0,
        "test_coverage": 0, "production_readiness": 0,
    }

    for finding in findings:
        severity = finding.get("severity", "LOW").upper()
        category = finding.get("category", "")
        weight = SEVERITY_WEIGHT.get(severity, 0)

        deductions["overall"] += weight

        dim = CAT_TO_DIM.get(category)
        if dim:
            deductions[dim] += weight * 2  # heavier deduction in the specific dimension

    return {
        key: max(0, min(100, 100 - deductions[key]))
        for key in deductions
    }
