from __future__ import annotations

from typing import Any

TRIM_SIZE_5_5_X_8_5 = "5.5x8.5"
TRIM_SIZE_6_X_9 = "6x9"
TRIM_SIZE_7_X_10 = "7x10"
DEFAULT_TRIM_SIZE = TRIM_SIZE_6_X_9

PRINT_SPECS: dict[str, dict[str, Any]] = {
    TRIM_SIZE_5_5_X_8_5: {
        "trim_size": TRIM_SIZE_5_5_X_8_5,
        "page_size_points": (396, 612),
        "page_size_inches": (5.5, 8.5),
        "margins_points": {"left": 48, "right": 42, "top": 52, "bottom": 52},
        "image_frame_inches": {"width": 4.2, "height": 2.4},
        "font_scale": 0.94,
    },
    TRIM_SIZE_6_X_9: {
        "trim_size": TRIM_SIZE_6_X_9,
        "page_size_points": (432, 648),
        "page_size_inches": (6.0, 9.0),
        "margins_points": {"left": 52, "right": 46, "top": 56, "bottom": 56},
        "image_frame_inches": {"width": 4.6, "height": 2.7},
        "font_scale": 1.0,
    },
    TRIM_SIZE_7_X_10: {
        "trim_size": TRIM_SIZE_7_X_10,
        "page_size_points": (504, 720),
        "page_size_inches": (7.0, 10.0),
        "margins_points": {"left": 58, "right": 52, "top": 60, "bottom": 60},
        "image_frame_inches": {"width": 5.4, "height": 3.1},
        "font_scale": 1.08,
    },
}


def normalize_trim_size(trim_size: str | None) -> str:
    value = (trim_size or "").strip().lower()
    if value in PRINT_SPECS:
        return value
    return DEFAULT_TRIM_SIZE


def get_print_spec(trim_size: str | None) -> dict[str, Any]:
    normalized = normalize_trim_size(trim_size)
    spec = PRINT_SPECS[normalized]
    return {
        "trim_size": spec["trim_size"],
        "page_size_points": tuple(spec["page_size_points"]),
        "page_size_inches": tuple(spec["page_size_inches"]),
        "margins_points": dict(spec["margins_points"]),
        "image_frame_inches": dict(spec["image_frame_inches"]),
        "font_scale": float(spec["font_scale"]),
    }
