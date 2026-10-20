"""Per-model request budgets and document-free usage across retries/fallbacks."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings


def _extract_token_counts(usage: object) -> tuple[int, int]:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "details", None)
    if isinstance(details, dict) and details:
        if input_tokens == 0:
            input_tokens = sum(
                val
                for key, val in details.items()
                if isinstance(val, int)
                and (key.endswith("_prompt_tokens") or key == "cached_content_tokens")
            )
        if output_tokens == 0:
            output_tokens = sum(
                val
                for key, val in details.items()
                if isinstance(val, int)
                and (key.endswith("_candidates_tokens") or key == "thoughts_tokens")
            )
    return input_tokens, output_tokens


@dataclass
class ProviderUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add_tokens(self, usage: object) -> None:
        in_tokens, out_tokens = _extract_token_counts(usage)
        self.input_tokens += in_tokens
        self.output_tokens += out_tokens

    def to_api(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
        }


@dataclass
class RequestBudget:
    limit: int
    usage: ProviderUsage
    used: int = 0

    def reserve(self) -> None:
        if self.used >= self.limit:
            raise UsageLimitExceeded("O limite local de chamadas deste modelo foi atingido.")
        self.used += 1
        self.usage.requests += 1


class BudgetedModel(WrapperModel):
    """Count every non-streaming invocation before it reaches the provider.

    The extractor uses Agent.run(), never streaming. Counting at the model boundary
    covers both the agent's output retries and the extractor's transient retries,
    including invocations for which the provider reports no token usage.
    """

    def __init__(self, model: Model | str, budget: RequestBudget) -> None:
        super().__init__(model)
        self.budget = budget

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.budget.reserve()
        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters
        )
        in_tokens, out_tokens = _extract_token_counts(response.usage)
        if getattr(response.usage, "input_tokens", 0) == 0 and in_tokens > 0:
            response.usage.input_tokens = in_tokens
        if getattr(response.usage, "output_tokens", 0) == 0 and out_tokens > 0:
            response.usage.output_tokens = out_tokens
        self.budget.usage.add_tokens(response.usage)
        return response
