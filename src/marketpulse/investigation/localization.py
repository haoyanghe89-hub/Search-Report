"""Chinese presentation only; never apply to evidence, identifiers or stored hashes."""

from __future__ import annotations

import json
import re
from pathlib import Path

_CATALOG: dict[str, dict[str, str]] = json.loads(
    Path(__file__).with_name("zh_CN.json").read_text(encoding="utf-8")
)


def label(value: object) -> str:
    text = str(value) if value is not None else ""
    return _CATALOG["labels"].get(text, text)


def chinese_text(value: str) -> str:
    """Only reviewed exact translations, with unknown historical text preserved."""
    ended = re.fullmatch(r"Run ended with status ([A-Z_]+)\. (.*)", value)
    if ended:
        return f"运行结束时状态为“{label(ended[1])}”。" + chinese_text(ended[2])
    omitted = re.fullmatch(
        r"(\d+) claims have not completed validation; "
        r"they are omitted from findings and remain available in the run record\.",
        value,
    )
    if omitted:
        return f"另有 {omitted[1]} 条声明尚未完成验证，未计入本报告发现；可在运行记录中查看。"
    conflict = re.fullmatch(r"Unresolved ([A-Z_]+) conflict over (\d+) claims", value)
    if conflict:
        return f"涉及 {conflict[2]} 条声明的“{label(conflict[1])}”冲突尚未解决。"
    return _CATALOG["texts"].get(value, value)
