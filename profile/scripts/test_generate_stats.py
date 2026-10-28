#!/usr/bin/env python3
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import generate_stats


def history(start, counts):
    return [
        {"date": (start + timedelta(days=index)).isoformat(), "count": count}
        for index, count in enumerate(counts)
    ]


class CalculateStreaksTests(unittest.TestCase):
    def test_consecutive_contributions_including_today(self):
        today = date(2026, 10, 28)
        self.assertEqual(
            generate_stats.calculate_streaks(history(today - timedelta(days=3), [0, 2, 1, 4]), today),
            (3, 3),
        )

    def test_today_inactive_but_yesterday_active(self):
        today = date(2026, 10, 28)
        self.assertEqual(
            generate_stats.calculate_streaks(history(today - timedelta(days=3), [0, 2, 1, 0]), today),
            (2, 2),
        )

    def test_genuine_break_limits_current_and_longest_streaks(self):
        today = date(2026, 10, 28)
        self.assertEqual(
            generate_stats.calculate_streaks(history(today - timedelta(days=6), [1, 1, 0, 1, 1, 1, 1]), today),
            (4, 4),
        )

    def test_streak_crosses_year_boundary(self):
        today = date(2027, 1, 2)
        self.assertEqual(
            generate_stats.calculate_streaks(history(date(2026, 12, 30), [2, 1, 3, 1]), today),
            (4, 4),
        )

    def test_missing_calendar_date_is_rejected(self):
        today = date(2026, 10, 28)
        days = history(today - timedelta(days=2), [1, 1, 1])
        days.pop(1)
        with self.assertRaises(ValueError):
            generate_stats.calculate_streaks(days, today)

    def test_empty_history_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_stats.calculate_streaks([], date(2026, 10, 28))


class PublicFallbackTests(unittest.TestCase):
    def test_public_user_fallback_uses_one_validated_dataset(self):
        now = generate_stats.datetime(2026, 10, 28, 12, tzinfo=generate_stats.timezone.utc)
        year_start = date(2026, 1, 1)
        rolling_start = date(2025, 10, 29)

        def collection(start, end):
            days = history(start, [1] * ((end - start).days + 1))
            return {
                "restrictedContributionsCount": 0,
                "totalCommitContributions": len(days),
                "contributionCalendar": {
                    "totalContributions": len(days),
                    "weeks": [{"contributionDays": [
                        {"date": day["date"], "contributionCount": day["count"]}
                        for day in days
                    ]}],
                },
            }

        public_response = {
            "user": {
                "login": generate_stats.USERNAME,
                "calendarYear": collection(year_start, now.date()),
                "rolling365": collection(rolling_start, now.date()),
            }
        }
        with patch.object(
            generate_stats,
            "graphql",
            side_effect=[
                generate_stats.TransientGraphQLError("viewer unavailable"),
                generate_stats.TransientGraphQLError("year unavailable"),
                public_response,
            ],
        ):
            result = generate_stats.fetch_streak_data("token", now)

        self.assertEqual(result["current"], 365)
        self.assertEqual(result["longest"], 365)
        self.assertEqual(result["calendar_year"]["total"], 301)

    def test_split_viewer_queries_preserve_authenticated_calendar_data(self):
        now = generate_stats.datetime(2026, 10, 28, 12, tzinfo=generate_stats.timezone.utc)

        def collection(start, total):
            days = history(start, [1] * total)
            return {
                "restrictedContributionsCount": 2,
                "totalCommitContributions": total,
                "contributionCalendar": {
                    "totalContributions": total,
                    "weeks": [{"contributionDays": [
                        {"date": day["date"], "contributionCount": day["count"]}
                        for day in days
                    ]}],
                },
            }

        with patch.object(
            generate_stats,
            "graphql",
            side_effect=[
                generate_stats.TransientGraphQLError("combined unavailable"),
                {"viewer": {"login": generate_stats.USERNAME, "contributions": collection(date(2026, 1, 1), 301)}},
                {"viewer": {"login": generate_stats.USERNAME, "contributions": collection(date(2025, 10, 29), 365)}},
            ],
        ):
            result = generate_stats.fetch_streak_data("token", now)

        self.assertEqual(result["calendar_year"]["total"], 301)
        self.assertEqual(result["rolling_365"]["total"], 365)
        self.assertEqual(result["current"], 365)
        self.assertEqual(result["longest"], 365)


class CalendarValidationTests(unittest.TestCase):
    def test_malformed_calendar_response_is_rejected(self):
        with self.assertRaises(SystemExit):
            generate_stats.parse_calendar_range(
                {"contributionCalendar": {"weeks": []}, "totalCommitContributions": 0},
                date(2026, 10, 28),
                date(2026, 10, 28),
                "malformed",
            )

    def test_malformed_contribution_count_is_rejected(self):
        with self.assertRaises(SystemExit):
            generate_stats.parse_calendar_range(
                {
                    "contributionCalendar": {
                        "totalContributions": 0,
                        "weeks": [{"contributionDays": [
                            {"date": "2026-10-28", "contributionCount": "0"}
                        ]}],
                    },
                    "totalCommitContributions": 0,
                    "restrictedContributionsCount": 0,
                },
                date(2026, 10, 28),
                date(2026, 10, 28),
                "malformed",
            )
