"""Render metrics/headline.json into a results card.

Outputs:
  docs/assets/metrics.svg   - the card image embedded at the top of README.md
  README.md                 - the block between <!-- metrics:start --> and
                              <!-- metrics:end --> is regenerated (KPI table,
                              bars, facts panel)

Reads metrics/card.json for the card title and the kpi_order that fixes the
tile order. Stdlib only, deterministic, offline.

Usage: python metrics/render.py [--check]
  --check  exit 1 if README.md or the SVG would change (CI drift guard)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
HEADLINE = ROOT / "metrics" / "headline.json"
CARD = ROOT / "metrics" / "card.json"
README = ROOT / "README.md"
SVG_OUT = ROOT / "docs" / "assets" / "metrics.svg"

START = "<!-- metrics:start -->"
END = "<!-- metrics:end -->"

ACCENTS = {
    "teal": "#2dd4bf",
    "blue": "#60a5fa",
    "amber": "#fbbf24",
    "violet": "#a78bfa",
    "red": "#f87171",
}
STATUSES = {"ok", "pending", "blocked"}
STATUS_WORD = {"ok": "observed", "pending": "pending", "blocked": "not claimed"}

WIDTH = 920
PAD = 28
TILE_GAP = 14
TILE_H = 92
BAR_ROW_H = 30
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
BG = "#0f172a"
PANEL = "#1e293b"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
TRACK = "#334155"


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate(headline: dict, kpi_order: list[str]) -> None:
    for key in ("kpis", "bars", "facts"):
        if key not in headline:
            raise SystemExit(f"headline.json: missing '{key}'")
    kpis = headline["kpis"]
    if list(kpis) != kpi_order:
        raise SystemExit(
            f"kpi keys {list(kpis)} do not match card.json kpi_order {kpi_order}"
        )
    for key, tile in kpis.items():
        for field in ("label", "value", "note", "accent"):
            if field not in tile:
                raise SystemExit(f"kpi '{key}': missing '{field}'")
        if tile["accent"] not in ACCENTS:
            raise SystemExit(f"kpi '{key}': bad accent {tile['accent']!r}")
    for row in headline["bars"]["rows"]:
        if not 0 <= row["value"] <= row["max"]:
            raise SystemExit(f"bar {row['label']!r}: value outside [0, max]")
        if row["accent"] not in ACCENTS:
            raise SystemExit(f"bar {row['label']!r}: bad accent")
    for row in headline["facts"]["rows"]:
        if row["status"] not in STATUSES:
            raise SystemExit(f"fact {row['label']!r}: bad status {row['status']!r}")


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_svg(headline: dict, title: str, subtitle: str) -> str:
    kpis = list(headline["kpis"].values())
    bars = headline["bars"]
    per_row = 3 if len(kpis) > 4 else max(1, len(kpis))
    tile_w = (WIDTH - 2 * PAD - TILE_GAP * (per_row - 1)) / per_row
    tile_rows = -(-len(kpis) // per_row)

    y = PAD
    parts: list[str] = []
    parts.append(
        f'<text x="{PAD}" y="{y + 20}" font-size="22" font-weight="700" fill="{TEXT}">'
        f"{escape(title)}</text>"
    )
    parts.append(
        f'<text x="{PAD}" y="{y + 42}" font-size="13" fill="{MUTED}">'
        f"{escape(clip(subtitle, 120))}</text>"
    )
    y += 62

    for i, tile in enumerate(kpis):
        col, row = i % per_row, i // per_row
        x = PAD + col * (tile_w + TILE_GAP)
        ty = y + row * (TILE_H + TILE_GAP)
        color = ACCENTS[tile["accent"]]
        parts.append(
            f'<rect x="{x:.1f}" y="{ty}" width="{tile_w:.1f}" height="{TILE_H}" rx="10" fill="{PANEL}"/>'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{ty}" width="4" height="{TILE_H}" rx="2" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{x + 16:.1f}" y="{ty + 24}" font-size="12" fill="{MUTED}">'
            f"{escape(clip(tile['label'], 34))}</text>"
        )
        parts.append(
            f'<text x="{x + 16:.1f}" y="{ty + 56}" font-size="26" font-weight="700" fill="{color}">'
            f"{escape(clip(tile['value'], 22))}</text>"
        )
        parts.append(
            f'<text x="{x + 16:.1f}" y="{ty + 78}" font-size="10.5" fill="{MUTED}">'
            f"{escape(clip(tile['note'], int(tile_w / 5.6)))}</text>"
        )
    y += tile_rows * (TILE_H + TILE_GAP) + 10

    parts.append(
        f'<text x="{PAD}" y="{y + 14}" font-size="13" font-weight="600" fill="{TEXT}">'
        f"{escape(clip(bars['title'], 130))}</text>"
    )
    y += 28
    label_w = 300
    bar_x = PAD + label_w
    bar_w = WIDTH - bar_x - PAD - 150
    for row in bars["rows"]:
        frac = row["value"] / row["max"] if row["max"] else 0
        color = ACCENTS[row["accent"]]
        cy = y + BAR_ROW_H / 2
        parts.append(
            f'<text x="{PAD}" y="{cy + 4}" font-size="12" fill="{TEXT}">'
            f"{escape(clip(row['label'], 44))}</text>"
        )
        parts.append(
            f'<rect x="{bar_x}" y="{cy - 6}" width="{bar_w}" height="12" rx="6" fill="{TRACK}"/>'
        )
        if frac > 0:
            parts.append(
                f'<rect x="{bar_x}" y="{cy - 6}" width="{max(6, bar_w * frac):.1f}" height="12" rx="6" fill="{color}"/>'
            )
        parts.append(
            f'<text x="{bar_x + bar_w + 12}" y="{cy + 4}" font-size="12" fill="{MUTED}">'
            f"{escape(clip(row['display'], 22))}</text>"
        )
        y += BAR_ROW_H
    y += PAD

    ok = sum(1 for r in headline["facts"]["rows"] if r["status"] == "ok")
    total = len(headline["facts"]["rows"])
    parts.append(
        f'<text x="{PAD}" y="{y - 10}" font-size="11" fill="{MUTED}">'
        f"{escape(headline['facts']['title'])}: {ok} of {total} rows observed offline; "
        f"the rest are marked pending or not claimed in README.md. "
        f"Generated by metrics/render.py from metrics/headline.json.</text>"
    )

    body = "\n".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{y}" '
        f'viewBox="0 0 {WIDTH} {y}" font-family="{FONT}" role="img" '
        f'aria-label="{escape(title)} results card">\n'
        f'<rect width="{WIDTH}" height="{y}" rx="16" fill="{BG}"/>\n{body}\n</svg>\n'
    )


def md_cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render_markdown(headline: dict, subtitle: str, make_target: str) -> str:
    lines = [START, "", "## Results", ""]
    lines.append(
        '<img src="docs/assets/metrics.svg" alt="Results card" width="920">'
    )
    lines.append("")
    lines.append(
        f"Every figure below was observed by `{make_target}`, which runs offline with "
        "a fixed seed and no API key, and writes `metrics/headline.json`. "
        f"{subtitle} Rows marked *pending* need hardware, data or a service the "
        "offline harness does not have; nothing here is estimated."
    )
    lines.append("")
    lines.append("| Metric | Value | How it was measured |")
    lines.append("|---|---|---|")
    for tile in headline["kpis"].values():
        lines.append(
            f"| {md_cell(tile['label'])} | **{md_cell(tile['value'])}** | {md_cell(tile['note'])} |"
        )
    lines.append("")
    lines.append(f"**{md_cell(headline['bars']['title'])}**")
    lines.append("")
    lines.append("| | | |")
    lines.append("|---|---|---|")
    for row in headline["bars"]["rows"]:
        frac = row["value"] / row["max"] if row["max"] else 0
        filled = round(frac * 20)
        bar = "█" * filled + "░" * (20 - filled)
        lines.append(f"| {md_cell(row['label'])} | `{bar}` | {md_cell(row['display'])} |")
    lines.append("")
    lines.append(f"**{md_cell(headline['facts']['title'])}**")
    lines.append("")
    lines.append("| | Status | Evidence |")
    lines.append("|---|---|---|")
    for row in headline["facts"]["rows"]:
        lines.append(
            f"| {md_cell(row['label'])} | {STATUS_WORD[row['status']]} | {md_cell(row['value'])} |"
        )
    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def splice(readme: str, block: str) -> str:
    if START in readme and END in readme:
        head, rest = readme.split(START, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail
    raise SystemExit(f"README.md has no {START} / {END} markers")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on drift")
    args = parser.parse_args(argv)

    headline = load(HEADLINE)
    card = load(CARD)
    validate(headline, card["kpi_order"])

    svg = render_svg(headline, card["title"], card["subtitle"])
    block = render_markdown(headline, card["subtitle"], card["make_target"])
    readme = README.read_text(encoding="utf-8")
    new_readme = splice(readme, block)

    old_svg = SVG_OUT.read_text(encoding="utf-8") if SVG_OUT.exists() else ""
    drift = new_readme != readme or old_svg != svg
    if args.check:
        if drift:
            print("metrics/render.py --check: README.md or docs/assets/metrics.svg is stale")
            return 1
        print("metrics card is current")
        return 0

    SVG_OUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUT.write_text(svg, encoding="utf-8", newline="\n")
    README.write_text(new_readme, encoding="utf-8", newline="\n")
    print(f"wrote {SVG_OUT.relative_to(ROOT)} and README results block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
