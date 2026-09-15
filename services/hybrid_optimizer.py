"""Select conservative parameters from bounded LimeSurvey measurements."""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional
from core.config import DEFAULT_OPTIMAL_PARAMS, LS_OPTIMIZER_MIN_SUCCESS_RATE
from services.limesurvey_benchmark import LimeSurveyBenchmark

logger = logging.getLogger(__name__)


def parameter_score(measurement: dict[str, float], baseline_seconds: float) -> float:
    """Penalize failures and compare latency against the same successful baseline."""
    if measurement["success_rate"] < LS_OPTIMIZER_MIN_SUCCESS_RATE:
        return -1.0
    minimum, maximum = baseline_seconds * 0.5, baseline_seconds * 1.5
    duration = measurement["avg_response_time"]
    time_score = max(0.0, min(1.0, (maximum - duration) / (maximum - minimum))) if maximum > minimum else 0.0
    return time_score * measurement["success_rate"]


class HybridOptimizer:
    """Choose concurrency and attempt limits without duplicating measurement logic."""

    def __init__(self, api, fetch_questions_fn, fetch_properties_fn):
        self.benchmark = LimeSurveyBenchmark(api, fetch_questions_fn, fetch_properties_fn)

    async def find_optimal_parameters(self) -> Dict[str, Any]:
        """Evaluate bounded combinations and return the best parameters."""
        started = time.perf_counter()
        try:
            metrics = await self.benchmark.analyze_survey_metrics()
            if not metrics or metrics["max_group_id"] is None:
                logger.warning("No LimeSurvey groups are available for optimization")
                return self._get_default_parameters()

            baseline = await self.benchmark.measure_combination(
                4, 1, metrics["max_survey_id"], metrics["max_group_id"],
            )
            if baseline is None or baseline["success_rate"] < LS_OPTIMIZER_MIN_SUCCESS_RATE:
                return self._get_default_parameters()
            baseline_seconds = baseline["avg_response_time"]

            best: Optional[Dict[str, Any]] = None
            for semaphore in (2, 4, 6):
                for max_attempts in (1, 2):
                    result = await self.benchmark.measure_combination(
                        semaphore,
                        max_attempts,
                        metrics["max_survey_id"],
                        metrics["max_group_id"],
                    )
                    if not result:
                        continue
                    if result["success_rate"] < LS_OPTIMIZER_MIN_SUCCESS_RATE:
                        continue
                    score = parameter_score(result, baseline_seconds)
                    if best is None or score > best["score"]:
                        best = {
                            "semaphore": semaphore,
                            "maxAttempts": max_attempts,
                            "score": score,
                        }

            if best is not None:
                logger.info(
                    "Optimization completed duration_s=%.2f semaphore=%s max_attempts=%s score=%.3f",
                    time.perf_counter() - started,
                    best["semaphore"],
                    best["maxAttempts"],
                    best["score"],
                )
                return best
            return self._get_default_parameters()
        except asyncio.CancelledError:
            logger.warning("Optimization was cancelled")
            raise
        except Exception as exc:
            logger.exception("Optimization failed: %s", exc)
            return self._get_default_parameters()

    def _get_default_parameters(self) -> Dict[str, Any]:
        """Return conservative parameters when live measurement is unavailable."""
        defaults = {
            "semaphore": DEFAULT_OPTIMAL_PARAMS["semaphore"],
            "maxAttempts": DEFAULT_OPTIMAL_PARAMS["maxAttempts"],
            "score": 0.0,
        }
        logger.info("Using default optimizer parameters: %s", defaults)
        return defaults
