"""Measure a bounded sample of LimeSurvey groups and response latencies."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from services.limesurvey_client import LimeSurveyClient
from services.remote_call_executor import run_remote_call
from core.config import (
    DEFAULT_OPTIMAL_PARAMS,
    LS_OPTIMIZER_MAX_GROUPS,
    LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS,
    LS_OPTIMIZER_MAX_SURVEYS,
    LS_OPTIMIZER_MIN_SUCCESS_RATE,
)


logger = logging.getLogger(__name__)

QuestionFetcher = Callable[..., Awaitable[Any]]
PropertyFetcher = Callable[..., Awaitable[Any]]


class LimeSurveyBenchmark:
    """Own remote measurement only; parameter selection never makes HTTP calls."""

    def __init__(self, api, fetch_questions_fn, fetch_properties_fn):
        self.api = api
        self.fetch_questions = fetch_questions_fn
        self.fetch_properties = fetch_properties_fn

    async def analyze_survey_metrics(self) -> Dict[str, Any]:
        """Find the largest group inside a bounded account sample.

        Citric is synchronous, so each remote call runs in a worker thread and
        does not block FastAPI's event loop.
        """
        metrics: Dict[str, Any] = {
            "max_group_size": 0,
            "max_group_id": None,
            "max_survey_id": None,
            "total_questions": 0,
            "group_sizes": [],
            "question_types": {},
        }
        surveys = await run_remote_call(self.api, self.api.survey.list_surveys)
        visited_groups = 0
        for survey in surveys[:max(1, LS_OPTIMIZER_MAX_SURVEYS)]:
            sid = int(survey["sid"])
            groups = await run_remote_call(self.api, self.api.survey.list_groups, sid)
            for group in groups:
                if visited_groups >= max(1, LS_OPTIMIZER_MAX_GROUPS):
                    return metrics
                visited_groups += 1
                gid = int(group["gid"])
                questions = await run_remote_call(
                    self.api,
                    self.api.survey.list_questions,
                    sid,
                    gid,
                )
                group_size = len(questions)
                metrics["group_sizes"].append(group_size)
                metrics["total_questions"] += group_size
                if group_size > metrics["max_group_size"]:
                    metrics["max_group_size"] = group_size
                    metrics["max_group_id"] = gid
                    metrics["max_survey_id"] = sid
                for question in questions:
                    question_type = question.get("type", "unknown")
                    counts = metrics["question_types"]
                    counts[question_type] = counts.get(question_type, 0) + 1
        return metrics

    async def measure_combination(
        self,
        semaphore: int,
        max_attempts: int,
        survey_id: int,
        group_id: int,
    ) -> Optional[Dict[str, float]]:
        """Measure one semaphore/retry combination against a survey group."""
        local_semaphore = asyncio.Semaphore(semaphore)
        try:
            fetch_started = time.perf_counter()
            questions = await self.fetch_questions(
                survey_id,
                group_id,
                local_semaphore,
                max_attempts,
            )
            fetch_duration = time.perf_counter() - fetch_started
            if not questions:
                return None

            async def measure(question: Dict[str, Any]) -> Optional[float]:
                started = time.perf_counter()
                try:
                    await asyncio.wait_for(
                        self.fetch_properties(
                            question["qid"],
                            local_semaphore,
                            max_attempts,
                        ),
                        timeout=30.0,
                    )
                    return time.perf_counter() - started
                except asyncio.TimeoutError:
                    logger.warning("Question %s timed out", question["qid"])
                except Exception as exc:
                    logger.warning("Question %s failed: %s", question["qid"], exc)
                return None

            sample = questions[:max(1, LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS)]
            measurements = await asyncio.gather(*(measure(question) for question in sample))
            durations = [duration for duration in measurements if duration is not None]
            if not durations:
                return None
            successful = len(durations)
            failed = len(sample) - successful
            average = (fetch_duration + sum(durations)) / len(sample)
            logger.info(
                "Optimizer sample semaphore=%s max_attempts=%s successful=%s failed=%s average_ms=%.2f",
                semaphore,
                max_attempts,
                successful,
                failed,
                average * 1000,
            )
            return {
                "success_rate": successful / len(sample),
                "avg_response_time": average,
                "error_count": float(failed),
            }
        except Exception as exc:
            logger.exception(
                "Could not evaluate semaphore=%s max_attempts=%s: %s",
                semaphore,
                max_attempts,
                exc,
            )
            return None
