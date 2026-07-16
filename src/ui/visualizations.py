"""Contract-driven Matplotlib charts for SafeMate analysis results."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

MPL_CACHE_DIR = Path(tempfile.gettempdir()) / "safemate-matplotlib"
MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager
from matplotlib.figure import Figure


BACKGROUND = "#0E1117"
TEXT = "#F3F4F6"
MUTED = "#9CA3AF"
GRID = "#374151"
SAFE = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"


def _configure_korean_font() -> str:
    candidates = (
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
        Path("/System/Library/Fonts/Supplemental/NotoSansGothic-Regular.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    )
    for path in candidates:
        if not path.is_file():
            continue
        font_manager.fontManager.addfont(str(path))
        return font_manager.FontProperties(fname=str(path)).get_name()
    return "DejaVu Sans"


matplotlib.rcParams["font.family"] = _configure_korean_font()
matplotlib.rcParams["axes.unicode_minus"] = False


def create_message_probability_chart(analysis: dict) -> Figure | None:
    """Visualize the normal/phishing probability from the message contract."""
    probability = _unit_interval(analysis.get("phishing_probability"))
    if probability is None:
        return None

    values = [1.0 - probability, probability]
    figure, axis = _new_chart(height=2.6)
    bars = axis.barh(
        ["정상", "피싱"],
        values,
        color=[SAFE, DANGER],
        height=0.55,
    )
    _format_percentage_axis(axis, "메시지 분류 확률")
    _label_bars(axis, bars, values)
    return _finish(figure)


def create_message_feature_chart(top_features: list[dict]) -> Figure | None:
    """Visualize real feature contributions when the model provides them."""
    rows = _feature_rows(top_features, "contribution")
    if not rows:
        return None
    return _horizontal_feature_chart(rows, "판정에 영향을 준 표현", DANGER)


def create_url_risk_chart(url_analyses: list[dict]) -> Figure | None:
    """Compare valid URL risk scores without inventing missing values."""
    rows: list[tuple[str, float]] = []
    for index, analysis in enumerate(url_analyses, start=1):
        score = _unit_interval(analysis.get("risk_score"))
        if score is None:
            continue
        rows.append((_url_label(analysis.get("url"), index), score))
    if not rows:
        return None
    return _horizontal_feature_chart(rows[:10], "URL별 위험 점수", WARNING)


def create_url_feature_chart(features: list[dict]) -> Figure | None:
    """Visualize normalized URL features supplied by the URL model."""
    rows = _feature_rows(features, "normalized_value")
    if not rows:
        return None
    return _horizontal_feature_chart(rows, "URL 특징값", WARNING)


def create_url_contribution_chart(features: list[dict]) -> Figure | None:
    """Visualize URL risk contributions only when they are available."""
    rows = _feature_rows(features, "contribution")
    if not rows:
        return None
    return _horizontal_feature_chart(rows, "특징별 위험 기여도", DANGER)


def _feature_rows(items: list[dict], value_key: str) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = _unit_interval(item.get(value_key))
        name = item.get("name")
        if value is None or not isinstance(name, str) or not name.strip():
            continue
        rows.append((name.strip()[:40], value))
    return sorted(rows, key=lambda row: row[1])[-8:]


def _horizontal_feature_chart(
    rows: list[tuple[str, float]],
    title: str,
    color: str,
) -> Figure:
    labels, values = zip(*rows, strict=True)
    figure, axis = _new_chart(height=max(2.8, 0.52 * len(rows) + 1.4))
    bars = axis.barh(labels, values, color=color, height=0.58)
    _format_percentage_axis(axis, title)
    _label_bars(axis, bars, list(values))
    return _finish(figure)


def _new_chart(*, height: float) -> tuple[Figure, object]:
    figure = Figure(figsize=(8, height), facecolor=BACKGROUND)
    axis = figure.subplots()
    axis.set_facecolor(BACKGROUND)
    axis.tick_params(colors=TEXT, labelsize=10)
    for spine in axis.spines.values():
        spine.set_visible(False)
    return figure, axis


def _format_percentage_axis(axis: object, title: str) -> None:
    axis.set_xlim(0, 1.08)
    axis.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    axis.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], color=MUTED)
    axis.set_title(title, color=TEXT, fontsize=13, fontweight="bold", pad=12)
    axis.grid(axis="x", color=GRID, alpha=0.5, linewidth=0.8)
    axis.set_axisbelow(True)


def _label_bars(axis: object, bars: object, values: list[float]) -> None:
    for bar, value in zip(bars, values, strict=True):
        axis.text(
            min(value + 0.02, 1.02),
            bar.get_y() + bar.get_height() / 2,
            f"{value:.0%}",
            va="center",
            color=TEXT,
            fontsize=10,
        )


def _finish(figure: Figure) -> Figure:
    figure.tight_layout(pad=1.2)
    return figure


def _unit_interval(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        return None
    return normalized


def _url_label(value: object, index: int) -> str:
    if isinstance(value, str):
        try:
            hostname = urlsplit(value).hostname
        except ValueError:
            hostname = None
        if hostname:
            return f"URL {index} · {hostname[:35]}"
    return f"URL {index}"
