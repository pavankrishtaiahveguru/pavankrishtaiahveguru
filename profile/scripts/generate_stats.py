#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-hosted GitHub profile stats generator.

Fetches live data for `pavankrishtaiahveguru` from the GitHub REST API and the
GraphQL API (contribution calendar) and renders three fully self-contained SVG
cards into `profile/`:

  profile/github-stats.svg     stars / commits / PRs / issues / contributed-to
  profile/github-streak.svg    total contributions / current streak / longest streak
  profile/top-languages.svg    top languages by bytes of code

Zero third-party dependencies: uses only the Python standard library, so the
GitHub Actions workflow can run it on any runner without installing anything.

Design notes:
  - The output must never contain fabricated values. Every number displayed is
    computed from API responses. If a fetch fails or returns malformed data the
    script exits non-zero WITHOUT touching any existing SVG on disk.
  - SVGs are standalone: no external images, CSS, or fonts are referenced.

Usage:
  GITHUB_TOKEN=ghp_xxx python3 profile/scripts/generate_stats.py
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

USERNAME = "pavankrishtaiahveguru"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

REST_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"

# ---------------------------------------------------------------- palette ---
BG = "#0D1117"          # card background
STROKE = "#30363D"      # subtle border / dividers
PRIMARY = "#6EE7F7"     # primary cyan (titles)
SECONDARY = "#67E8F9"   # secondary cyan
BLUE = "#7AA2F7"        # blue numbers
PURPLE = "#A78BFA"      # purple numbers
GREEN = "#4ADE80"       # green numbers
FLAME = "#FF6B6B"       # red/orange flame icon
WHITE = "#FFFFFF"       # main text
MUTED = "#8B949E"       # secondary text

# GitHub language colors (as used on github.com itself)
LANG_COLORS = {
    "JavaScript": "#F1E05A", "Java": "#B07219", "HTML": "#E34C26",
    "CSS": "#563D7C", "Python": "#3572A5", "TypeScript": "#3178C6",
    "C": "#555555", "C++": "#F34B7D", "C#": "#178600", "Go": "#00ADD8",
    "Rust": "#DEA584", "Shell": "#89E051", "Kotlin": "#A97BFF",
    "PHP": "#4F5D95", "Ruby": "#701516", "Swift": "#F05138",
    "Dart": "#00B4AB", "Jupyter Notebook": "#DA5B0B", "Vue": "#41B883",
    "SCSS": "#C6538C", "Makefile": "#427819", "Dockerfile": "#384D54",
    "PowerShell": "#012456", "Batchfile": "#C1F12E", "R": "#198CE7",
    "TeX": "#3D6117", "VBA": "#867DB1", "Assembly": "#6E4C13",
    "EJS": "#A91E3C", "HCL": "#844FBA", "Nix": "#7E7EFF",
    "CMake": "#DA3434", "PLpgSQL": "#336790", "MATLAB": "#E16737",
    "Fortran": "#4D41B1", "Pascal": "#E3F171", "Lua": "#000080",
    "Perl": "#0298C3", "Scala": "#C22D40", "Haskell": "#5E5086",
}
FALLBACK_COLORS = ["#6EE7F7", "#7AA2F7", "#A78BFA", "#4ADE80", "#F7DF1E", "#FF6B6B", "#F78C6B", "#64B5F6"]

FONT = "Segoe UI, Ubuntu, Sans-Serif"


