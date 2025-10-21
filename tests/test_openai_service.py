import asyncio

import pytest

from nta_eval_svc.services.openai_service import OpenAIService


async def _fake_call_success(prompt: str) -> str:
    return "success"


async def _fake_call_failure(prompt: str) -> str:
    return "failure"


async def _fake_call_scores(prompt: str) -> str:
    # return sequential numbers based on presence of a marker
    return "80"


def test_build_prompt_contains_parts():
    svc = OpenAIService()
    prompt = svc.build_prompt("score", "these are the rules", "agent_output_here")
    assert "Method: score" in prompt
    assert "these are the rules" in prompt
    assert "agent_output_here" in prompt


def test_score_aggregation_average(monkeypatch):
    # monkeypatch the _call_openai to return a variety of scores
    responses = ["80", "90", "70", "60", "100"]

    async def fake_calls(prompt: str):
        # pop from the front
        return responses.pop(0)

    svc = OpenAIService(call_fn=fake_calls)
    samples, agg = svc.evaluate_criterion_sync("out", "score", "rules", samples=5)
    # aggregated average = (80+90+70+60+100)/5 = 80.0
    assert isinstance(samples, list) and len(samples) == 5
    assert "score" in agg
    assert agg["score"] == 80.0


def test_success_failure_majority_and_tie(monkeypatch):
    # Case majority success
    seq1 = ["success", "failure", "success", "success", "failure"]

    async def seq_calls1(prompt: str):
        return seq1.pop(0)

    svc1 = OpenAIService(call_fn=seq_calls1)
    samples1, agg1 = svc1.evaluate_criterion_sync("out", "success-failure", "rules", samples=5)
    assert agg1["verdict"] == "success"
    assert agg1["success_count"] == 3

    # Case tie: 2 success, 2 failure, 1 ambiguous => treated as failure
    seq2 = ["success", "failure", "success", "failure", "I am not sure"]

    async def seq_calls2(prompt: str):
        return seq2.pop(0)

    svc2 = OpenAIService(call_fn=seq_calls2)
    samples2, agg2 = svc2.evaluate_criterion_sync("out", "success-failure", "rules", samples=5)
    assert agg2["verdict"] == "failure"
