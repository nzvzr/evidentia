"""Named DOCX styles (Phase 4).

Formatting is applied through *named styles*, not ad-hoc run formatting, so the
delivered document is editable the way a human-authored Word document is: change
"Heading 1" once and every heading follows. python-docx ships a default template
that already defines ``Title``, ``Subtitle``, ``Heading 1``–``Heading 3``,
``Normal`` and ``Quote``; this module tunes those and adds the domain styles the
report needs (evidence quotes, citations, severity labels, metadata, table
headers).

All values are static constants — there is no wall-clock, no randomness, and no
tenant input — so the styled document is deterministic.
"""

from __future__ import annotations

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

# A restrained, professional palette. Ink is near-black; the accent is a muted
# teal used sparingly. Severity colors are conventional (red/amber/grey).
INK = RGBColor(0x1A, 0x1A, 0x1C)
SUBTLE = RGBColor(0x6B, 0x6B, 0x72)
ACCENT = RGBColor(0x0B, 0x6B, 0x66)
RISK_HIGH = RGBColor(0xB3, 0x38, 0x28)
RISK_MEDIUM = RGBColor(0xB0, 0x76, 0x1E)
RISK_LOW = RGBColor(0x6B, 0x6B, 0x72)
QUOTE_INK = RGBColor(0x33, 0x33, 0x38)

BODY_FONT = "Calibri"
MONO_FONT = "Consolas"

# Custom style names. Kept distinct from the built-ins so tuning ours never
# collides with a name Word reserves.
S_BODY = "Evidentia Body"
S_EVIDENCE_QUOTE = "Evidence Quote"
S_CITATION = "Citation"
S_RISK_HIGH = "Risk High"
S_RISK_MEDIUM = "Risk Medium"
S_RISK_LOW = "Risk Low"
S_METADATA = "Metadata"
S_TABLE_HEADER = "Table Header"
S_TABLE_CELL = "Table Cell"
S_COVER_LABEL = "Cover Label"


def _font(style, *, name=BODY_FONT, size=None, bold=None, italic=None, color=None):
    font = style.font
    font.name = name
    if size is not None:
        font.size = Pt(size)
    if bold is not None:
        font.bold = bold
    if italic is not None:
        font.italic = italic
    if color is not None:
        font.color.rgb = color
    return font


def _get_or_add(document, name: str, base: str | None = None):
    styles = document.styles
    try:
        return styles[name]
    except KeyError:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        if base is not None:
            try:
                style.base_style = styles[base]
            except KeyError:
                pass
        return style


def apply_styles(document) -> None:
    """Register/tune every named style on ``document``.

    Idempotent: re-tunes built-ins in place and only adds a custom style once.
    """
    styles = document.styles

    # --- base body text ---------------------------------------------------
    normal = styles["Normal"]
    _font(normal, name=BODY_FONT, size=10.5, color=INK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    body = _get_or_add(document, S_BODY, base="Normal")
    _font(body, name=BODY_FONT, size=10.5, color=INK)
    body.paragraph_format.space_after = Pt(8)
    body.paragraph_format.line_spacing = 1.25

    # --- headings & title -------------------------------------------------
    title = styles["Title"]
    _font(title, name=BODY_FONT, size=30, bold=True, color=INK)
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(6)

    subtitle = styles["Subtitle"]
    _font(subtitle, name=BODY_FONT, size=14, italic=False, color=SUBTLE)
    subtitle.paragraph_format.space_after = Pt(4)

    h1 = styles["Heading 1"]
    _font(h1, name=BODY_FONT, size=18, bold=True, color=INK)
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after = Pt(6)
    h1.paragraph_format.keep_with_next = True

    h2 = styles["Heading 2"]
    _font(h2, name=BODY_FONT, size=13.5, bold=True, color=INK)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(4)
    h2.paragraph_format.keep_with_next = True

    h3 = styles["Heading 3"]
    _font(h3, name=BODY_FONT, size=11.5, bold=True, color=ACCENT)
    h3.paragraph_format.space_before = Pt(8)
    h3.paragraph_format.space_after = Pt(2)
    h3.paragraph_format.keep_with_next = True

    # --- domain styles ----------------------------------------------------
    quote = _get_or_add(document, S_EVIDENCE_QUOTE, base="Normal")
    _font(quote, name=BODY_FONT, size=10, italic=True, color=QUOTE_INK)
    quote.paragraph_format.left_indent = Pt(18)
    quote.paragraph_format.right_indent = Pt(12)
    quote.paragraph_format.space_before = Pt(4)
    quote.paragraph_format.space_after = Pt(6)

    citation = _get_or_add(document, S_CITATION, base="Normal")
    _font(citation, name=MONO_FONT, size=9, color=SUBTLE)
    citation.paragraph_format.space_after = Pt(2)

    for name, color in (
        (S_RISK_HIGH, RISK_HIGH),
        (S_RISK_MEDIUM, RISK_MEDIUM),
        (S_RISK_LOW, RISK_LOW),
    ):
        risk = _get_or_add(document, name, base="Normal")
        _font(risk, name=BODY_FONT, size=10.5, bold=True, color=color)
        risk.paragraph_format.space_before = Pt(4)
        risk.paragraph_format.space_after = Pt(2)
        risk.paragraph_format.keep_with_next = True

    metadata = _get_or_add(document, S_METADATA, base="Normal")
    _font(metadata, name=MONO_FONT, size=8.5, color=SUBTLE)
    metadata.paragraph_format.space_after = Pt(1)

    table_header = _get_or_add(document, S_TABLE_HEADER, base="Normal")
    _font(table_header, name=BODY_FONT, size=9.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
    table_header.paragraph_format.space_before = Pt(2)
    table_header.paragraph_format.space_after = Pt(2)

    table_cell = _get_or_add(document, S_TABLE_CELL, base="Normal")
    _font(table_cell, name=BODY_FONT, size=9.5, color=INK)
    table_cell.paragraph_format.space_before = Pt(1)
    table_cell.paragraph_format.space_after = Pt(1)

    cover_label = _get_or_add(document, S_COVER_LABEL, base="Normal")
    _font(cover_label, name=MONO_FONT, size=9, bold=True, color=ACCENT)
    cover_label.paragraph_format.space_after = Pt(0)


def severity_style(severity: str) -> str:
    return {
        "High": S_RISK_HIGH,
        "Medium": S_RISK_MEDIUM,
        "Low": S_RISK_LOW,
    }.get(severity, S_RISK_LOW)


def severity_fill(severity: str) -> str:
    """Table-cell shading hex (no leading #) for a severity, used on risk rows."""
    return {
        "High": "F4D9D4",
        "Medium": "F4E7CE",
        "Low": "ECECEE",
    }.get(severity, "ECECEE")


__all__ = [
    "apply_styles",
    "severity_style",
    "severity_fill",
    "ACCENT",
    "INK",
    "SUBTLE",
    "S_BODY",
    "S_EVIDENCE_QUOTE",
    "S_CITATION",
    "S_RISK_HIGH",
    "S_RISK_MEDIUM",
    "S_RISK_LOW",
    "S_METADATA",
    "S_TABLE_HEADER",
    "S_TABLE_CELL",
    "S_COVER_LABEL",
    "WD_ALIGN_PARAGRAPH",
]
