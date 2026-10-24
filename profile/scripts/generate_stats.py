#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-hosted GitHub profile stats generator.

Fetches live data for `pavankrishtaiahveguru` from the GitHub REST API and the
GraphQL API (contribution calendar) and renders three fully self-contained SVG
cards into `profile/`:

  profile/github-stats.svg     stars / commits / PRs / issues / calendar-year contributions
  profile/github-streak.svg    calendar-year / rolling contributions and streaks
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
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

USERNAME = "pavankrishtaiahveguru"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

REST_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"

# ---------------------------------------------------------------- palette ---
BG = "#FFFFFF"
STROKE = "#DBEAFE"
PRIMARY = "#2563EB"
SECONDARY = "#22D3EE"
BLUE = "#2563EB"
PURPLE = "#9333EA"
GREEN = "#10A56B"
FLAME = "#F43F5E"
WHITE = "#0F172A"
MUTED = "#475569"

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
    headers["Authorization"] = f"Bearer {token}"
    data = payload.encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if not 200 <= resp.status < 300:
                die(f"GitHub API returned HTTP {resp.status} for {url.split('?')[0]}")
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


def graphql(query: str, token: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables})
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
def fetch_rest_stats(token: str, now: datetime) -> dict:
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

    rolling_start = (now.date() - timedelta(days=364)).isoformat()
    rolling_end = now.date().isoformat()
    log(f"REST commit search range: {rolling_start}..{rolling_end} UTC (inclusive dates)")
    commits = int(rest_get("/search/commits", token,
                           params=f"q=author:{USERNAME}+committer-date:{rolling_start}..{rolling_end}&per_page=1")
                  .get("total_count", 0))
    issues = int(rest_get("/search/issues", token,
                          params=f"q=author:{USERNAME}+type:issue&per_page=1").get("total_count", 0))
    prs = int(rest_get("/search/issues", token,
                       params=f"q=author:{USERNAME}+type:pr&per_page=1").get("total_count", 0))
    stats = {
        "stars": total_stars,
        "commits": commits,
        "issues": issues,
        "prs": prs,
        "byte_counts": owned_byte_counts,
    }
    log(f"REST stats fetched: {json.dumps({k: v for k, v in stats.items() if k != 'byte_counts'})}")
    log(f"Language bytes collected across {len(owned_byte_counts)} languages (owner repos, forks excluded)")
    return stats


# --------------------------------------------------------- GraphQL streak ---
CALENDAR_FIELDS = """
fragment CalendarFields on ContributionsCollection {
  restrictedContributionsCount
  contributionCalendar {
    totalContributions
    weeks {
      contributionDays { date contributionCount }
    }
  }
}
"""

VIEWER_CALENDAR_QUERY = CALENDAR_FIELDS + """
query($yearFrom: DateTime!, $rollingFrom: DateTime!, $to: DateTime!) {
  viewer {
    login
    calendarYear: contributionsCollection(from: $yearFrom, to: $to) {
      ...CalendarFields
    }
    rolling365: contributionsCollection(from: $rollingFrom, to: $to) {
      ...CalendarFields
    }
  }
}
"""

USER_CALENDAR_QUERY = CALENDAR_FIELDS + """
query($login: String!, $yearFrom: DateTime!, $rollingFrom: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    calendarYear: contributionsCollection(from: $yearFrom, to: $to) {
      ...CalendarFields
    }
    rolling365: contributionsCollection(from: $rollingFrom, to: $to) {
      ...CalendarFields
    }
  }
}
"""


