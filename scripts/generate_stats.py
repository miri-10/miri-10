#!/usr/bin/env python3
"""
generate_stats.py

Draws four GitHub-profile graphics straight from the GraphQL API: a hero
total with a weekly sparkline, a streak card, a top-languages bar list, and
a year-at-a-glance calendar using the portrait's own density ramp. Standard
library only -- nothing to break in CI.

Env:
    GITHUB_TOKEN   required. The workflow's built-in token is enough.
    GH_LOGIN       required. GitHub username (github.repository_owner in CI).

Usage:
    python3 scripts/generate_stats.py
"""
import os
import sys
import json
import urllib.request
import datetime as dt
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from svg_common import (  # noqa: E402
    RAMP, font_face_css, theme_vars_css, xml_escape, svg_open,
)

API_URL = "https://api.github.com/graphql"
FONT_PATH = "assets/fonts/body.woff2"
RAMP_FONT_PATH = "assets/fonts/ramp.woff2"
OUT_DIR = "."  # repo root, alongside portrait.svg

FONT_SIZE = 14
LINE_H = 20
PAD = 20


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def gh_graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "self-generating-profile",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "errors" in payload:
        raise RuntimeError(f"GraphQL error: {payload['errors']}")
    return payload["data"]


CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
"""

LANG_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(privacy: PUBLIC, first: 50, after: $after, isFork: false,
                  ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def week_aligned_window(today: dt.date) -> tuple[dt.date, dt.date]:
    """53 whole weeks, Sunday-aligned, ending on today -- pinned to whole UTC
    days so two runs minutes apart bucket identically."""
    days_since_sunday = (today.weekday() + 1) % 7  # Mon=0..Sun=6 -> Sun=0
    this_week_start = today - dt.timedelta(days=days_since_sunday)
    start = this_week_start - dt.timedelta(weeks=52)
    return start, today


def fetch_contribution_days(login: str, token: str, today: dt.date):
    start, end = week_aligned_window(today)
    from_iso = dt.datetime.combine(start, dt.time(0, 0, 0)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = dt.datetime.combine(end, dt.time(23, 59, 59)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = gh_graphql(CONTRIB_QUERY, {"login": login, "from": from_iso, "to": to_iso}, token)
    cal = data["user"]["contributionsCollection"]["contributionCalendar"]
    days = []
    for week in cal["weeks"]:
        for d in week["contributionDays"]:
            days.append((dt.date.fromisoformat(d["date"]), d["contributionCount"]))
    days.sort(key=lambda x: x[0])
    return days, cal["totalContributions"]


def fetch_languages(login: str, token: str) -> dict:
    totals = {}
    after = None
    while True:
        data = gh_graphql(LANG_QUERY, {"login": login, "after": after}, token)
        repos = data["user"]["repositories"]
        for node in repos["nodes"]:
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                totals[name] = totals.get(name, 0) + edge["size"]
        if repos["pageInfo"]["hasNextPage"]:
            after = repos["pageInfo"]["endCursor"]
        else:
            break
    return totals


# ---------------------------------------------------------------------------
# derived stats
# ---------------------------------------------------------------------------

def compute_streaks(days: list[tuple[dt.date, int]]):
    runs = []
    run_start = None
    run_end = None
    for d, c in days:
        if c > 0:
            if run_start is None:
                run_start = d
            run_end = d
        else:
            if run_start is not None:
                runs.append((run_start, run_end))
            run_start = None
    if run_start is not None:
        runs.append((run_start, run_end))

    longest = max(runs, key=lambda r: (r[1] - r[0]).days) if runs else None

    today = days[-1][0]
    current = None
    if runs:
        last_run = runs[-1]
        if (today - last_run[1]).days <= 1:
            current = last_run
    return current, longest


def weekly_totals(days: list[tuple[dt.date, int]]):
    weeks = []
    bucket = []
    for d, c in days:
        bucket.append(c)
        if len(bucket) == 7:
            weeks.append(sum(bucket))
            bucket = []
    if bucket:
        weeks.append(sum(bucket))
    return weeks


def ramp_index_for_day(count: int, max_count: int) -> int:
    if count <= 0:
        return 0
    if max_count <= 1:
        return len(RAMP) - 1
    frac = count / max_count
    return 1 + round(frac * (len(RAMP) - 2))


# ---------------------------------------------------------------------------
# SVG builders
# ---------------------------------------------------------------------------

def build_hero_svg(total: int, weeks: list[int]) -> str:
    width, height = 460, 140
    svg = [svg_open(width, height, f"{total} contributions in the last year")]
    svg.append("<defs><style>")
    svg.append(font_face_css(FONT_PATH, "body"))
    svg.append(theme_vars_css())
    svg.append(
        "text{font-family:'body',monospace;fill:var(--ink);}"
        ".muted{fill:var(--muted);}"
        ".spark{fill:none;stroke:var(--ink);stroke-width:1.5;}"
        ".fill{fill:var(--ink);opacity:0.08;}"
    )
    svg.append("</style></defs>")

    svg.append(f'<text x="0" y="46" font-size="40">{total:,}</text>')
    svg.append(f'<text x="0" y="68" font-size="13" class="muted">contributions in the last year</text>')

    if weeks:
        chart_x, chart_y, chart_w, chart_h = 0, 88, width, 40
        mx = max(weeks) or 1
        n = len(weeks)
        pts = []
        for i, v in enumerate(weeks):
            x = chart_x + (i / max(n - 1, 1)) * chart_w
            y = chart_y + chart_h - (v / mx) * chart_h
            pts.append((x, y))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = poly + f" {chart_x+chart_w:.1f},{chart_y+chart_h:.1f} {chart_x:.1f},{chart_y+chart_h:.1f}"
        svg.append(f'<polygon class="fill" points="{area}"/>')
        svg.append(f'<polyline class="spark" points="{poly}"/>')

    svg.append("</svg>")
    return "".join(svg)


def build_streak_svg(current, longest) -> str:
    width, height = 460, 120
    svg = [svg_open(width, height, "contribution streaks")]
    svg.append("<defs><style>")
    svg.append(font_face_css(FONT_PATH, "body"))
    svg.append(theme_vars_css())
    svg.append(
        "text{font-family:'body',monospace;fill:var(--ink);}"
        ".muted{fill:var(--muted);}"
    )
    svg.append("</style></defs>")

    def fmt(run):
        if run is None:
            return 0, "--"
        start, end = run
        n = (end - start).days + 1
        rng = f"{start:%b %-d} - {end:%b %-d, %Y}" if start != end else f"{start:%b %-d, %Y}"
        return n, rng

    cur_n, cur_rng = fmt(current)
    long_n, long_rng = fmt(longest)

    svg.append(f'<text x="0" y="34" font-size="28">{cur_n} day{"s" if cur_n != 1 else ""}</text>')
    svg.append(f'<text x="0" y="54" font-size="12" class="muted">current streak - {xml_escape(cur_rng)}</text>')

    svg.append(f'<text x="0" y="94" font-size="28">{long_n} day{"s" if long_n != 1 else ""}</text>')
    svg.append(f'<text x="0" y="114" font-size="12" class="muted">longest streak - {xml_escape(long_rng)}</text>')

    svg.append("</svg>")
    return "".join(svg)


def build_langs_svg(lang_bytes: dict) -> str:
    ranked = sorted(lang_bytes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    total = sum(v for _, v in ranked) or 1
    row_h = 22
    width = 460
    height = PAD * 2 + row_h * max(len(ranked), 1)
    svg = [svg_open(width, height, "top languages by bytes")]
    svg.append("<defs><style>")
    svg.append(font_face_css(FONT_PATH, "body"))
    svg.append(theme_vars_css())
    svg.append(
        "text{font-family:'body',monospace;fill:var(--ink);font-size:13px;}"
        ".muted{fill:var(--muted);}"
        ".bar{fill:var(--ink);opacity:0.85;}"
        ".track{fill:var(--rule);}"
    )
    svg.append("</style></defs>")

    label_w = 120
    bar_x = label_w
    bar_max_w = width - label_w - 50

    for i, (name, size) in enumerate(ranked):
        y = PAD + i * row_h
        pct = size / total
        bar_w = max(bar_max_w * pct, 2)
        svg.append(f'<text x="0" y="{y + 14:.1f}">{xml_escape(name)}</text>')
        svg.append(f'<rect class="track" x="{bar_x}" y="{y + 3}" width="{bar_max_w}" height="8" rx="1"/>')
        svg.append(f'<rect class="bar" x="{bar_x}" y="{y + 3}" width="{bar_w:.1f}" height="8" rx="1"/>')
        svg.append(f'<text class="muted" x="{width}" y="{y + 14:.1f}" text-anchor="end">{pct*100:.1f}%</text>')

    svg.append("</svg>")
    return "".join(svg)


def build_year_svg(days: list[tuple[dt.date, int]]) -> str:
    weeks = []
    bucket = []
    for d, c in days:
        bucket.append((d, c))
        if len(bucket) == 7:
            weeks.append(bucket)
            bucket = []
    if bucket:
        weeks.append(bucket)

    max_count = max((c for _, c in days), default=0)
    cell = 12
    cols = len(weeks)
    rows = 7
    width = cols * cell
    height = rows * cell

    svg = [svg_open(width, height, "contributions in the last year, one character per day")]
    svg.append("<defs><style>")
    svg.append(font_face_css(RAMP_FONT_PATH, "ramp"))
    svg.append(theme_vars_css())
    svg.append("text{font-family:'ramp',monospace;font-size:11px;fill:var(--ink);white-space:pre;}")
    svg.append("</style></defs>")

    for wi, week in enumerate(weeks):
        for d, c in week:
            row = (d.weekday() + 1) % 7  # Sunday = 0
            idx = ramp_index_for_day(c, max_count)
            ch = RAMP[idx]
            if ch == " ":
                continue
            x = wi * cell + cell * 0.2
            y = row * cell + cell * 0.82
            svg.append(f'<text x="{x:.1f}" y="{y:.1f}" xml:space="preserve">{xml_escape(ch)}</text>')

    svg.append("</svg>")
    return "".join(svg)


# ---------------------------------------------------------------------------

def write_if_changed(path: str, content: str) -> bool:
    p = Path(path)
    if p.exists() and p.read_text(encoding="utf-8") == content:
        return False
    p.write_text(content, encoding="utf-8")
    return True


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_LOGIN")
    if not token or not login:
        print("GITHUB_TOKEN and GH_LOGIN must be set", file=sys.stderr)
        sys.exit(1)

    today = dt.datetime.now(dt.timezone.utc).date()
    days, total = fetch_contribution_days(login, token, today)
    lang_bytes = fetch_languages(login, token)

    current, longest = compute_streaks(days)
    weeks = weekly_totals(days)

    changed = []
    for name, content in [
        ("stats.svg", build_hero_svg(total, weeks)),
        ("streak.svg", build_streak_svg(current, longest)),
        ("langs.svg", build_langs_svg(lang_bytes)),
        ("year.svg", build_year_svg(days)),
    ]:
        path = os.path.join(OUT_DIR, name)
        if write_if_changed(path, content):
            changed.append(name)

    print(f"total={total} weeks={len(weeks)} langs={len(lang_bytes)} changed={changed or 'none'}")


if __name__ == "__main__":
    main()
