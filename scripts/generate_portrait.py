#!/usr/bin/env python3
"""
generate_portrait.py

Turns a headshot photo into a self-typing ASCII portrait SVG for a GitHub
profile README. Pipeline: rembg cutout -> bilateral filter -> CLAHE ->
darkening curve -> downsample to a character grid -> SVG with a SMIL
typing-wipe animation and an inlined monospace font subset.

Usage:
    python3 scripts/generate_portrait.py assets/headshot_source.jpg assets/portrait.svg

Requires: pillow, numpy, opencv-python-headless, rembg, onnxruntime
The first run downloads rembg's background-removal model (~176 MB), cached
afterwards under ~/.u2net.
"""
import sys
import base64
import numpy as np
from PIL import Image
import cv2

# ---- tunables -------------------------------------------------------------
COLS = 90                    # character columns
CHAR_W = 7.74                # px, = 0.6em advance at FONT_SIZE (matches the
                              # embedded font's 600/1000 unit advance width)
FONT_SIZE = 12.9              # px
ROW_H = CHAR_W / 0.48         # px, keeps the ascii grid's aspect ratio locked
                              # to the source photo (rows = cols*(h/w)*0.48)
RAMP = " .`:-=+*cs#%@"        # 13 levels, light -> dark; leading space is
                              # intentional: brightest pixels vanish
BG_ALPHA_THRESHOLD = 30       # rembg alpha below this = definitely background
STAGGER = 0.09                # s, delay between each row starting to type
ROW_DUR = 0.42                # s, how long each row takes to wipe in
FONT_PATH = "assets/fonts/ramp.woff2"
# single flat color -- no per-character color. Adapts to the viewer's
# light/dark GitHub theme via a prefers-color-scheme media query.
FILL_COLOR_LIGHT = "#1f2328"
FILL_COLOR_DARK = "#c9d1d9"


def _grabcut_alpha(img_rgb: Image.Image) -> np.ndarray:
    """Fallback cutout with no model download: OpenCV GrabCut seeded with a
    centered rectangle around the face/shoulders. Works well for the
    side-lit, plain-background portraits this pipeline expects; rembg (below)
    gives cleaner edges when its model is reachable."""
    arr = np.array(img_rgb)
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    margin_x, margin_top, margin_bottom = int(w * 0.06), int(h * 0.03), int(h * 0.12)
    rect = (margin_x, margin_top, w - 2 * margin_x, h - margin_top - margin_bottom)
    cv2.grabCut(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), mask, rect, bgd_model,
                fgd_model, iterCount=8, mode=cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    fg = cv2.GaussianBlur(fg, (5, 5), 0)
    return fg