def parse_calendar_range(collection: dict, start_date, end_date, label: str) -> dict:
    calendar = collection.get("contributionCalendar")
    if not isinstance(calendar, dict):
        die(f"GraphQL {label} response is missing contributionCalendar")
    weeks = calendar.get("weeks")
    if not isinstance(weeks, list):
        die(f"GraphQL {label} calendar is missing a valid weeks list")
    total = calendar.get("totalContributions")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        die(f"GraphQL {label} calendar is missing a valid totalContributions value")

    selected_days = {}
    for week_index, week in enumerate(weeks):
        if not isinstance(week, dict) or not isinstance(week.get("contributionDays"), list):
            die(f"GraphQL {label} week {week_index} is missing contributionDays")
        for day_index, day in enumerate(week["contributionDays"]):
            if not isinstance(day, dict) or not isinstance(day.get("date"), str):
                die(f"GraphQL {label} day {week_index}:{day_index} is missing a valid date")
            date_value = day["date"]
            try:
                contribution_date = datetime.strptime(date_value, "%Y-%m-%d").date()
            except ValueError:
                die(f"GraphQL {label} day {week_index}:{day_index} has invalid date '{date_value}'")
            count = day.get("contributionCount")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                die(f"GraphQL {label} day {week_index}:{day_index} has an invalid contributionCount")
            if start_date <= contribution_date <= end_date:
                if contribution_date in selected_days:
                    die(f"GraphQL {label} calendar contains duplicate date {date_value}")
                selected_days[contribution_date] = count

    expected_days = (end_date - start_date).days + 1
    expected_dates = [
        start_date + timedelta(days=offset) for offset in range(expected_days)
    ]
    if sorted(selected_days) != expected_dates:
        die(
            f"GraphQL {label} calendar does not cover every selected date "
            f"({len(selected_days)} returned, {expected_days} expected)"
        )

    daily_total = sum(selected_days.values())
    log(f"{label} GraphQL totalContributions: {total:,}")
    log(f"{label} selected daily contribution sum: {daily_total:,}")
    if daily_total != total:
        die(
            f"{label} contribution mismatch: daily sum {daily_total:,} "
            f"does not equal GraphQL totalContributions {total:,}"
        )

    restricted = collection.get("restrictedContributionsCount")
    if isinstance(restricted, int) and not isinstance(restricted, bool):
        log(f"{label} restrictedContributionsCount: {restricted:,}")
    return {
        "total": total,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": [
            {"date": date_value.isoformat(), "count": selected_days[date_value]}
            for date_value in expected_dates
        ],
    }


