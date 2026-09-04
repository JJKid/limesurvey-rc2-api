"""Measure LimeSurvey latency and choose bounded concurrency/retry settings."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from services.limesurvey_client import LimeSurveyClient
from services.remote_call_executor import run_remote_call


logger = logging.getLogger(__name__)

QuestionFetcher = Callable[..., Awaitable[Any]]
PropertyFetcher = Callable[..., Awaitable[Any]]


class HybridOptimizer:
    """Combine host limits with live LimeSurvey measurements.

    The optimizer uses the largest available question group as a bounded test
    case. It compares a small set of semaphore and retry values and returns the
    fastest successful configuration. It never changes public API behavior;
    callers only use its result to tune internal concurrent fetches.
    """

    def __init__(
        self,
        api: LimeSurveyClient,
        fetch_questions_fn: QuestionFetcher,
        fetch_properties_fn: PropertyFetcher,
    ) -> None:
        self.api = api
        self.fetch_questions = fetch_questions_fn
        self.fetch_properties = fetch_properties_fn
        self.time_benchmarks = {
            "min_time": float("inf"),
            "max_time": 0.0,
            "avg_time": 0.0,
        }

    async def analyze_survey_metrics(self) -> Dict[str, Any]:
        """Find the largest group and collect basic account-wide metrics.

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
        for survey in surveys:
            sid = int(survey["sid"])
            groups = await run_remote_call(self.api, self.api.survey.list_groups, sid)
            for group in groups:
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

    async def _get_worst_case_avg_response_time(
        self,
        survey_id: int,
        group_id: int,
    ) -> Optional[float]:
        """Measure average seconds per question for the largest group."""
        try:
            semaphore = asyncio.Semaphore(5)
            fetch_started = time.perf_counter()
            questions = await self.fetch_questions(
                survey_id,
                group_id,
                semaphore,
            )
            fetch_duration = time.perf_counter() - fetch_started
            if not questions:
                logger.warning("No questions found in benchmark group %s", group_id)
                return None

            async def measure(question: Dict[str, Any]) -> Optional[float]:
                started = time.perf_counter()
                try:
                    await asyncio.wait_for(
                        self.fetch_properties(question["qid"], semaphore),
                        timeout=30.0,
                    )
                    return time.perf_counter() - started
                except asyncio.TimeoutError:
                    logger.warning("Question %s timed out during benchmark", question["qid"])
                except Exception as exc:
                    logger.warning(
                        "Question %s failed during benchmark: %s",
                        question["qid"],
                        exc,
                    )
                return None

            measurements = await asyncio.gather(*(measure(question) for question in questions))
            durations = [duration for duration in measurements if duration is not None]
            if not durations:
                logger.warning("Benchmark produced no valid response times")
                return None
            average = (fetch_duration + sum(durations)) / len(questions)
            logger.info(
                "Benchmark group=%s questions=%s average_ms=%.2f",
                group_id,
                len(questions),
                average * 1000,
            )
            return average
        except Exception as exc:
            logger.exception("Could not benchmark group %s: %s", group_id, exc)
            return None

    def _calculate_time_score(self, response_time: float) -> float:
        """Map a measured response time to a score between zero and one."""
        average = self.time_benchmarks["avg_time"]
        if average == 0.0:
            return max(0.0, 1 - min(1, response_time / 5))
        minimum = self.time_benchmarks["min_time"]
        maximum = self.time_benchmarks["max_time"]
        if response_time <= minimum:
            return 1.0
        if response_time >= maximum:
            return 0.0
        return 1.0 - ((response_time - minimum) / (maximum - minimum))

    async def _evaluate_parameter_combination(
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

            measurements = await asyncio.gather(*(measure(question) for question in questions))
            durations = [duration for duration in measurements if duration is not None]
            if not durations:
                return None
            successful = len(durations)
            failed = len(questions) - successful
            average = (fetch_duration + sum(durations)) / len(questions)
            logger.info(
                "Optimizer sample semaphore=%s max_attempts=%s successful=%s failed=%s average_ms=%.2f",
                semaphore,
                max_attempts,
                successful,
                failed,
                average * 1000,
            )
            return {
                "success_rate": successful / len(questions),
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

    async def find_optimal_parameters(self) -> Dict[str, Any]:
        """Evaluate bounded combinations and return the best parameters."""
        started = time.perf_counter()
        try:
            metrics = await self.analyze_survey_metrics()
            if not metrics or metrics["max_group_id"] is None:
                logger.warning("No LimeSurvey groups are available for optimization")
                return self._get_default_parameters()

            cpu_count = self._get_cpu_count()
            min_semaphore = max(1, cpu_count // 2)
            max_semaphore = min(cpu_count * 2, 10)
            max_attempts_range = range(1, 4)

            baseline = await self._get_worst_case_avg_response_time(
                metrics["max_survey_id"],
                metrics["max_group_id"],
            )
            if baseline is None:
                return self._get_default_parameters()
            self.time_benchmarks = {
                "avg_time": baseline,
                "min_time": baseline * 0.5,
                "max_time": baseline * 1.5,
            }

            best: Optional[Dict[str, Any]] = None
            for semaphore in range(min_semaphore, max_semaphore + 1, 2):
                for max_attempts in max_attempts_range:
                    result = await self._evaluate_parameter_combination(
                        semaphore,
                        max_attempts,
                        metrics["max_survey_id"],
                        metrics["max_group_id"],
                    )
                    if not result:
                        continue
                    score = self._calculate_time_score(result["avg_response_time"])
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
            return self._get_default_parameters()
        except Exception as exc:
            logger.exception("Optimization failed: %s", exc)
            return self._get_default_parameters()

    def _get_default_parameters(self) -> Dict[str, Any]:
        """Return conservative parameters when live measurement is unavailable."""
        defaults = {
            "semaphore": min(self._get_cpu_count(), 5),
            "maxAttempts": 2,
            "score": 0.0,
        }
        logger.info("Using default optimizer parameters: %s", defaults)
        return defaults

    @staticmethod
    def _get_cpu_count() -> int:
        """Return the number of CPUs visible to the current process."""
        return os.cpu_count() or 1
