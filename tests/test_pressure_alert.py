from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.pressure_alert import (
    AlertResult,
    Features,
    Measurement,
    build_discord_payload,
    evaluate_alert,
    load_dotenv,
    parse_measurement_lines,
    should_notify,
)


def measurements_with_final_drop() -> list[Measurement]:
    start = datetime(2026, 1, 1)
    values = [
        1000.0 + 0.25 * ((index % 24) - 12) / 12
        for index in range(24 * 15)
    ]
    values[-3:] = [998.8, 997.0, 994.5]
    return [
        Measurement(start + timedelta(hours=index), pressure)
        for index, pressure in enumerate(values)
    ]


class PressureAlertTests(unittest.TestCase):
    def test_dotenv_loads_values_without_overwriting_environment(self) -> None:
        dotenv_path = Mock(spec=Path)
        dotenv_path.exists.return_value = True
        dotenv_path.read_text.return_value = "\n".join(
            [
                "# local settings",
                "DISCORD_WEBHOOK_URL='https://example.invalid/webhook'",
                "PRESSURE_BASELINE_DAYS=14 # two weeks",
                "PRESSURE_MINIMUM_LEVEL=2",
            ]
        )

        with patch.dict(
            os.environ,
            {"PRESSURE_MINIMUM_LEVEL": "3"},
            clear=True,
        ):
            load_dotenv(dotenv_path)

            self.assertEqual(
                os.environ["DISCORD_WEBHOOK_URL"],
                "https://example.invalid/webhook",
            )
            self.assertEqual(os.environ["PRESSURE_BASELINE_DAYS"], "14")
            self.assertEqual(os.environ["PRESSURE_MINIMUM_LEVEL"], "3")

    def test_space_separated_measurements_are_supported(self) -> None:
        measurements = parse_measurement_lines(
            [
                "# comment\n",
                "timestamp temperature humidity pressure\n",
                "2026-06-23T10:00:00+09:00 25.0 50.0 1001.2\n",
            ]
        )

        self.assertEqual(measurements[0].timestamp, datetime(2026, 6, 23, 10))
        self.assertEqual(measurements[0].pressure, 1001.2)

    def test_large_drop_is_detected(self) -> None:
        result = evaluate_alert(measurements_with_final_drop(), baseline_days=14)

        self.assertEqual(result.level, 3)
        self.assertEqual(result.direction, "下降")
        self.assertLess(result.features.delta_3h, -5.0)

    def test_cooldown_suppresses_same_level_and_direction(self) -> None:
        result = evaluate_alert(measurements_with_final_drop(), baseline_days=14)
        state = {
            "last_sent_at": (result.timestamp - timedelta(hours=1)).isoformat(),
            "level": result.level,
            "direction": result.direction,
        }

        notify, _ = should_notify(result, state, cooldown_hours=6, minimum_level=1)

        self.assertFalse(notify)

    def test_embed_disables_uncontrolled_mentions(self) -> None:
        zeroes = Features(0, 0, 0, 0, 0, 0, 0)
        result = AlertResult(
            timestamp=datetime(2026, 6, 23, 12),
            pressure=998.2,
            level=2,
            score=3.2,
            direction="下降",
            features=zeroes,
            z_scores=zeroes,
        )

        payload = build_discord_payload(result)

        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("content", payload)


if __name__ == "__main__":
    unittest.main()