def log(msg: str) -> None:
    print(f"[stats] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[stats][ERROR] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ------------------------------------------------------------------ fetch ---
def http_json(url: str, token: str, payload=None) -> dict:
    """GET (or POST if payload given) a URL and parse the JSON response."""
    headers = {
        "Accept": "application/vnd.github+json" if "graphql" not in url else "application/json",
        "User-Agent": f"profile-stats-generator ({USERNAME})",
        "Authorization": f"Bearer {token}",
    }
    data = payload.encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        die(f"GitHub API returned HTTP {e.code} for {url.split('?')[0]}: {detail}")
    except urllib.error.URLError as e:
        die(f"Network error contacting GitHub API: {e.reason}")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        die(f"GitHub API response was not valid JSON for {url.split('?')[0]}")


def rest_get(path: str, token: str, params: str = "") -> dict:
    url = f"{REST_BASE}{path}" + (f"?{params}" if params else "")
    return http_json(url, token)


def graphql(query: str, token: str) -> dict:
    payload = json.dumps({"query": query})
    resp = http_json(GRAPHQL_URL, token, payload=payload)
    if resp.get("errors"):
        die(f"GitHub GraphQL query failed: {json.dumps(resp['errors'])[:400]}")
    data = resp.get("data")
    if data is None:
        die("GitHub GraphQL response contained no 'data' object")
    return data


# ----------------------------------------------------------------- helpers ---
def esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def fmt_int(n: int) -> str:
    return f"{n:,}"


def streak_days_label(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def lang_color(name: str, idx: int) -> str:
    return LANG_COLORS.get(name, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])


# ------------------------------------------------------------- REST stats ---
def fetch_rest_stats(token: str) -> dict:
    log(f"Fetching REST data for '{USERNAME}' (user info, repos, yearly event totals)...")
    user = rest_get(f"/users/{USERNAME}", token)
    login = user.get("login")
    if not login or login.lower() != USERNAME.lower():
        die(f"GitHub API returned unexpected user '{login}' (expected '{USERNAME}')")

    total_stars = 0
    owned_byte_counts: dict[str, int] = {}
    page = 1
    while True:
        repos = rest_get(f"/users/{USERNAME}/repos",
                         token, params=f"per_page=100&page={page}&type=owner")
        if not isinstance(repos, list):
            die("GitHub API returned unexpected payload when listing repositories")
        if not repos:
            break
        for r in repos:
            if r.get("fork"):
                continue  # forks would double-count others' code in the language bar
            total_stars += int(r.get("stargazers_count") or 0)
            full_name = r["full_name"]
            langs = rest_get(f"/repos/{full_name}/languages", token)
            for name, nbytes in (langs or {}).items():
                owned_byte_counts[name] = owned_byte_counts.get(name, 0) + int(nbytes)
        log(f"  page {page}: {len(repos)} repositories processed")
        page += 1
        if page > 12:
            log("  (capped at 12 pages / 1200 repositories)")
            break

    year = one_year_ago_iso()
    commits = int(rest_get("/search/commits", token,
                           params=f"q=author:{USERNAME}+committer-date:>={year}&per_page=1")
                  .get("total_count", 0))
    issues = int(rest_get("/search/issues", token,
                          params=f"q=author:{USERNAME}+type:issue&per_page=1").get("total_count", 0))
    prs = int(rest_get("/search/issues", token,
                       params=f"q=author:{USERNAME}+type:pr&per_page=1").get("total_count", 0))
    # commits in other users'/orgs' repositories = "contributed to" (last year)
    contributed_to = int(rest_get("/search/commits", token,
                                  params=f"q=author:{USERNAME}+committer-date:>={year}+-user:{USERNAME}&per_page=1")
                         .get("total_count", 0))

    stats = {
        "stars": total_stars,
        "commits": commits,
        "issues": issues,
        "prs": prs,
        "contributed_to": contributed_to,
        "byte_counts": owned_byte_counts,
    }
    log(f"REST stats fetched: {json.dumps({k: v for k, v in stats.items() if k != 'byte_counts'})}")
    log(f"Language bytes collected across {len(owned_byte_counts)} languages (owner repos, forks excluded)")
    return stats


def one_year_ago_iso() -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")


# --------------------------------------------------------- GraphQL streak ---
CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
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


def fetch_streak_data(token: str) -> dict:
    log(f"Fetching contribution calendar (GraphQL) for '{USERNAME}'...")
    data = graphql(CALENDAR_QUERY, token)
    try:
        calendar = data["user"]["contributionsCollection"]["contributionCalendar"]
    except (KeyError, TypeError):
        die("GraphQL response missing user.contributionsCollection.contributionCalendar")

    days: list[tuple[str, int]] = []
    for week in calendar.get("weeks", []):
        for d in week.get("contributionDays", []):
            days.append((d["date"], int(d["contributionCount"] or 0)))
    if not days:
        die("Contribution calendar returned zero days — refusing to generate empty stats")
    days.sort(key=lambda x: x[0])

    total_contributions = int(calendar.get("totalContributions") or 0)
    summed = sum(c for _, c in days)
    if total_contributions == 0 and summed == 0:
        die("Contribution calendar totals are zero — refusing to generate empty stats")
    if total_contributions == 0:
        total_contributions = summed  # safety net, keeps GraphQL the source of truth

    # Streaks are computed from the official contribution calendar only.
    current = longest = 0
    run = 0
    for _, count in days:
        if count > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    # current streak: walk backwards from today
    today = days[-1][0]
    run = 0
    for date_str, count in reversed(days):
        if count > 0:
            run += 1
        elif date_str == today:
            continue  # today with 0 contributions does not break the streak yet
        else:
            break
    current = run

    if longest <= 0:
        die("Calculated longest streak is zero — refusing to generate empty stats")
    log(f"Contribution data fetched: total={total_contributions:,}, current_streak={current}, longest_streak={longest}, calendar_days={len(days)}")
    return {
        "total": total_contributions,
        "current": current,
        "longest": longest,
        "first_date": days[0][0],
        "last_date": today,
    }


# ------------------------------------------------------- language rollup ---
def top_languages(byte_counts: dict[str, int], n: int = 5) -> list[dict]:
    total = sum(byte_counts.values())
    if total <= 0:
        die("No language bytes collected from any repository — refusing to generate empty stats")
    items = sorted(byte_counts.items(), key=lambda kv: kv[1], reverse=True)
    top = items[:n]
    rest = items[n:]
    if rest:
        other_bytes = sum(b for _, b in rest)
        threshold = total * 0.01
        if other_bytes >= threshold:
            top.append(("Other", other_bytes))
    langs = [{"name": name, "bytes": b, "pct": b / total * 100.0} for name, b in top]
    log("Language percentages calculated from actual repository byte counts:")
    for l in langs:
        log(f"  {l['name']:<20} {l['pct']:6.2f}%")
    return langs


# ----------------------------------------------------------------- SVG kit ---
def svg_header(width: int, height: int, title: str, desc: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{esc(title)}</title>\n'
        f'  <desc id="desc">{esc(desc)}</desc>\n'
    )


def card_bg(w: int, h: int) -> str:
    return (f'  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" ry="14" '
            f'fill="{BG}" stroke="{STROKE}" stroke-width="1"/>\n')


def defs() -> str:
    return (
        "  <defs>\n"
        '    <clipPath id="ringClip"><circle cx="0" cy="0" r="22"/></clipPath>\n'
        "  </defs>\n"
    )


def octocat_mark(x: float, y: float, size: float, color: str) -> str:
    """GitHub mark (official path, viewBox 0 0 16 16), scaled/positioned."""
    path = ("M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
            "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
            "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 "
            "0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 "
            "0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z")
    return (f'  <g transform="translate({x:.2f},{y:.2f}) scale({size / 16:.5f})">\n'
            f'    <path d="{path}" fill="{color}"/>\n  </g>\n')


def flame_icon(cx: float, cy: float, scale: float, color: str) -> str:
    path = ("M12 2c.5 3.5-1.5 5-3 6.5C7.3 10.2 6 12 6 14.5A6 6 0 0 0 18 14.5c0-2-1-3.5-2-4.5-.3 1-.8 1.7-1.6 2.2.3-2.4-.6-5.7-2.4-8.2-.2-.3-.5-1.3 0-2z")
    return (f'  <g transform="translate({cx:.2f},{cy:.2f}) scale({scale:.5f}) translate(-12,-9.5)">\n'
            f'    <path d="{path}" fill="{color}"/>\n  </g>\n')


# --------------------------------------------------------- card 1: stats ---
def render_stats_card(s: dict) -> str:
    W, H = 480, 212
    rows = [
        ("Total Stars Earned", fmt_int(s["stars"]), BLUE, star_icon_path()),
        ("Total Commits (last year)", fmt_int(s["commits"]), GREEN, commit_icon_path()),
        ("Total PRs", fmt_int(s["prs"]), PURPLE, pr_icon_path()),
        ("Total Issues", fmt_int(s["issues"]), BLUE, issue_icon_path()),
        ("Contributed to (last year)", fmt_int(s["contributed_to"]), GREEN, contributed_icon_path()),
    ]
    out = [svg_header(W, H, f"{USERNAME}'s GitHub Stats",
                      "stars, commits, pull requests, issues and contributions")]
    out.append(card_bg(W, H))
    out.append(f'  <text x="26" y="36" font-family="{FONT}" font-size="15" font-weight="700" fill="{PRIMARY}">PavanVeguru&#8217;s GitHub Stats</text>')
    out.append(f'  <line x1="26" y1="48" x2="{W - 26}" y2="48" stroke="{STROKE}" stroke-width="1"/>')
    # GitHub mark on the right, echoing the reference screenshot
    out.append(octocat_mark(W - 52, 18, 30, PRIMARY))
    out.append(f'  <circle cx="{W - 37}" cy="33" r="20" fill="none" stroke="{SECONDARY}" stroke-opacity="0.35" stroke-width="1.5"/>')

    y = 74
    for label, value, color, icon in rows:
        out.append(f'  <g transform="translate(26,{y}) scale(0.62)">{icon}</g>')
        out.append(f'  <text x="56" y="{y + 8}" font-family="{FONT}" font-size="12.5" fill="{MUTED}">{esc(label)}</text>')
        out.append(f'  <text x="{W - 26}" y="{y + 9}" text-anchor="end" font-family="{FONT}" font-size="16" font-weight="700" fill="{color}">{esc(value)}</text>')
        if label != rows[-1][0]:
            out.append(f'  <line x1="26" y1="{y + 19}" x2="{W - 26}" y2="{y + 19}" stroke="{STROKE}" stroke-opacity="0.55" stroke-width="0.75"/>')
        y += 24

    out.append(f'  <text x="26" y="{H - 12}" font-family="{FONT}" font-size="9" fill="{MUTED}" fill-opacity="0.75">updated {esc(datetime.now(timezone.utc).strftime("%b %d, %Y"))} &#183; generated from live GitHub data</text>')
    out.append("</svg>\n")
    return "".join(out)


def star_icon_path() -> str:
    return ('<path d="M8 0l2.06 4.9 5.3.43-4.03 3.47 1.22 5.18L8 11.2 3.45 13.98l1.22-5.18L.64 5.33l5.3-.43L8 0z" fill="#6EE7F7"/>')


def commit_icon_path() -> str:
    return ('<circle cx="8" cy="8" r="3" fill="none" stroke="#4ADE80" stroke-width="1.8"/>'
            '<line x1="8" y1="0" x2="8" y2="5" stroke="#4ADE80" stroke-width="1.8"/>'
            '<line x1="8" y1="11" x2="8" y2="16" stroke="#4ADE80" stroke-width="1.8"/>')


def pr_icon_path() -> str:
    return ('<circle cx="4" cy="4" r="2.2" fill="none" stroke="#A78BFA" stroke-width="1.6"/>'
            '<circle cx="4" cy="12" r="2.2" fill="none" stroke="#A78BFA" stroke-width="1.6"/>'
            '<line x1="4" y1="6.2" x2="4" y2="9.8" stroke="#A78BFA" stroke-width="1.6"/>'
            '<circle cx="12" cy="12" r="2.2" fill="none" stroke="#A78BFA" stroke-width="1.6"/>'
            '<path d="M12 9.8V7a2.5 2.5 0 0 0-2.5-2.5H7" fill="none" stroke="#A78BFA" stroke-width="1.6"/>'
            '<path d="M8.8 3.2 7 4.5l1.8 1.3" fill="none" stroke="#A78BFA" stroke-width="1.6"/>')


def issue_icon_path() -> str:
    return ('<circle cx="8" cy="8" r="6.4" fill="none" stroke="#7AA2F7" stroke-width="1.6"/>'
            '<circle cx="8" cy="8" r="2.2" fill="#7AA2F7"/>')


def contributed_icon_path() -> str:
    return ('<circle cx="5.5" cy="4.5" r="2.4" fill="none" stroke="#4ADE80" stroke-width="1.5"/>'
            '<path d="M1.5 14c0-2.5 1.8-4.3 4-4.3s4 1.8 4 4.3" fill="none" stroke="#4ADE80" stroke-width="1.5"/>'
            '<line x1="11.5" y1="5" x2="15.5" y2="5" stroke="#4ADE80" stroke-width="1.5"/>'
            '<line x1="13.5" y1="3" x2="13.5" y2="7" stroke="#4ADE80" stroke-width="1.5"/>')


# -------------------------------------------------------- card 2: streak ---
def render_streak_card(st: dict) -> str:
    W, H = 480, 205
    cx, cy, R = 240, 92, 44
    out = [svg_header(W, H, f"{USERNAME}'s Contribution Streak",
                      "total contributions, current streak and longest streak")]
    out.append(card_bg(W, H))
    out.append(f'  <text x="26" y="36" font-family="{FONT}" font-size="15" font-weight="700" fill="{PRIMARY}">Contribution / Streak</text>')
    out.append(f'  <line x1="26" y1="48" x2="{W - 26}" y2="48" stroke="{STROKE}" stroke-width="1"/>')

    CIRC = 2 * 3.141592653589793 * R
    out.append(f'  <circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{STROKE}" stroke-width="8"/>')
    # full decorative ring in cyan, flame on top — matches the reference visual
    out.append(f'  <circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{PRIMARY}" stroke-width="8" '
               f'stroke-linecap="round" stroke-dasharray="{CIRC * 0.78:.1f} {CIRC:.1f}" transform="rotate(-90 {cx} {cy})"/>')
    out.append(flame_icon(cx, cy - 2, 1.35, FLAME))

    # three columns
    cols = [
        (cx - 152, "Total Contributions", fmt_int(st["total"]), BLUE),
        (cx, "Current Streak", streak_days_label(st["current"]), SECONDARY),
        (cx + 152, "Longest Streak", streak_days_label(st["longest"]), GREEN),
    ]
    for col_cx, label, value, color in cols:
        anchor, lx = ("middle", col_cx)
        out.append(f'  <text x="{lx}" y="160" text-anchor="{anchor}" font-family="{FONT}" font-size="11" fill="{MUTED}">{esc(label)}</text>')
        out.append(f'  <text x="{lx}" y="178" text-anchor="{anchor}" font-family="{FONT}" font-size="15" font-weight="700" fill="{color}">{esc(value)}</text>')
    # dividers between columns
    for dx in (-76, 76):
        out.append(f'  <line x1="{cx + dx}" y1="152" x2="{cx + dx}" y2="180" stroke="{STROKE}" stroke-width="1"/>')

    out.append(f'  <text x="26" y="{H - 10}" font-family="{FONT}" font-size="9" fill="{MUTED}" fill-opacity="0.75">GitHub contribution calendar &#183; {esc(st["first_date"])} &#8594; {esc(st["last_date"])}</text>')
    out.append("</svg>\n")
    return "".join(out)


# ----------------------------------------------------- card 3: languages ---
def render_languages_card(langs: list[dict]) -> str:
    W, H = 560, 210
    pad = 26
    bar_x, bar_w = pad, W - 2 * pad
    bar_y = 64
    out = [svg_header(W, H, f"{USERNAME}'s Most Used Languages",
                      "top languages by bytes of code across owned repositories")]
    out.append(card_bg(W, H))
    out.append(f'  <text x="{pad}" y="36" font-family="{FONT}" font-size="15" font-weight="700" fill="{PRIMARY}">Most Used Languages</text>')
    out.append(f'  <line x1="{pad}" y1="48" x2="{W - pad}" y2="48" stroke="{STROKE}" stroke-width="1"/>')

    # stacked horizontal bar with percentage-proportional segments
    x = bar_x
    for i, l in enumerate(langs):
        seg_w = bar_w * (l["pct"] / 100.0)
        out.append(f'  <rect x="{x:.2f}" y="{bar_y}" width="{max(seg_w, 1.5):.2f}" height="10" rx="5" ry="5" fill="{lang_color(l["name"], i)}"/>')
        x += seg_w

    # two-column legend rows
    per_col = (len(langs) + 1) // 2
    col_w = (W - 2 * pad) / 2
    y0 = 100
    for i, l in enumerate(langs):
        col = 0 if i < per_col else 1
        row = i if i < per_col else i - per_col
        lx = pad + col * col_w
        ly = y0 + row * 24
        out.append(f'  <circle cx="{lx + 6}" cy="{ly - 4}" r="5" fill="{lang_color(l["name"], i)}"/>')
        out.append(f'  <text x="{lx + 20}" y="{ly}" font-family="{FONT}" font-size="12.5" fill="{WHITE}">{esc(l["name"])}</text>')
        out.append(f'  <text x="{lx + col_w - 14}" y="{ly}" text-anchor="end" font-family="{FONT}" font-size="12.5" font-weight="600" fill="{lang_color(l["name"], i)}">{l["pct"]:.2f}%</text>')

    out.append(f'  <text x="{pad}" y="{H - 12}" font-family="{FONT}" font-size="9" fill="{MUTED}" fill-opacity="0.75">by bytes of code &#183; owned repositories only (forks excluded) &#183; updated {esc(datetime.now(timezone.utc).strftime("%b %d, %Y"))}</text>')
    out.append("</svg>\n")
    return "".join(out)


# -------------------------------------------------------------- validate ---
SVG_START_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*<svg[\s>]|^\s*<svg[\s>]", re.IGNORECASE)


def validate_and_write(path: str, content: str, label: str) -> None:
    if not content or not content.strip():
        die(f"{label}: generated content is empty — aborting without writing {path}")
    if not SVG_START_RE.match(content):
        die(f"{label}: generated content does not start with valid SVG markup — aborting")
    if content.count("<svg") != 1 or content.count("</svg>") != 1:
        die(f"{label}: unexpected number of <svg> root elements — aborting")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    size = os.path.getsize(path)
    if size < 200:
        die(f"{label}: written file {path} is suspiciously small ({size} bytes)")
    log(f"Generated {os.path.normpath(path)} ({size} bytes)")


# ------------------------------------------------------------------- main ---
def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        die("GITHUB_TOKEN environment variable is not set — refusing to run")
    log(f"Generating self-hosted stats for GitHub user '{USERNAME}'")

    rest = fetch_rest_stats(token)
    streak = fetch_streak_data(token)
    langs = top_languages(rest["byte_counts"], n=5)

    validate_and_write(os.path.join(OUT_DIR, "github-stats.svg"), render_stats_card(rest), "github-stats")
    validate_and_write(os.path.join(OUT_DIR, "github-streak.svg"), render_streak_card(streak), "github-streak")
    validate_and_write(os.path.join(OUT_DIR, "top-languages.svg"), render_languages_card(langs), "top-languages")
    log("All three SVG cards generated and validated successfully")


if __name__ == "__main__":
    main()
