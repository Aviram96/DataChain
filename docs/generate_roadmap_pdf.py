"""Export ROADMAP.md to a PDF copy."""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
ROADMAP_MD = REPO_ROOT / "ROADMAP.md"
OUTPUT = Path(__file__).resolve().parent / "ROADMAP.pdf"


def normalize_text(text: str) -> str:
    """Make markdown/plain text safe for core PDF fonts."""
    replacements = {
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u2192": "->",  # right arrow
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2026": "...",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("`", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Drop any remaining non-latin-1 characters fpdf core fonts cannot render.
    return text.encode("latin-1", errors="replace").decode("latin-1")


def is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped.replace("|", "").replace(":", "").replace("-", "").strip()) == set()


def parse_table_row(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return [normalize_text(cell) for cell in cells]


class RoadmapPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def write_wrapped(pdf: RoadmapPDF, text: str, size: float = 10, style: str = "") -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5, text)
    pdf.ln(1)


def write_table(pdf: RoadmapPDF, rows: list[list[str]]) -> None:
    if not rows:
        return

    col_count = max(len(row) for row in rows)
    usable_width = pdf.w - pdf.l_margin - pdf.r_margin
    if col_count == 3:
        widths = [usable_width * 0.14, usable_width * 0.58, usable_width * 0.28]
    elif col_count == 2:
        widths = [usable_width * 0.35, usable_width * 0.65]
    else:
        widths = [usable_width / col_count] * col_count

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(235, 240, 248)
    pdf.set_text_color(30, 30, 30)
    header = rows[0]
    for idx, cell in enumerate(header):
        pdf.cell(widths[idx], 6, cell[:80], border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(50, 50, 50)
    for row in rows[1:]:
        padded = row + [""] * (col_count - len(row))
        line_height = 5
        x_start = pdf.l_margin
        y_start = pdf.get_y()
        heights: list[float] = []

        for idx, cell in enumerate(padded):
            pdf.set_xy(x_start + sum(widths[:idx]), y_start)
            pdf.multi_cell(widths[idx], line_height, cell, border=0)
            heights.append(pdf.get_y() - y_start)

        row_height = max(heights) if heights else line_height
        for idx in range(col_count):
            pdf.rect(x_start + sum(widths[:idx]), y_start, widths[idx], row_height)
        pdf.set_xy(x_start, y_start + row_height)


def build_pdf() -> Path:
    if not ROADMAP_MD.is_file():
        raise FileNotFoundError(f"Missing roadmap source: {ROADMAP_MD}")

    lines = ROADMAP_MD.read_text(encoding="utf-8").splitlines()
    pdf = RoadmapPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    table_buffer: list[list[str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith("|"):
            if not is_table_separator(stripped):
                table_buffer.append(parse_table_row(stripped))
            idx += 1
            continue

        if table_buffer:
            write_table(pdf, table_buffer)
            table_buffer = []
            pdf.ln(2)

        if not stripped:
            pdf.ln(2)
        elif stripped == "---":
            pdf.ln(2)
        elif stripped.startswith("# "):
            pdf.set_text_color(20, 40, 80)
            write_wrapped(pdf, normalize_text(stripped[2:]), size=18, style="B")
            pdf.ln(2)
        elif stripped.startswith("## "):
            pdf.set_text_color(20, 40, 80)
            write_wrapped(pdf, normalize_text(stripped[3:]), size=13, style="B")
            pdf.ln(1)
        elif stripped.startswith("- "):
            pdf.set_text_color(60, 60, 60)
            write_wrapped(pdf, f"  - {normalize_text(stripped[2:])}", size=10)
        elif stripped.startswith("**") and stripped.endswith("**"):
            pdf.set_text_color(30, 30, 30)
            write_wrapped(pdf, normalize_text(stripped.strip("*")), size=10, style="B")
        else:
            pdf.set_text_color(60, 60, 60)
            write_wrapped(pdf, normalize_text(stripped), size=10)

        idx += 1

    if table_buffer:
        write_table(pdf, table_buffer)

    pdf.output(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    path = build_pdf()
    print(f"Wrote {path}")
