import sys
import logging
from openai import AsyncOpenAI
from opspilot.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

def get_llm_client() -> AsyncOpenAI:
    """
    Returns a singleton instance of the AsyncOpenAI client configured 
    using the application settings.
    """
    global _client
    if _client is not None:
        return _client
    
    settings = get_settings()
    
    # Initialize the client with proxy URL and provided API Key
    logger.info(f"Initializing AsyncOpenAI client towards {settings.openai_base_url}")
    _client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        max_retries=3,
        timeout=60.0,
    )
    return _client

async def generate_completion(
    prompt: str,
    system_prompt: str = "You are an intelligent enterprise operations analysis agent.",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
) -> str:
    """
    Wrapper for chat completions with optional Tool Calling loop.
    """
    client = get_llm_client()
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
            
        response = await client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        
        if message.tool_calls:
            # We support a single automatic depth loop for simplicity
            kwargs["messages"].append(message)
            for tool_call in message.tool_calls:
                # We mock the actual tool execution here, returning a trace flag
                # In full enterprise it maps to a registry.
                logger.info(f"LLM triggered Tool Call: {tool_call.function.name}")
                kwargs["messages"].append({
                    "role": "tool", 
                    "tool_call_id": tool_call.id, 
                    "content": f'{{"result": "Tool {tool_call.function.name} executed successfully. Apply this trace to your final summary."}}'
                })
            # Remove tools so it finalized the thought
            kwargs.pop("tools", None)
            final_response = await client.chat.completions.create(**kwargs)
            return final_response.choices[0].message.content or ""
            
        return message.content or ""
    except Exception as e:
        logger.error(f"LLM Completion failed: {e}")
        raise

async def get_embedding(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """
    Get the embedding vector for the provided text.
    """
    client = get_llm_client()
    try:
        response = await client.embeddings.create(
            input=[text],
            model=model
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []

async def get_embeddings(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """
    Batch retrieve embeddings for multiple text snippets.
    """
    client = get_llm_client()
    try:
        response = await client.embeddings.create(
            input=texts,
            model=model
        )
        return [item.embedding for item in response.data]
    except Exception as e:
        logger.error(f"Batch Embedding generation failed: {e}")
        return []

async def rerank_chunks(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    Zero-Shot LLM-as-a-Judge Reranker (RankGPT style).
    Scores chunks from 0-10 on query relevance and returns the top-k sorted chunks.
    """
    if not chunks:
        return []
    
    # We only take the top 15 from RRF to prevent massive context windows
    candidates = chunks[:15]
    
    prompt = f"Please act as an objective relevance judge. Rate each chunk's relevance to the query from 0 to 10. You must return a JSON object with a single key 'scores' containing an array of integers in exact order.\n\nQuery: {query}\n\nChunks:\n"
    for i, c in enumerate(candidates):
        text_preview = c.get("text", "")[:400].replace('\n', ' ')
        prompt += f"[Chunk {i}] {text_preview}\n"
        
    try:
        response_text = await generate_completion(
            prompt=prompt,
            system_prompt="You are a JSON-only scoring engine. Output exactly a JSON object: {\"scores\": [int, int, ...]}",
            model="gpt-4o-mini",
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        import json
        data = json.loads(response_text)
        scores = data.get("scores", [])
        
        scored_candidates = []
        for i, c in enumerate(candidates):
            score = scores[i] if i < len(scores) else 0
            c["rerank_score"] = score
            scored_candidates.append((score, c))
            
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for score, c in scored_candidates[:top_k]]
    except Exception as e:
        logger.error(f"LLM Reranker failed, falling back to RRF: {e}")
        return candidates[:top_k]