def remove_background(img_rgb: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """Cuts the subject out and composites onto white. Tries rembg first
    (best edges, needs its ~176MB model reachable on first run); falls back
    to a model-free GrabCut cutout if that model can't be downloaded (e.g.
    a network-restricted CI sandbox)."""
    alpha = None
    try:
        import rembg
        cut = rembg.remove(img_rgb)  # RGBA, background transparent
        cut_np = np.array(cut)
        alpha = cut_np[:, :, 3]
    except Exception as e:
        print(f"rembg unavailable ({e}); falling back to GrabCut", file=sys.stderr)
        alpha = _grabcut_alpha(img_rgb)

    rgb = np.array(img_rgb).astype(np.float32)
    a = (alpha.astype(np.float32) / 255.0)[:, :, None]
    white = np.ones_like(rgb) * 255.0
    flattened = (rgb * a + white * (1 - a)).astype(np.uint8)
    return Image.fromarray(flattened), alpha


def process_gray(flattened: Image.Image, alpha: np.ndarray, curve_exp: float = 1.15,
                  clahe_clip: float = 1.5) -> np.ndarray:
    gray = cv2.cvtColor(np.array(flattened), cv2.COLOR_RGB2GRAY)

    # smooth skin, keep edges
    gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    # local contrast so a flatly-lit face doesn't render as one tone
    clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # stretch levels using only the foreground's own range -- a directionally
    # lit face otherwise sits in the bottom third of 0-255 and the ramp never
    # reaches its lighter characters
    fg = alpha >= BG_ALPHA_THRESHOLD
    if fg.any():
        lo, hi = np.percentile(gray[fg].astype(np.float32), [2, 98])
        if hi - lo > 1:
            gray = np.clip((gray.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255)
        else:
            gray = gray.astype(np.float32)
    else:
        gray = gray.astype(np.float32)

    # darkening curve -- keeps glasses/brows/lips from washing out without
    # crushing the whole face to shadow the way a steeper exponent would
    normalized = gray / 255.0
    curved = np.power(np.clip(normalized, 0, 1), curve_exp) * 255.0
    return np.clip(curved, 0, 255).astype(np.uint8)


def to_char_grid(gray: np.ndarray, alpha: np.ndarray, cols: int) -> list[str]:
    h, w = gray.shape
    rows = max(1, round(cols * (h / w) * 0.48))

    small_gray = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)
    small_alpha = cv2.resize(alpha, (cols, rows), interpolation=cv2.INTER_AREA)
    fg = small_alpha >= BG_ALPHA_THRESHOLD
    ramp_len = len(RAMP)

    # Downsampling ~13px of source per character cell averages away most of
    # the tonal range a single portrait actually has, so mapping by absolute
    # brightness leaves the ramp's lighter characters almost unused and the
    # face reads as a flat, dark mass. Mapping by brightness *rank* within
    # the face instead guarantees every one of the 13 levels gets used,
    # which is what keeps features legible at this resolution.
    grid_idx = np.zeros((rows, cols), dtype=int)
    if fg.any():
        vals = small_gray[fg].astype(np.float32)
        order = np.argsort(vals)
        ranks = np.empty_like(order)
        ranks[order] = np.arange(len(order))
        pct = ranks / max(len(order) - 1, 1)  # 0 = darkest .. 1 = brightest
        idxs = np.round((1 - pct) * (ramp_len - 1)).astype(int)
        grid_idx[fg] = idxs

    lines = []
    for r in range(rows):
        row_chars = [RAMP[grid_idx[r, c]] if fg[r, c] else " " for c in range(cols)]
        lines.append("".join(row_chars))
    return lines


def xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_svg(lines: list[str], font_path: str) -> str:
    cols = max(len(l) for l in lines)
    rows = len(lines)
    width = cols * CHAR_W
    height = rows * ROW_H

    with open(font_path, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode("ascii")

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.2f} {height:.2f}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="ASCII self-portrait">'
    )
    parts.append("<defs>")
    parts.append(
        "<style>"
        "@font-face{"
        "font-family:'ramp';"
        f"src:url(data:font/woff2;base64,{font_b64}) format('woff2');"
        "font-weight:normal;font-style:normal;"
        "}"
        f":root{{--ink:{FILL_COLOR_LIGHT};}}"
        f"@media (prefers-color-scheme: dark){{:root{{--ink:{FILL_COLOR_DARK};}}}}"
        f"text{{font-family:'ramp',monospace;font-size:{FONT_SIZE}px;"
        "fill:var(--ink);white-space:pre;}"
        ".cursor{fill:var(--ink);}"
        "</style></defs>"
    )

    baseline_offset = ROW_H * 0.78
    cursor_w = CHAR_W

    for i, line in enumerate(lines):
        row_y = i * ROW_H
        baseline_y = row_y + baseline_offset
        begin = i * STAGGER
        row_w = len(line) * CHAR_W
        clip_id = f"clip{i}"
        parts.append(f'<clipPath id="{clip_id}">')
        parts.append(
            f'<rect x="0" y="{row_y:.2f}" width="0" height="{ROW_H:.2f}">'
            f'<animate attributeName="width" from="0" to="{row_w:.2f}" '
            f'begin="{begin:.2f}s" dur="{ROW_DUR}s" fill="freeze" calcMode="linear"/>'
            f"</rect>"
        )
        parts.append("</clipPath>")

        parts.append(f'<g clip-path="url(#{clip_id})">')
        parts.append(
            f'<text x="0" y="{baseline_y:.2f}" xml:space="preserve">{xml_escape(line)}</text>'
        )
        parts.append("</g>")

        if row_w > 0:
            parts.append(
                f'<rect class="cursor" y="{row_y:.2f}" width="{cursor_w:.2f}" height="{ROW_H:.2f}" '
                f'opacity="0.85">'
                f'<animate attributeName="x" from="0" to="{max(row_w - cursor_w, 0):.2f}" '
                f'begin="{begin:.2f}s" dur="{ROW_DUR}s" fill="freeze" calcMode="linear"/>'
                f'<set attributeName="opacity" to="0" begin="{begin + ROW_DUR:.2f}s" fill="freeze"/>'
                f"</rect>"
            )

    parts.append("</svg>")
    return "".join(parts)


def main():
    if len(sys.argv) < 3:
        print("usage: generate_portrait.py <input.jpg> <output.svg> [cols]")
        sys.exit(1)
    in_path, out_path = sys.argv[1], sys.argv[2]
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else COLS

    img = Image.open(in_path).convert("RGB")
    flattened, alpha = remove_background(img)
    gray = process_gray(flattened, alpha)
    lines = to_char_grid(gray, alpha, cols)
    svg = build_svg(lines, FONT_PATH)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)

    total_type_time = (len(lines) - 1) * STAGGER + ROW_DUR
    print(f"wrote {out_path}: {cols} cols x {len(lines)} rows, "
          f"~{total_type_time:.1f}s type animation")


if __name__ == "__main__":
    main()
