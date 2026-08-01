"""Shared SVG helpers for the stats/heading graphics: font embedding, the
light/dark ink that follows the viewer's GitHub theme, and small drawing
utilities. Keeps every generated graphic in the same visual language as the
portrait -- one flat color, monospace, no per-element theming tricks GitHub
would strip anyway.
"""
import base64

INK_LIGHT = "#1f2328"
INK_DARK = "#c9d1d9"
MUTED_LIGHT = "#59636e"
MUTED_DARK = "#8b949e"
RULE_LIGHT = "#d0d7de"
RULE_DARK = "#30363d"

RAMP = " .`:-=+*cs#%@"  # same 13-level density ramp as the portrait


def font_face_css(font_path: str, family: str) -> str:
    with open(font_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (
        f"@font-face{{font-family:'{family}';"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
        "font-weight:normal;font-style:normal;}"
    )


def theme_vars_css() -> str:
    return (
        f":root{{--ink:{INK_LIGHT};--muted:{MUTED_LIGHT};--rule:{RULE_LIGHT};}}"
        "@media (prefers-color-scheme: dark){"
        f":root{{--ink:{INK_DARK};--muted:{MUTED_DARK};--rule:{RULE_DARK};}}"
        "}"
    )


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_open(width: float, height: float, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.2f} {height:.2f}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="{xml_escape(label)}">'
    )
