"""PDF report generation for SpringInsight scan results.

Generates a professional multi-page PDF report from a completed Run.
Uses reportlab for pure-Python PDF generation with no system dependencies.

Falls back to a simple text-based PDF if reportlab is unavailable.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

SEVERITY_COLORS_RGB = {
    "CRITICAL": (0.97, 0.27, 0.27),   # red
    "HIGH":     (0.98, 0.57, 0.18),   # orange
    "MEDIUM":   (0.92, 0.71, 0.08),   # yellow
    "LOW":      (0.38, 0.64, 0.98),   # blue
    "INFO":     (0.60, 0.60, 0.65),   # gray
}

SCORE_COLORS = {
    "green":  (0.13, 0.77, 0.37),
    "yellow": (0.92, 0.71, 0.08),
    "red":    (0.94, 0.27, 0.27),
}


def _score_color(score: int | None) -> str:
    if score is None:
        return "gray"
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


def generate_pdf_report(
    run: Any,          # Run ORM object (already loaded, with findings)
    findings: list,    # list of Finding ORM objects
    agent_runs: list,  # list of AgentRun ORM objects
) -> bytes:
    """Generate a PDF report and return the raw bytes.

    Raises ImportError if reportlab is not installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.platypus.flowables import KeepTogether
    except ImportError as exc:
        raise ImportError(
            "reportlab is required for PDF export. "
            "Install it with: pip install reportlab"
        ) from exc

    buffer = io.BytesIO()
    page_width, page_height = A4
    margin = 20 * mm

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=20 * mm,
        title=f"SpringInsight Report — {run.project_name}",
        author="SpringInsight",
    )

    # ── Styles ─────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "SITitle",
        parent=styles["Normal"],
        fontSize=24,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#f97316"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SISubtitle",
        parent=styles["Normal"],
        fontSize=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#9ca3af"),
        spaceAfter=2,
    )
    h2_style = ParagraphStyle(
        "SIH2",
        parent=styles["Normal"],
        fontSize=14,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#e8e8f0"),
        spaceBefore=14,
        spaceAfter=6,
    )
    h3_style = ParagraphStyle(
        "SIH3",
        parent=styles["Normal"],
        fontSize=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#e8e8f0"),
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "SIBody",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.HexColor("#c4c4cc"),
        spaceAfter=3,
        leading=13,
    )
    mono_style = ParagraphStyle(
        "SIMono",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Courier",
        textColor=colors.HexColor("#94a3b8"),
        backColor=colors.HexColor("#111116"),
        spaceAfter=3,
        leftIndent=6,
        rightIndent=6,
        leading=11,
    )
    muted_style = ParagraphStyle(
        "SIMuted",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica",
        textColor=colors.HexColor("#6b6b80"),
        spaceAfter=2,
    )

    BG = colors.HexColor("#08080b")
    SURFACE = colors.HexColor("#111116")
    BORDER = colors.HexColor("#1c1c24")
    ORANGE = colors.HexColor("#f97316")
    TEXT = colors.HexColor("#e8e8f0")
    MUTED = colors.HexColor("#6b6b80")

    story = []

    # ── Cover page ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("⚡ SpringInsight", title_style))
    story.append(Paragraph("Codebase Intelligence Report", subtitle_style))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=ORANGE, spaceAfter=6))

    proj_info = [
        ["Project", run.project_name],
        ["Status", run.status.upper()],
        ["Branch", run.git_branch or "—"],
        ["Commit", (run.git_commit or "—")[:12]],
        ["Scan Started", run.started_at.strftime("%Y-%m-%d %H:%M UTC") if run.started_at else "—"],
        ["Scan Duration", f"{run.duration_seconds:.0f}s" if run.duration_seconds else "—"],
        ["Total Findings", str(len(findings))],
    ]
    if run.score_overall is not None:
        proj_info.append(["Overall Score", f"{run.score_overall}/100"])

    cover_table = Table(proj_info, colWidths=[50 * mm, 110 * mm])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), ORANGE),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [SURFACE, colors.HexColor("#13131a")]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(cover_table)
    story.append(PageBreak())

    # ── Score Dashboard ────────────────────────────────────────────────────────
    story.append(Paragraph("Score Dashboard", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))

    score_data = [
        ["Dimension", "Score", "Weight"],
        ["Security", run.score_security, "30%"],
        ["Code Quality", run.score_code_quality, "20%"],
        ["Architecture", run.score_architecture, "15%"],
        ["API Design", run.score_api_design, "15%"],
        ["Production Readiness", run.score_production_readiness, "12%"],
        ["Test Coverage", run.score_test_coverage, "8%"],
        ["OVERALL", run.score_overall, "100%"],
    ]

    def _score_cell(val: int | None, is_overall: bool = False) -> str:
        if val is None:
            return "—"
        color = "#4ade80" if val >= 80 else "#facc15" if val >= 60 else "#f87171"
        font = "Helvetica-Bold" if is_overall else "Helvetica"
        return f"<font color='{color}' name='{font}'>{val}/100</font>"

    score_table_data = [[
        Paragraph("Dimension", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
        Paragraph("Score", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
        Paragraph("Weight", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
    ]]
    for row in score_data[1:]:
        is_overall = row[0] == "OVERALL"
        fn = "Helvetica-Bold" if is_overall else "Helvetica"
        tc = ORANGE if is_overall else TEXT
        score_table_data.append([
            Paragraph(f"<font name='{fn}'>{row[0]}</font>",
                      ParagraphStyle("x", parent=body_style, textColor=tc)),
            Paragraph(_score_cell(row[1], is_overall), body_style),
            Paragraph(f"<font color='#6b6b80'>{row[2]}</font>", body_style),
        ])

    score_tbl = Table(score_table_data, colWidths=[80 * mm, 50 * mm, 40 * mm])
    score_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [SURFACE, colors.HexColor("#13131a")]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, -1), (-1, -1), 1, ORANGE),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1, 8 * mm))

    # Findings summary by severity
    sev_counts = {s: 0 for s in SEVERITY_ORDER}
    for f in findings:
        sev = getattr(f, "severity", "INFO").upper()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    story.append(Paragraph("Findings Summary", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))

    sev_table_data = [[
        Paragraph("Severity", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
        Paragraph("Count", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
    ]]
    for sev in SEVERITY_ORDER:
        count = sev_counts.get(sev, 0)
        r, g, b = SEVERITY_COLORS_RGB.get(sev, (0.6, 0.6, 0.6))
        hex_color = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
        sev_table_data.append([
            Paragraph(f"<font color='{hex_color}' name='Helvetica-Bold'>{sev}</font>", body_style),
            Paragraph(f"<font color='{hex_color}'>{count}</font>", body_style),
        ])

    sev_tbl = Table(sev_table_data, colWidths=[100 * mm, 70 * mm])
    sev_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [SURFACE, colors.HexColor("#13131a")]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(sev_tbl)
    story.append(PageBreak())

    # ── Detailed findings ──────────────────────────────────────────────────────
    story.append(Paragraph("Detailed Findings", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))

    sorted_findings = sorted(
        findings,
        key=lambda f: SEVERITY_ORDER.index(getattr(f, "severity", "INFO").upper())
        if getattr(f, "severity", "INFO").upper() in SEVERITY_ORDER else 99,
    )

    for idx, f in enumerate(sorted_findings):
        sev = getattr(f, "severity", "INFO").upper()
        r, g, b = SEVERITY_COLORS_RGB.get(sev, (0.6, 0.6, 0.6))
        sev_hex = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

        location = getattr(f, "file_path", "") or ""
        if getattr(f, "line_number", None):
            location += f":{f.line_number}"
        if getattr(f, "method_name", None):
            location += f" ({f.method_name})"

        block = []
        block.append(Paragraph(
            f"<font color='{sev_hex}' name='Helvetica-Bold'>[{sev}]</font> "
            f"<font color='#e8e8f0' name='Helvetica-Bold'>{getattr(f, 'category', '')} — "
            f"{getattr(f, 'subcategory', '') or ''}</font>",
            ParagraphStyle("fh", parent=body_style, fontName="Helvetica-Bold",
                           fontSize=10, spaceAfter=2),
        ))
        if location:
            block.append(Paragraph(
                f"<font color='#94a3b8' name='Courier'>📁 {location}</font>",
                mono_style,
            ))
        if getattr(f, "problem", None):
            block.append(Paragraph(getattr(f, "problem", ""), body_style))
        if getattr(f, "fix_description", None):
            block.append(Paragraph(
                f"<font color='#4ade80'>💡 Fix: {f.fix_description[:300]}</font>",
                ParagraphStyle("fix", parent=body_style, textColor=colors.HexColor("#4ade80")),
            ))
        if getattr(f, "fix_code", None):
            block.append(Paragraph(f.fix_code[:400], mono_style))
        if getattr(f, "cve_ids", None) and f.cve_ids:
            cves = ", ".join(f.cve_ids)
            block.append(Paragraph(f"CVEs: {cves}", muted_style))

        block.append(Spacer(1, 3))
        story.append(KeepTogether(block))

        if idx < len(sorted_findings) - 1:
            story.append(HRFlowable(width="100%", thickness=0.3, color=BORDER, spaceAfter=4))

    # ── Agent Summary ──────────────────────────────────────────────────────────
    if agent_runs:
        story.append(PageBreak())
        story.append(Paragraph("Agent Execution Summary", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))

        ar_header = [
            Paragraph("Agent", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
            Paragraph("Model", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
            Paragraph("Status", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
            Paragraph("Findings", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
            Paragraph("Duration", ParagraphStyle("h", parent=body_style, fontName="Helvetica-Bold", textColor=MUTED)),
        ]
        ar_data = [ar_header]

        for ar in sorted(agent_runs, key=lambda x: getattr(x, "agent_id", "")):
            status = getattr(ar, "status", "unknown")
            status_color = "#4ade80" if status == "complete" else "#f87171" if status == "failed" else "#6b6b80"
            dur = ""
            if getattr(ar, "duration_seconds", None):
                dur = f"{ar.duration_seconds:.0f}s"
            model = getattr(ar, "model", "")
            model_short = "Haiku" if "haiku" in model else "Sonnet" if "sonnet" in model else "Opus" if "opus" in model else model

            ar_data.append([
                Paragraph(f"<b>{ar.agent_id}</b> {ar.agent_name}", body_style),
                Paragraph(f"<font color='#6b6b80'>{model_short}</font>", body_style),
                Paragraph(f"<font color='{status_color}'>{status}</font>", body_style),
                Paragraph(str(getattr(ar, "findings_count", 0)), body_style),
                Paragraph(f"<font color='#6b6b80'>{dur}</font>", body_style),
            ])

        ar_tbl = Table(ar_data, colWidths=[65 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm])
        ar_tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [SURFACE, colors.HexColor("#13131a")]),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(ar_tbl)

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Paragraph(
        f"Generated by SpringInsight v0.4.0 · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · "
        "https://springinsight.dev",
        muted_style,
    ))

    # Build on dark background using canvas
    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, page_width, page_height, fill=True, stroke=False)
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()
