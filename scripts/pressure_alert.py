#!/usr/bin/env python3
"""Detect unusual pressure changes and notify a Discord webhook."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LEVEL_NAMES = {
    0: "平常",
    1: "注意",
    2: "警戒",
    3: "急変",
}

LEVEL_COLORS = {
    1: 0xFACC15,
    2: 0xF97316,
    3: 0xEF4444,
}

ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(path: Path) -> None:
    """Load .env values without overwriting variables already in the environment."""
    if not path.exists():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not ENV_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"{path}:{line_number}: invalid .env entry")

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()

        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Measurement:
    timestamp: datetime
    pressure: float


@dataclass(frozen=True)
class Features:
    delta_1h: float
    delta_3h: float
    delta_6h: float
    slope_3h: float
    slope_6h: float
    acceleration: float
    range_6h: float


@dataclass(frozen=True)
class AlertResult:
    timestamp: datetime
    pressure: float
    level: int
    score: float
    direction: str
    features: Features
    z_scores: Features


def parse_measurement_lines(
    lines: Iterable[str],
    source_name: str = "<input>",
) -> list[Measurement]:
    measurements: list[Measurement] = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            if "," in line:
                row = next(csv.reader([line]))
                if len(row) != 5:
                    raise ValueError("5列のCSVではありません")
                date_text, hour_text, _, _, pressure_text = (
                    value.strip() for value in row
                )
                hour = int(hour_text)
                if not 0 <= hour <= 23:
                    raise ValueError("時刻が不正です")
                timestamp = datetime.strptime(
                    f"{date_text} {hour:02d}", "%Y-%m-%d %H"
                )
            else:
                row = line.split()
                if row[0].lower() == "timestamp":
                    continue
                if len(row) != 4:
                    raise ValueError("4列の空白区切りデータではありません")
                timestamp_text, _, _, pressure_text = row
                timestamp = datetime.fromisoformat(timestamp_text)
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=None)
            pressure = float(pressure_text)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{source_name}:{line_number}: 計測値の形式が正しくありません"
            ) from error

        if not math.isfinite(pressure):
            raise ValueError(f"{source_name}:{line_number}: 気圧が不正です")

        measurements.append(Measurement(timestamp, pressure))

    if not measurements:
        raise ValueError(f"{source_name}: 計測データがありません")

    by_timestamp = {item.timestamp: item for item in measurements}
    return sorted(by_timestamp.values(), key=lambda item: item.timestamp)


def parse_data_csv(path: Path) -> list[Measurement]:
    with path.open("r", encoding="utf-8", newline="") as source:
        return parse_measurement_lines(source, str(path))


def linear_slope(values: Iterable[float]) -> float:
    points = list(values)
    if len(points) < 2:
        raise ValueError("傾きの計算には2点以上必要です")

    x_mean = (len(points) - 1) / 2
    y_mean = statistics.fmean(points)
    numerator = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(points)
    )
    denominator = sum((index - x_mean) ** 2 for index in range(len(points)))
    return numerator / denominator


def _require_hourly_window(
    measurements: list[Measurement], end_index: int, hours: int
) -> list[Measurement]:
    start_index = end_index - hours
    if start_index < 0:
        raise ValueError("特徴量の計算に必要な履歴が不足しています")

    window = measurements[start_index : end_index + 1]
    for previous, current in zip(window, window[1:]):
        if current.timestamp - previous.timestamp != timedelta(hours=1):
            raise ValueError(
                "直近データに欠損があります。連続した1時間間隔のデータが必要です"
            )
    return window


def calculate_features(
    measurements: list[Measurement], end_index: int
) -> Features:
    window = _require_hourly_window(measurements, end_index, 6)
    pressure = [item.pressure for item in window]

    delta_1h = pressure[-1] - pressure[-2]
    previous_delta_1h = pressure[-2] - pressure[-3]

    return Features(
        delta_1h=delta_1h,
        delta_3h=pressure[-1] - pressure[-4],
        delta_6h=pressure[-1] - pressure[0],
        slope_3h=linear_slope(pressure[-3:]),
        slope_6h=linear_slope(pressure),
        acceleration=delta_1h - previous_delta_1h,
        range_6h=max(pressure) - min(pressure),
    )


def robust_z_score(value: float, history: list[float]) -> float:
    if len(history) < 24:
        raise ValueError("異常度の計算には24件以上の基準データが必要です")

    median = statistics.median(history)
    mad = statistics.median(abs(item - median) for item in history)
    scale = max(1.4826 * mad, 0.1)
    return abs(value - median) / scale


def _feature_history(
    measurements: list[Measurement],
    latest_index: int,
    baseline_days: int,
) -> list[Features]:
    baseline_start = measurements[latest_index].timestamp - timedelta(
        days=baseline_days
    )
    history: list[Features] = []

    for index in range(6, latest_index):
        if measurements[index].timestamp < baseline_start:
            continue
        try:
            history.append(calculate_features(measurements, index))
        except ValueError:
            continue

    if len(history) < 24:
        raise ValueError(
            f"基準期間内の連続データが不足しています（有効件数: {len(history)}）"
        )
    return history


def evaluate_alert(
    measurements: list[Measurement],
    baseline_days: int = 30,
) -> AlertResult:
    latest_index = len(measurements) - 1
    current = calculate_features(measurements, latest_index)
    history = _feature_history(measurements, latest_index, baseline_days)

    def z(name: str) -> float:
        return robust_z_score(
            getattr(current, name),
            [getattr(item, name) for item in history],
        )

    z_scores = Features(
        delta_1h=z("delta_1h"),
        delta_3h=z("delta_3h"),
        delta_6h=z("delta_6h"),
        slope_3h=z("slope_3h"),
        slope_6h=z("slope_6h"),
        acceleration=z("acceleration"),
        range_6h=z("range_6h"),
    )

    critical_score = max(z_scores.delta_1h, z_scores.acceleration)
    short_trend_score = max(
        z_scores.slope_3h,
        0.6 * z_scores.delta_3h + 0.4 * z_scores.slope_6h,
    )
    sustained_score = (
        0.5 * z_scores.delta_6h
        + 0.3 * z_scores.slope_6h
        + 0.2 * z_scores.range_6h
    )
    score = max(critical_score, short_trend_score, sustained_score)

    if score >= 4.0:
        level = 3
    elif score >= 3.0:
        level = 2
    elif score >= 2.0:
        level = 1
    else:
        level = 0

    direction_value = current.delta_3h
    if abs(direction_value) < 0.1:
        direction_value = current.slope_6h
    direction = "上昇" if direction_value > 0 else "下降" if direction_value < 0 else "横ばい"

    latest = measurements[latest_index]
    return AlertResult(
        timestamp=latest.timestamp,
        pressure=latest.pressure,
        level=level,
        score=score,
        direction=direction,
        features=current,
        z_scores=z_scores,
    )


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def should_notify(
    result: AlertResult,
    state: dict[str, object],
    cooldown_hours: float,
    minimum_level: int,
    force: bool = False,
) -> tuple[bool, str]:
    if result.level < minimum_level:
        return False, f"通知対象外です（レベル{result.level}）"
    if force:
        return True, "強制通知"

    try:
        last_sent_at = datetime.fromisoformat(str(state["last_sent_at"]))
        last_level = int(state["level"])
        last_direction = str(state["direction"])
    except (KeyError, TypeError, ValueError):
        return True, "前回通知なし"

    elapsed = result.timestamp - last_sent_at
    same_kind = result.direction == last_direction
    if (
        same_kind
        and elapsed < timedelta(hours=cooldown_hours)
        and result.level <= last_level
    ):
        return False, (
            f"同種アラートのクールダウン中です"
            f"（残り約{max(0.0, cooldown_hours - elapsed.total_seconds() / 3600):.1f}時間）"
        )
    return True, "新規または警戒レベル上昇"


def build_discord_payload(
    result: AlertResult,
    role_id: str | None = None,
    mention_level: int = 3,
) -> dict[str, object]:
    content = None
    allowed_mentions: dict[str, list[str]] = {"parse": []}
    if role_id and result.level >= mention_level:
        content = f"<@&{role_id}> 気圧の急変を検出しました。"
        allowed_mentions = {"parse": [], "roles": [role_id]}

    fields = [
        {"name": "現在気圧", "value": f"{result.pressure:.1f} hPa", "inline": True},
        {
            "name": "1時間変化",
            "value": f"{result.features.delta_1h:+.1f} hPa",
            "inline": True,
        },
        {
            "name": "3時間変化",
            "value": f"{result.features.delta_3h:+.1f} hPa",
            "inline": True,
        },
        {
            "name": "6時間変化",
            "value": f"{result.features.delta_6h:+.1f} hPa",
            "inline": True,
        },
        {
            "name": "6時間傾き",
            "value": f"{result.features.slope_6h:+.2f} hPa/h",
            "inline": True,
        },
        {
            "name": "異常スコア",
            "value": f"{result.score:.2f}",
            "inline": True,
        },
    ]

    payload: dict[str, object] = {
        "username": "Room Conditions",
        "allowed_mentions": allowed_mentions,
        "embeds": [
            {
                "title": f"気圧変化アラート：{LEVEL_NAMES[result.level]}",
                "description": (
                    f"通常より大きな気圧変化（{result.direction}）を検出しました。"
                ),
                "color": LEVEL_COLORS[result.level],
                "fields": fields,
                "timestamp": result.timestamp.isoformat(),
                "footer": {"text": "Room Conditions pressure monitor"},
            }
        ],
    }
    if content:
        payload["content"] = content
    return payload


def send_discord_webhook(
    webhook_url: str,
    payload: dict[str, object],
    max_attempts: int = 3,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(1, max_attempts + 1):
        request = Request(
            webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "RoomConditions/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    return
                raise RuntimeError(f"Discord Webhook HTTP {response.status}")
        except HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == max_attempts:
                raise RuntimeError(
                    f"Discord Webhookへの送信に失敗しました（HTTP {error.code}）"
                ) from error
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 2 ** (attempt - 1)
        except URLError as error:
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Discord Webhookへの接続に失敗しました: {error.reason}"
                ) from error
            delay = 2 ** (attempt - 1)
        time.sleep(delay)


def save_state(path: Path, result: AlertResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_sent_at": result.timestamp.isoformat(),
        "level": result.level,
        "direction": result.direction,
        "score": round(result.score, 4),
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="気圧変化を検出し、Discord Webhookへ通知します。"
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=repository_root / "public" / "data" / "data.csv",
        help="5列CSVまたはtimestampを持つ4列空白区切りの計測データ",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=repository_root / ".pressure-alert-state.json",
        help="通知クールダウン状態の保存先",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=int(os.getenv("PRESSURE_BASELINE_DAYS", "30")),
    )
    parser.add_argument(
        "--cooldown-hours",
        type=float,
        default=float(os.getenv("PRESSURE_COOLDOWN_HOURS", "6")),
    )
    parser.add_argument(
        "--minimum-level",
        type=int,
        choices=(1, 2, 3),
        default=int(os.getenv("PRESSURE_MINIMUM_LEVEL", "1")),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parents[1]
    try:
        load_dotenv(repository_root / ".env")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    args = build_parser().parse_args(argv)

    try:
        measurements = parse_data_csv(args.data)
        result = evaluate_alert(measurements, args.baseline_days)
        notify, reason = should_notify(
            result,
            load_state(args.state),
            args.cooldown_hours,
            args.minimum_level,
            args.force,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    summary = {
        **asdict(result),
        "timestamp": result.timestamp.isoformat(),
        "notify": notify,
        "reason": reason,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not notify:
        return 0

    payload = build_discord_payload(
        result,
        role_id=os.getenv("DISCORD_ROLE_ID"),
        mention_level=int(os.getenv("DISCORD_MENTION_LEVEL", "3")),
    )
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(
            "ERROR: DISCORD_WEBHOOK_URL環境変数を設定してください",
            file=sys.stderr,
        )
        return 2

    try:
        send_discord_webhook(webhook_url, payload)
        save_state(args.state, result)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Discordへアラートを送信しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
