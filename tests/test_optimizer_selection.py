"""Synthetic timing measurements test selection independently of network latency."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from services.hybrid_optimizer import HybridOptimizer, parameter_score


def test_fast_but_unreliable_configuration_cannot_win():
    assert parameter_score({"success_rate": .94, "avg_response_time": .01}, 1) == -1
    assert parameter_score({"success_rate": .95, "avg_response_time": .5}, 1) == .95
    assert parameter_score({"success_rate": 1, "avg_response_time": .5}, 1) == 1


@pytest.mark.anyio
async def test_selection_uses_bounded_combinations_and_preserves_cancellation():
    optimizer = HybridOptimizer(None, None, None)
    optimizer.benchmark.analyze_survey_metrics = AsyncMock(return_value={"max_group_id": 2, "max_survey_id": 1})
    optimizer.benchmark.measure_combination = AsyncMock(return_value={"success_rate": 1, "avg_response_time": 1})
    result = await optimizer.find_optimal_parameters()
    assert result["semaphore"] in (2, 4, 6)
    assert result["maxAttempts"] in (1, 2)
    assert optimizer.benchmark.measure_combination.await_count == 7  # baseline plus six candidates
    optimizer.benchmark.analyze_survey_metrics.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await optimizer.find_optimal_parameters()
