from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from openai import AsyncOpenAI

from opspilot.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_llm_client() -> AsyncOpenAI:
    """Singleton AsyncOpenAI client."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    logger.info("Initializing AsyncOpenAI client towards %s", settings.openai_base_url)
    _client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        max_retries=3,
        timeout=60.0,
    )
    return _client


# ---------------------------------------------------------------------------
#  Tool Call Trace (每轮工具调用的结构化记录)
# ---------------------------------------------------------------------------

class ToolCallTrace:
    """Accumulates structured traces of tool invocations during a completion."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: str,
        elapsed_ms: float,
        success: bool,
    ) -> None:
        self.records.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "result_summary": result_summary[:500],
            "elapsed_ms": round(elapsed_ms, 1),
            "success": success,
        })


# ---------------------------------------------------------------------------
#  generate_completion — 支持真实 Tool Calling
# ---------------------------------------------------------------------------

async def generate_completion(
    prompt: str,
    system_prompt: str = "You are an intelligent enterprise operations analysis agent.",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
    tool_registry: dict[str, Callable[..., Any]] | None = None,
    max_tool_rounds: int = 3,
) -> tuple[str, ToolCallTrace]:
    """
    Chat completion wrapper with **real** tool calling.

    Returns:
        (content, trace) — the final text response and a ToolCallTrace of
        all tool invocations that happened during this completion.
    """
    client = get_llm_client()
    trace = ToolCallTrace()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if tools:
        kwargs["tools"] = tools

    try:
        for _round in range(max_tool_rounds + 1):
            response = await client.chat.completions.create(**kwargs)
            message = response.choices[0].message

            if not message.tool_calls:
                # No more tool calls — return final text
                return (message.content or ""), trace

            # Process tool calls: real execution
            kwargs["messages"].append(message)

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                t0 = time.perf_counter()
                success = True
                result_content: str

                if tool_registry and fn_name in tool_registry:
                    try:
                        raw_result = tool_registry[fn_name](**fn_args)
                        result_content = json.dumps(
                            raw_result, ensure_ascii=False, default=str
                        )
                    except Exception as exc:
                        logger.error("Tool %s execution failed: %s", fn_name, exc)
                        result_content = json.dumps({
                            "error": str(exc),
                            "tool": fn_name,
                        })
                        success = False
                else:
                    result_content = json.dumps({
                        "error": f"Tool '{fn_name}' not found in registry.",
                    })
                    success = False

                elapsed_ms = (time.perf_counter() - t0) * 1000
                trace.record(
                    tool_name=fn_name,
                    arguments=fn_args,
                    result_summary=result_content[:500],
                    elapsed_ms=elapsed_ms,
                    success=success,
                )

                logger.info(
                    "Tool Call [%s] → %s (%.0fms)",
                    fn_name,
                    "OK" if success else "FAIL",
                    elapsed_ms,
                )

                kwargs["messages"].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_content,
                })

            # After processing tool calls, remove tools kwarg on last round
            # so model can finalize
            if _round == max_tool_rounds - 1:
                kwargs.pop("tools", None)

        # Exhausted rounds — do a final call without tools
        kwargs.pop("tools", None)
        final_response = await client.chat.completions.create(**kwargs)
        return (final_response.choices[0].message.content or ""), trace

    except Exception as e:
        logger.error("LLM Completion failed: %s", e)
        raise


# ---------------------------------------------------------------------------
#  Embeddings
# ---------------------------------------------------------------------------

async def get_embedding(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """Get the embedding vector for a single text."""
    client = get_llm_client()
    try:
        response = await client.embeddings.create(input=[text], model=model)
        return response.data[0].embedding
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
        return []


async def get_embeddings(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """Batch retrieve embeddings for multiple texts."""
    client = get_llm_client()
    try:
        response = await client.embeddings.create(input=texts, model=model)
        return [item.embedding for item in response.data]
    except Exception as e:
        logger.error("Batch Embedding generation failed: %s", e)
        return []


# ---------------------------------------------------------------------------
#  Reranker
# ---------------------------------------------------------------------------

async def rerank_chunks(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """Zero-Shot LLM-as-a-Judge Reranker (RankGPT style)."""
    if not chunks:
        return []

    candidates = chunks[:15]

    prompt = (
        "Please act as an objective relevance judge. "
        "Rate each chunk's relevance to the query from 0 to 10. "
        "Return a JSON object: {\"scores\": [int, ...]} in exact order.\n\n"
        f"Query: {query}\n\nChunks:\n"
    )
    for i, c in enumerate(candidates):
        text_preview = c.get("text", "")[:400].replace("\n", " ")
        prompt += f"[Chunk {i}] {text_preview}\n"

    try:
        response_text, _ = await generate_completion(
            prompt=prompt,
            system_prompt='You are a JSON-only scoring engine. Output exactly: {"scores": [int, ...]}',
            model="gpt-4o-mini",
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response_text)
        scores = data.get("scores", [])

        scored = []
        for i, c in enumerate(candidates):
            score = scores[i] if i < len(scores) else 0
            c["rerank_score"] = score
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]
    except Exception as e:
        logger.error("LLM Reranker failed, falling back to RRF order: %s", e)
        return candidates[:top_k]
