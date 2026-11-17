"""Pure queue-selection and drain-plan logic for the GPU worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .enums import JobType


class SchedulableJob(Protocol):
    model_id: str
    type: Any


def _type_value(job_type: Any) -> str:
    return job_type.value if isinstance(job_type, JobType) else str(job_type)


def _image_quant(job: Any) -> str | None:
    return getattr(job, "params", {}).get("image_quant") if _type_value(job.type) == "image" else None


def select_in_tier[JobT: SchedulableJob](
    tier: list[JobT],
    resident_model: str | None,
    resident_type: str | None,
    resident_quant: str | None = None,
) -> JobT:
    """Choose within an oldest-first priority tier while minimizing swaps."""
    if resident_model is not None:
        same_model = next(
            (job for job in tier if job.model_id == resident_model
             and (_image_quant(job) is None or _image_quant(job) == resident_quant)),
            None,
        )
        if same_model is not None:
            return same_model
        if resident_type is not None:
            same_type = next(
                (job for job in tier if _type_value(job.type) == resident_type),
                None,
            )
            if same_type is not None:
                return same_type
    return tier[0]


@dataclass
class PlanStep:
    model_id: str
    job_type: str
    count: int
    job_ids: list[str] = field(default_factory=list)
    image_quant: str | None = None


def plan_queue(
    jobs: list[Any],
    current_model_id: str | None,
    current_job_type: str | None,
    current_image_quant: str | None = None,
) -> tuple[int, list[PlanStep]]:
    """Predict model swaps and the compressed run sequence for a queue snapshot."""
    remaining = sorted(jobs, key=lambda job: (-job.priority, job.created_at))
    resident_model = current_model_id
    resident_type = current_job_type
    resident_quant = current_image_quant
    swaps = 0
    steps: list[PlanStep] = []

    while remaining:
        top_priority = remaining[0].priority
        tier = [job for job in remaining if job.priority == top_priority]
        chosen = select_in_tier(tier, resident_model, resident_type, resident_quant)
        quant = _image_quant(chosen)
        if resident_model is not None and (chosen.model_id != resident_model or (quant is not None and quant != resident_quant)):
            swaps += 1
        resident_model = chosen.model_id
        resident_type = _type_value(chosen.type)
        resident_quant = quant
        if steps and steps[-1].model_id == chosen.model_id and steps[-1].image_quant == quant:
            steps[-1].count += 1
        else:
            steps.append(PlanStep(chosen.model_id, resident_type, 1, image_quant=quant))
        if hasattr(chosen, "id"):
            steps[-1].job_ids.append(chosen.id)
        remaining.remove(chosen)

    return swaps, steps


__all__ = ["PlanStep", "plan_queue", "select_in_tier"]
