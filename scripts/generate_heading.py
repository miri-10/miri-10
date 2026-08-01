#!/usr/bin/env python3
"""
generate_heading.py

Section headings as SVG -- the only way to put a custom typeface on a
heading, since GitHub strips <style> blocks and font tags from README
markdown. Renders a lowercase mono label with a hairline rule running to
the right edge.

Usage:
    python3 scripts/generate_heading.py "activity" assets/headings/activity.svg
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from svg_common import font_face_css, theme_vars_css, xml_escape, svg_open  # noqa: E402

FONT_PATH = "assets/fonts/headings.woff2"
WIDTH = 720
HEIGHT = 34
FONT_SIZE = 15
LETTER_SPACING = 2.5


def build(label: str) -> str:
    text = label.lower()
    svg = [svg_open(WIDTH, HEIGHT, f"section: {text}")]
    svg.append("<defs><style>")
    svg.append(font_face_css(FONT_PATH, "headings"))
    svg.append(theme_vars_css())
    svg.append(
        "text{font-family:'headings',monospace;font-size:"
        f"{FONT_SIZE}px;fill:var(--ink);letter-spacing:{LETTER_SPACING}px;}}"
        "line{stroke:var(--rule);stroke-width:1;}"
    )
    svg.append("</style></defs>")

    text_w = len(text) * FONT_SIZE * 0.6 + LETTER_SPACING * len(text)
    svg.append(f'<text x="0" y="{HEIGHT * 0.68:.1f}">{xml_escape(text)}</text>')
    rule_x = text_w + 16
    svg.append(f'<line x1="{rule_x:.1f}" y1="{HEIGHT/2:.1f}" x2="{WIDTH}" y2="{HEIGHT/2:.1f}"/>')
    svg.append("</svg>")
    return "".join(svg)


def main():
    if len(sys.argv) != 3:
        print("usage: generate_heading.py <label> <output.svg>")
        sys.exit(1)
    label, out_path = sys.argv[1], sys.argv[2]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build(label))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