def fetch_streak_data(token: str, now: datetime) -> dict:
    today = now.date()
    year_start = datetime(today.year, 1, 1, tzinfo=timezone.utc).date()
    rolling_start = today - timedelta(days=364)
    year_from = datetime.combine(year_start, datetime.min.time(), timezone.utc)
    rolling_from = datetime.combine(rolling_start, datetime.min.time(), timezone.utc)
    to_value = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    variables = {
        "login": USERNAME,
        "yearFrom": year_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rollingFrom": rolling_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": to_value,
    }
    log("Contribution calendar date ranges (UTC, inclusive calendar dates):")
    log(f"  {today.year}: {variables['yearFrom']} through {to_value} (current day is partial)")
    log(f"  last 365 days: {variables['rollingFrom']} through {to_value} (current day is partial)")
    log(f"Fetching contribution calendars for authenticated GitHub viewer / '{USERNAME}'...")
    viewer_variables = {
        key: value for key, value in variables.items() if key != "login"
    }
    data = graphql(VIEWER_CALENDAR_QUERY, token, viewer_variables)
    viewer = data.get("viewer")
    if not isinstance(viewer, dict) or not isinstance(viewer.get("login"), str):
        die("GraphQL response is missing viewer.login")

    if viewer["login"].lower() == USERNAME.lower():
        account = viewer
        log(f"Contribution calendar account: viewer '{viewer['login']}'")
    else:
        log(
            f"Authenticated viewer is '{viewer['login']}', not '{USERNAME}'. "
            "Falling back to the target user's public contribution calendar; "
            "private activity may not be visible with this token."
        )
        target_data = graphql(USER_CALENDAR_QUERY, token, variables)
        account = target_data.get("user")
        if not isinstance(account, dict) or not isinstance(account.get("login"), str):
            die(f"GraphQL response has no user '{USERNAME}'")
        if account["login"].lower() != USERNAME.lower():
            die(f"GraphQL returned unexpected user '{account['login']}' (expected '{USERNAME}')")

    year = parse_calendar_range(
        account.get("calendarYear"), year_start, today, f"{today.year} calendar year"
    )
    rolling = parse_calendar_range(
        account.get("rolling365"), rolling_start, today, "last 365 days"
    )

    longest = run = 0
    for day in rolling["days"]:
        if day["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    current = 0
    for day in reversed(rolling["days"]):
        if day["date"] == today.isoformat() and day["count"] == 0:
            continue
        if day["count"] > 0:
            current += 1
        else:
            break

    log(f"Current streak: {current} days")
    log(f"Longest streak in the last 365 days: {longest} days")
    return {
        "calendar_year": {
            "year": today.year,
            "total": year["total"],
            "start_date": year["start_date"],
            "end_date": year["end_date"],
        },
        "rolling_365": {
            "total": rolling["total"],
            "start_date": rolling["start_date"],
            "end_date": rolling["end_date"],
        },
        "current": current,
        "longest": longest,
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
    return (
        f'  <rect x="2" y="3" width="{w - 4}" height="{h - 5}" rx="20" '
        f'fill="url(#cardSurface)" stroke="{STROKE}" stroke-width="1.2" '
        'filter="url(#cardShadow)"/>\n'
        f'  <path d="M22 3h{w - 44}" stroke="#FFFFFF" stroke-opacity="0.95" '
        'stroke-width="1.5" stroke-linecap="round"/>\n'
    )


def svg_defs() -> str:
    return (
        "  <defs>\n"
        '    <linearGradient id="cardSurface" x1="0" y1="0" x2="1" y2="1">\n'
        f'      <stop offset="0" stop-color="{BG}" stop-opacity="0.99"/>\n'
        '      <stop offset="1" stop-color="#F7FAFF" stop-opacity="0.98"/>\n'
        '    </linearGradient>\n'
        '    <linearGradient id="ringGradient" x1="0" y1="1" x2="1" y2="0">\n'
        '      <stop offset="0" stop-color="#22D3EE"/>\n'
        '      <stop offset="1" stop-color="#2563EB"/>\n'
        '    </linearGradient>\n'
        '    <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">\n'
        '      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.24"/>\n'
        '      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>\n'
        '    </linearGradient>\n'
        '    <filter id="cardShadow" x="-10%" y="-10%" width="120%" height="130%">\n'
        '      <feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#2563EB" flood-opacity="0.10"/>\n'
        '    </filter>\n'
        '    <filter id="ringGlow" x="-40%" y="-40%" width="180%" height="180%">\n'
        '      <feGaussianBlur stdDeviation="4" result="blur"/>\n'
        '      <feComposite in="SourceGraphic" in2="blur" operator="over"/>\n'
        '    </filter>\n'
        '    <clipPath id="languageBarClip"><rect x="36" y="126" width="568" height="18" rx="9"/></clipPath>\n'
        "  </defs>\n"
    )


def octocat_mark(cx: float, cy: float, size: float, color: str) -> str:
    """Center the Octocat path's 0..16 visual bounds on (cx, cy)."""
    path = ("M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
            "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
            "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 "
            "0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 "
            "0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z")
    scale = size / 16
    x = cx - 8 * scale
    y = cy - 8 * scale
    return (f'  <g transform="translate({x:.2f},{y:.2f}) scale({scale:.5f})">\n'
            f'    <path d="{path}" fill="{color}"/>\n  </g>\n')


def flame_icon(cx: float, cy: float, scale: float, color: str) -> str:
    path = ("M12 2c.5 3.5-1.5 5-3 6.5C7.3 10.2 6 12 6 14.5A6 6 0 0 0 18 14.5c0-2-1-3.5-2-4.5-.3 1-.8 1.7-1.6 2.2.3-2.4-.6-5.7-2.4-8.2-.2-.3-.5-1.3 0-2z")
    return (f'  <g transform="translate({cx:.2f},{cy:.2f}) scale({scale:.5f}) translate(-12,-9.5)">\n'
            f'    <path d="{path}" fill="{color}"/>\n  </g>\n')


def heading_badge(x: int, y: int, icon: str) -> str:
    paths = {
        "chart": '<path d="M3 18h3V9H3v9zm5 0h3V4H8v14zm5 0h3V7h-3v11zm5 0h3V1h-3v17z" fill="#2563EB"/>',
        "code": '<path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 5l-4 14" fill="none" stroke="#2563EB" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    }
    return (
        f'  <rect x="{x}" y="{y}" width="56" height="56" rx="17" '
        'fill="#EFF6FF" stroke="#DBEAFE"/>\n'
        f'  <g transform="translate({x + 15},{y + 15})">{paths[icon]}</g>\n'
    )


# --------------------------------------------------------- card 1: stats ---
def render_stats_card(s: dict, contributions: dict) -> str:
    W, H = 640, 470
    rows = [
        ("Total Stars Earned", fmt_int(s["stars"]), "#F59E0B", star_icon_path()),
        ("Total Commits (last year)", fmt_int(s["commits"]), GREEN, commit_icon_path()),
        ("Total PRs", fmt_int(s["prs"]), PURPLE, pr_icon_path()),
        ("Total Issues", fmt_int(s["issues"]), "#F43F5E", issue_icon_path()),
        (f"{contributions['calendar_year']['year']} Contributions", fmt_int(contributions["calendar_year"]["total"]), BLUE, contributed_icon_path()),
    ]
    out = [svg_header(W, H, f"{USERNAME}'s GitHub Stats",
                      "stars, commits, pull requests, issues and other-repository commits")]
    out.append(svg_defs())
    out.append(card_bg(W, H))
    out.append(octocat_mark(66, 61, 34, "#0F172A"))
    out.append('  <circle cx="66" cy="61" r="34" fill="none" stroke="#BFDBFE" stroke-width="2"/>\n')
    out.append(f'  <text x="112" y="54" font-family="{FONT}" font-size="24" font-weight="700" fill="{WHITE}">PavanVeguru&#8217;s <tspan fill="{PRIMARY}">GitHub Stats</tspan></text>')
    out.append(f'  <text x="112" y="81" font-family="{FONT}" font-size="16" fill="{MUTED}">A quick summary of my GitHub activity</text>')

    y = 137
    for index, (label, value, color, icon) in enumerate(rows):
        out.append(f'  <circle cx="58" cy="{y - 5}" r="22" fill="{color}" fill-opacity="0.10"/>\n')
        out.append(f'  <g transform="translate(50,{y - 13})">{icon}</g>')
        out.append(f'  <text x="103" y="{y + 2}" font-family="{FONT}" font-size="17" fill="#526584">{esc(label)}</text>')
        out.append(f'  <text x="{W - 38}" y="{y + 3}" text-anchor="end" font-family="{FONT}" font-size="21" font-weight="700" fill="{color}">{esc(value)}</text>')
        if index < len(rows) - 1:
            out.append(f'  <line x1="102" y1="{y + 22}" x2="{W - 38}" y2="{y + 22}" stroke="{STROKE}" stroke-width="1"/>')
        y += 57

    out.append(f'  <circle cx="44" cy="{H - 39}" r="12" fill="none" stroke="{MUTED}" stroke-width="2"/>')
    out.append(f'  <path d="M44 {H - 47}v8l5 3" fill="none" stroke="{MUTED}" stroke-width="2" stroke-linecap="round"/>')
    out.append(f'  <text x="67" y="{H - 34}" font-family="{FONT}" font-size="13" fill="{MUTED}">Updated {esc(datetime.now(timezone.utc).strftime("%b %d, %Y"))}  &#183;  Generated from live GitHub data</text>')
    out.append("</svg>\n")
    return "".join(out)


def star_icon_path() -> str:
    return ('<path d="M8 0l2.06 4.9 5.3.43-4.03 3.47 1.22 5.18L8 11.2 3.45 13.98l1.22-5.18L.64 5.33l5.3-.43L8 0z" fill="#F59E0B"/>')


def commit_icon_path() -> str:
    return ('<circle cx="8" cy="8" r="3" fill="none" stroke="#10A56B" stroke-width="1.8"/>'
            '<line x1="8" y1="0" x2="8" y2="5" stroke="#10A56B" stroke-width="1.8"/>'
            '<line x1="8" y1="11" x2="8" y2="16" stroke="#10A56B" stroke-width="1.8"/>')


def pr_icon_path() -> str:
    return ('<circle cx="4" cy="4" r="2.2" fill="none" stroke="#9333EA" stroke-width="1.6"/>'
            '<circle cx="4" cy="12" r="2.2" fill="none" stroke="#9333EA" stroke-width="1.6"/>'
            '<line x1="4" y1="6.2" x2="4" y2="9.8" stroke="#9333EA" stroke-width="1.6"/>'
            '<circle cx="12" cy="12" r="2.2" fill="none" stroke="#9333EA" stroke-width="1.6"/>'
            '<path d="M12 9.8V7a2.5 2.5 0 0 0-2.5-2.5H7" fill="none" stroke="#9333EA" stroke-width="1.6"/>'
            '<path d="M8.8 3.2 7 4.5l1.8 1.3" fill="none" stroke="#9333EA" stroke-width="1.6"/>')


def issue_icon_path() -> str:
    return ('<circle cx="8" cy="8" r="6.4" fill="none" stroke="#F43F5E" stroke-width="1.6"/>'
            '<circle cx="8" cy="8" r="2.2" fill="#F43F5E"/>')


def contributed_icon_path() -> str:
    return ('<circle cx="5.5" cy="4.5" r="2.4" fill="none" stroke="#2563EB" stroke-width="1.5"/>'
            '<path d="M1.5 14c0-2.5 1.8-4.3 4-4.3s4 1.8 4 4.3" fill="none" stroke="#2563EB" stroke-width="1.5"/>'
            '<line x1="11.5" y1="5" x2="15.5" y2="5" stroke="#2563EB" stroke-width="1.5"/>'
            '<line x1="13.5" y1="3" x2="13.5" y2="7" stroke="#2563EB" stroke-width="1.5"/>')


# -------------------------------------------------------- card 2: streak ---
def render_streak_card(st: dict) -> str:
    W, H = 640, 470
    cx, cy, R = 320, 253, 91
    out = [svg_header(W, H, f"{USERNAME}'s Contribution Streak",
                      "calendar-year contributions, current streak, and longest streak in the last 365 days")]
    out.append(svg_defs())
    out.append(card_bg(W, H))
    out.append(heading_badge(28, 26, "chart"))
    out.append(f'  <text x="101" y="51" font-family="{FONT}" font-size="23" font-weight="700" fill="{WHITE}">Contribution / <tspan fill="{PRIMARY}">Streak</tspan></text>')
    out.append(f'  <text x="101" y="77" font-family="{FONT}" font-size="15" fill="{MUTED}">My GitHub contributions and streak details</text>')
    out.append('  <rect x="499" y="34" width="112" height="38" rx="12" fill="#FFFFFF" fill-opacity="0.78" stroke="#DBEAFE"/>\n')
    out.append(f'  <text x="514" y="58" font-family="{FONT}" font-size="13" fill="{MUTED}">Last 1 year</text>')
    out.append('  <path d="m592 49 5 5 5-5" fill="none" stroke="#64748B" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>\n')

    out.append(f'  <rect x="28" y="179" width="148" height="148" rx="25" fill="#FFFFFF" fill-opacity="0.72" stroke="{STROKE}" stroke-width="1.2" filter="url(#cardShadow)"/>\n')
    out.append('  <circle cx="102" cy="220" r="25" fill="#EFF6FF"/>\n')
    out.append('  <g transform="translate(89,207)"><circle cx="8" cy="6" r="4" fill="#2563EB"/><circle cx="19" cy="7" r="3.5" fill="#2563EB"/><path d="M1 21c0-5 3-8 7-8s7 3 7 8v1H1zm14-7c4 0 7 3 7 7v1h-5v-1c0-3-.7-5.4-2-7z" fill="#2563EB"/></g>\n')
    out.append(f'  <text x="102" y="277" text-anchor="middle" font-family="{FONT}" font-size="34" font-weight="700" fill="{BLUE}">{fmt_int(st["calendar_year"]["total"])}</text>')
    out.append(f'  <text x="102" y="302" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{MUTED}">{st["calendar_year"]["year"]} Contributions</text>')

    out.append(f'  <circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="#DBEAFE" stroke-width="12"/>')
    circumference = 2 * 3.141592653589793 * R
    out.append(f'  <circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="url(#ringGradient)" stroke-width="12" stroke-linecap="round" stroke-dasharray="{circumference * 0.78:.1f} {circumference:.1f}" transform="rotate(-90 {cx} {cy})" filter="url(#ringGlow)"/>')
    out.append(f'  <circle cx="{cx}" cy="{cy}" r="72" fill="#FFFFFF" fill-opacity="0.40" stroke="#FFFFFF" stroke-opacity="0.85"/>')
    out.append(flame_icon(cx, cy - 39, 1.5, FLAME))
    out.append(f'  <text x="{cx}" y="{cy + 25}" text-anchor="middle" font-family="{FONT}" font-size="38" font-weight="700" fill="{WHITE}">{st["current"]}</text>')
    out.append(f'  <text x="{cx}" y="{cy + 49}" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{MUTED}">Current Streak</text>')

    out.append(f'  <rect x="464" y="179" width="148" height="148" rx="25" fill="#FFFFFF" fill-opacity="0.72" stroke="{STROKE}" stroke-width="1.2" filter="url(#cardShadow)"/>\n')
    out.append('  <circle cx="538" cy="220" r="25" fill="#FFF7E6"/>\n')
    out.append('  <path d="M530 210h16v8a8 8 0 0 1-16 0zm0 3h-5v3a6 6 0 0 0 6 6m15-9h5v3a6 6 0 0 1-6 6m-7 4v5m-6 0h12" fill="none" stroke="#F59E0B" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>\n')
    out.append(f'  <text x="538" y="277" text-anchor="middle" font-family="{FONT}" font-size="34" font-weight="700" fill="{GREEN}">{st["longest"]}</text>')
    out.append(f'  <text x="538" y="302" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{MUTED}">Longest Streak</text>')

    out.append(f'  <line x1="198" y1="225" x2="198" y2="281" stroke="{STROKE}" stroke-width="1"/>')
    out.append(f'  <line x1="442" y1="225" x2="442" y2="281" stroke="{STROKE}" stroke-width="1"/>')
    out.append(f'  <rect x="28" y="363" width="584" height="1" fill="{STROKE}"/>')
    out.append(f'  <rect x="30" y="389" width="14" height="14" rx="3" fill="none" stroke="{MUTED}" stroke-width="2"/>')
    out.append(f'  <path d="M30 394h14M34 387v4m6-4v4" stroke="{MUTED}" stroke-width="1.6"/>')
    out.append(f'  <text x="57" y="402" font-family="{FONT}" font-size="13" fill="{MUTED}">{st["calendar_year"]["year"]} calendar year  &#183;  {esc(st["calendar_year"]["start_date"])} &#8594; {esc(st["calendar_year"]["end_date"])}</text>')
    out.append(f'  <text x="57" y="428" font-family="{FONT}" font-size="13" fill="{MUTED}">Last 365 days: {fmt_int(st["rolling_365"]["total"])} contributions  &#183;  {esc(st["rolling_365"]["start_date"])} &#8594; {esc(st["rolling_365"]["end_date"])}</text>')
    out.append("</svg>\n")
    return "".join(out)


# ----------------------------------------------------- card 3: languages ---
def render_languages_card(langs: list[dict]) -> str:
    W, H = 640, 470
    pad = 36
    out = [svg_header(W, H, f"{USERNAME}'s Most Used Languages",
                      "top languages by bytes of code across owned repositories")]
    out.append(svg_defs())
    out.append(card_bg(W, H))
    out.append(heading_badge(28, 26, "code"))
    out.append(f'  <text x="101" y="51" font-family="{FONT}" font-size="23" font-weight="700" fill="{WHITE}">Most Used Languages</text>')
    out.append(f'  <text x="101" y="77" font-family="{FONT}" font-size="15" fill="{MUTED}">By bytes of code in my repositories</text>')

    # stacked horizontal bar with percentage-proportional segments
    x = pad
    bar_y = 126
    bar_w = W - 2 * pad
    out.append('  <g clip-path="url(#languageBarClip)">\n')
    for i, l in enumerate(langs):
        seg_w = bar_w * (l["pct"] / 100.0)
        out.append(f'  <rect x="{x:.2f}" y="{bar_y}" width="{max(seg_w, 1.5):.2f}" height="18" fill="{lang_color(l["name"], i)}"/>')
        x += seg_w
    out.append('  </g>\n')
    out.append(f'  <rect x="{pad}" y="{bar_y}" width="{bar_w}" height="9" rx="9" fill="url(#barGradient)"/>')
    out.append(f'  <rect x="{pad}" y="{bar_y}" width="{bar_w}" height="18" rx="9" fill="none" stroke="#FFFFFF" stroke-opacity="0.55"/>')

    y = 184
    for i, l in enumerate(langs):
        color = lang_color(l["name"], i)
        out.append(f'  <circle cx="{pad + 8}" cy="{y - 5}" r="8" fill="{color}"/>')
        out.append(f'  <text x="{pad + 30}" y="{y}" font-family="{FONT}" font-size="17" fill="{WHITE}">{esc(l["name"])}</text>')
        out.append(f'  <text x="{W - pad}" y="{y}" text-anchor="end" font-family="{FONT}" font-size="18" font-weight="700" fill="{color}">{l["pct"]:.2f}%</text>')
        if i < len(langs) - 1:
            out.append(f'  <line x1="{pad + 30}" y1="{y + 15}" x2="{W - pad}" y2="{y + 15}" stroke="{STROKE}" stroke-opacity="0.7"/>')
        y += 37

    out.append(f'  <line x1="{pad}" y1="402" x2="{W - pad}" y2="402" stroke="{STROKE}"/>')
    out.append(f'  <ellipse cx="45" cy="{H - 40}" rx="10" ry="4" fill="none" stroke="{MUTED}" stroke-width="2"/>')
    out.append(f'  <path d="M35 {H - 40}v10c0 5 20 5 20 0v-10m-20 5c0 5 20 5 20 0" fill="none" stroke="{MUTED}" stroke-width="2"/>')
    out.append(f'  <text x="67" y="{H - 43}" font-family="{FONT}" font-size="12" fill="{MUTED}">By bytes of code  &#183;  owned repositories only (forks excluded)</text>')
    out.append(f'  <text x="67" y="{H - 24}" font-family="{FONT}" font-size="12" fill="{MUTED}">Updated {esc(datetime.now(timezone.utc).strftime("%b %d, %Y"))}</text>')
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
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        die(f"{label}: generated SVG is not well-formed XML: {error}")
    if root.tag != "{http://www.w3.org/2000/svg}svg" or not root.get("viewBox"):
        die(f"{label}: generated SVG has an invalid root or missing viewBox")
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

    now = datetime.now(timezone.utc).replace(microsecond=0)
    rest = fetch_rest_stats(token, now)
    streak = fetch_streak_data(token, now)
    langs = top_languages(rest["byte_counts"], n=5)

    validate_and_write(os.path.join(OUT_DIR, "github-stats.svg"), render_stats_card(rest, streak), "github-stats")
    validate_and_write(os.path.join(OUT_DIR, "github-streak.svg"), render_streak_card(streak), "github-streak")
    validate_and_write(os.path.join(OUT_DIR, "top-languages.svg"), render_languages_card(langs), "top-languages")
    log("All three stats cards generated and validated successfully")


if __name__ == "__main__":
    main()
