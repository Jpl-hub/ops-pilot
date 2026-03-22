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
    response_format: dict | None = None
) -> str:
    """
    Basic wrapper for chat completions.
    """
    client = get_llm_client()
    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
            
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        raise e
