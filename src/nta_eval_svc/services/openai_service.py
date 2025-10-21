from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, List, Optional, Tuple

import yaml

from nta_eval_svc.config import config as app_config

logger = logging.getLogger(__name__)


class OpenAIService:
    """Service to build prompts and call OpenAI concurrently.

    Usage:
        svc = OpenAIService(client=client)  # optional client for real calls
        result = svc.evaluate_criterion_sync(agent_output, method, rules, samples=5)

    If client is not provided and OPENAI_API_KEY is not set, the service will
    fall back to deterministic simulated responses (for tests / offline runs).
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        model: Optional[str] = None,
        call_fn: Optional[Callable[[str], asyncio.Future]] = None,
    ) -> None:
        # client is an OpenAI client instance (optional, for production calls)
        self.client = client
        self.model = model or app_config.OPENAI_MODEL
        # call_fn is primarily for tests to inject an async function that returns a raw string
        self._external_call = call_fn

    def build_prompt(self, method: str, rules: Any, agent_output: Optional[str]) -> str:
        """Construct a clear prompt for the OpenAI model.

        The prompt includes the evaluation method, human-readable rules, and the
        agent's output to be evaluated. The model should respond with a concise
        verdict or numeric score followed optionally by a rationale. Example:

        Prompt example:
        Evaluate the following agent output according to these rules.
        Method: score (0-100)
        Rules: <rules>
        Agent Output:
        <agent_output>

        Please return only the score (0-100) optionally followed by a short rationale.
        """
        rules_text = rules
        if not isinstance(rules_text, str):
            try:
                rules_text = yaml.safe_dump(rules_text)
            except Exception:
                rules_text = str(rules_text)
        agent_output = (agent_output or "").strip()

        prompt = (
            "You are an objective evaluator.\n"
            "Evaluate the following agent output using the rules below.\n\n"
            f"Method: {method}\n\n"
            "Rules:\n"
            f"{rules_text}\n\n"
            "Agent Output:\n"
            f"{agent_output}\n\n"
            "Instructions: Provide your response in plain text. For method 'score', "
            "return a single numeric score between 0 and 100 optionally followed by a brief rationale. "
            "For method 'success-failure', return either 'success' or 'failure' and an optional brief rationale."
        )
        return prompt

    async def _call_openai(self, prompt: str) -> str:
        """Make a single async OpenAI call and return raw text.

        If an injected call function exists, it will be invoked (tests). If a
        client exists, attempt a real API call. Otherwise, return a deterministic
        simulated response to keep offline tests stable.
        """
        try:
            if self._external_call is not None:
                # call_fn should be an async callable returning str
                return await self._external_call(prompt)

            if self.client is not None:
                # Try to use a common OpenAI python client pattern. Use asyncio.to_thread
                # to avoid blocking if client's call is synchronous.
                def sync_call() -> str:
                    try:
                        # The exact API may vary by openai version; attempt a reasonably common call
                        resp = self.client.chat.completions.create(
                            model=self.model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0,
                        )
                        # try to extract text from common response shapes
                        if hasattr(resp, "choices") and resp.choices:
                            return getattr(resp.choices[0].message, "content", "").strip() or str(resp)
                        return str(resp)
                    except Exception as e:  # pragma: no cover - defensive
                        logger.error("OpenAI sync call failed", exc_info=True)
                        raise

                return await asyncio.to_thread(sync_call)

            # No client and no external call: deterministic simulated fallback
            # If prompt asks for score, return '50' else 'failure'
            low_prompt = prompt.lower()
            if "method: score" in low_prompt:
                return "50"
            return "failure"
        except Exception as e:
            logger.error("_call_openai failed", exc_info=True)
            raise

    async def evaluate_criterion(self, agent_output: Optional[str], method: str, rules: Any, samples: int = 5) -> Tuple[List[dict], dict]:
        """Asynchronously perform `samples` OpenAI calls concurrently and aggregate.

        Returns a tuple (samples_list, aggregated_result).
        samples_list: list of {raw: str, parsed: Any}
        aggregated_result: dict describing aggregated score or verdict
        """
        prompt = self.build_prompt(method, rules, agent_output)

        # Create coroutines for concurrent calls
        coros = [self._call_openai(prompt) for _ in range(samples)]
        try:
            raw_responses = await asyncio.gather(*coros, return_exceptions=False)
        except Exception as e:
            logger.error("OpenAI concurrent calls failed", exc_info=True)
            raise

        samples_out: List[dict] = []
        parsed_values: List[Any] = []

        for raw in raw_responses:
            raw_text = raw if isinstance(raw, str) else str(raw)
            parsed = None
            try:
                if method == "score":
                    # extract numeric
                    m = re.search(r"(\d+(?:\.\d+)?)", raw_text)
                    if m:
                        val = float(m.group(1))
                        val = max(0.0, min(100.0, val))
                        parsed = round(val, 2)
                    else:
                        # fallback to 0
                        parsed = 0.0
                else:  # success-failure
                    low = raw_text.lower()
                    if "success" in low and "failure" not in low:
                        parsed = "success"
                    elif "failure" in low and "success" not in low:
                        parsed = "failure"
                    else:
                        # ambiguous => failure by default
                        parsed = "failure"
            except Exception:
                logger.error("parsing response failed", exc_info=True)
                parsed = "failure" if method != "score" else 0.0

            samples_out.append({"raw": raw_text, "parsed": parsed})
            parsed_values.append(parsed)

        # Aggregation
        if method == "score":
            nums = [float(p) for p in parsed_values]
            avg = round((sum(nums) / len(nums)) if nums else 0.0, 1)
            aggregated = {"score": avg}
        else:
            success_count = sum(1 for p in parsed_values if p == "success")
            failure_count = sum(1 for p in parsed_values if p == "failure")
            # majority vote, tie => failure
            verdict = "success" if success_count > failure_count else "failure"
            aggregated = {"verdict": verdict, "success_count": success_count, "failure_count": failure_count}

        return samples_out, aggregated

    def evaluate_criterion_sync(self, agent_output: Optional[str], method: str, rules: Any, samples: int = 5) -> Tuple[List[dict], dict]:
        """Synchronous wrapper for evaluate_criterion suitable for sync callers.

        Uses asyncio.run internally. Exceptions are propagated.
        """
        try:
            return asyncio.run(self.evaluate_criterion(agent_output, method, rules, samples=samples))
        except Exception as e:
            logger.error("evaluate_criterion_sync failed", exc_info=True)
            raise
