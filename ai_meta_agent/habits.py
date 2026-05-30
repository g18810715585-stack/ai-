from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Habit, Patch


def load_habits(path: Path) -> list[Habit]:
    if not path.exists():
        return []
    habits: list[Habit] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        habits.append(Habit.model_validate(json.loads(line)))
    return habits


def append_habit(path: Path, habit: Habit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(habit.model_dump_json(exclude_none=True))
        handle.write("\n")


def match_habits(habits: list[Habit], project: str, table_names: list[str], limit: int = 8) -> list[Habit]:
    scored: list[tuple[float, Habit]] = []
    for habit in habits:
        score = habit.confidence
        applies = habit.applies_to
        if applies.get("project") == project:
            score += 0.1
        if applies.get("target_table") in table_names:
            score += 0.2
        if score >= 0.5:
            scored.append((min(score, 1.0), habit))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [habit for _, habit in scored[:limit]]


def habit_from_patch(patch: Patch, decision: str, note: str | None = None) -> Habit:
    table_counts: dict[str, int] = {}
    for operation in patch.operations:
        table_counts[operation.target_table] = table_counts.get(operation.target_table, 0) + 1
    top_table = max(table_counts, key=table_counts.get) if table_counts else "unknown"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Habit(
        habit_id=f"habit_{patch.patch_id}_{decision}",
        name=f"{decision} patch {patch.patch_id}",
        scenario=f"User marked patch {patch.patch_id} as {decision}",
        applies_to={"project": patch.project, "target_table": top_table},
        action={
            "decision": decision,
            "operation_count": len(patch.operations),
            "operation_types": sorted({op.op for op in patch.operations}),
        },
        confidence=0.75 if decision == "accepted" else 0.65,
        evidence=[item for item in [f"{timestamp} {decision}", note] if item],
        last_used_at=timestamp,
    )


def habit_context(habits: list[Habit]) -> list[dict[str, Any]]:
    return [
        {
            "habit_id": habit.habit_id,
            "name": habit.name,
            "scenario": habit.scenario,
            "applies_to": habit.applies_to,
            "action": habit.action,
            "confidence": habit.confidence,
            "evidence": habit.evidence[-3:],
        }
        for habit in habits
    ]
