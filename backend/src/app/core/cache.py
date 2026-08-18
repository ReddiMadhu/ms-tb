"""
LLM response caching layer — SHA-256 hash-based JSON file cache.

Ported from db-tb pattern (ADR-018).
Wraps LangChain Chat Models to intercept .invoke() and
.with_structured_output() calls for transparent caching.
"""

import concurrent.futures
import hashlib
import json
import logging
import os
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(settings.llm_cache_dir, "llm_cache.json")


class CachedAIMessage:
    """Mock object to simulate LangChain's AIMessage structure."""

    def __init__(self, content: str):
        self.content = content


class CachedStructuredRunnable:
    """Wraps the Runnable returned by with_structured_output to support caching."""

    def __init__(self, base_runnable, cache_llm, schema):
        self.base_runnable = base_runnable
        self.cache_llm = cache_llm
        self.schema = schema

    def invoke(self, input_data: Any) -> Any:
        if isinstance(input_data, str):
            prompt_str = input_data
        elif hasattr(input_data, "to_string"):
            prompt_str = input_data.to_string()
        else:
            try:
                prompt_str = str(input_data)
            except Exception:
                return self.base_runnable.invoke(input_data)

        prompt_hash = self.cache_llm._get_hash(prompt_str)
        structured_hash = f"struct_{prompt_hash}"

        if structured_hash in self.cache_llm.cache:
            cached_data = self.cache_llm.cache[structured_hash]
            if self.schema and hasattr(self.schema, "parse_obj"):
                return self.schema.parse_obj(cached_data)
            elif self.schema and hasattr(self.schema, "model_validate"):
                return self.schema.model_validate(cached_data)
            return cached_data

        response = self.base_runnable.invoke(input_data)
        if response:
            if hasattr(response, "dict"):
                serialized = response.dict()
            elif hasattr(response, "model_dump"):
                serialized = response.model_dump()
            else:
                serialized = response
            self.cache_llm.cache[structured_hash] = serialized
            self.cache_llm._save_cache()

        return response


_cache_memory = None


class CachedLLM:
    """
    Wraps a LangChain Chat Model to intercept .invoke() calls and cache
    responses in a JSON file. Uses SHA-256 hash of the prompt as the key.

    Also supports .with_structured_output() via CachedStructuredRunnable.
    """

    def __init__(self, base_llm):
        self.base_llm = base_llm
        global _cache_memory
        if _cache_memory is None:
            _cache_memory = self._load_cache()
        self.cache = _cache_memory

    def with_structured_output(self, schema, **kwargs):
        if hasattr(self.base_llm, "with_structured_output"):
            base_runnable = self.base_llm.with_structured_output(schema, **kwargs)
            return CachedStructuredRunnable(base_runnable, self, schema)
        return self

    def _load_cache(self) -> dict:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.warning("Failed to load LLM cache from %s", CACHE_FILE)
        return {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to save LLM cache to %s", CACHE_FILE)

    def _get_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def invoke(self, input_data: Any) -> Any:
        if isinstance(input_data, str):
            prompt_str = input_data
        elif hasattr(input_data, "to_string"):
            prompt_str = input_data.to_string()
        else:
            try:
                prompt_str = str(input_data)
            except Exception:
                return self.base_llm.invoke(input_data)

        prompt_hash = self._get_hash(prompt_str)
        if prompt_hash in self.cache:
            logger.debug("LLM cache hit for hash %s", prompt_hash[:12])
            return CachedAIMessage(content=self.cache[prompt_hash])

        # Hard wall-clock timeout so a stuck Azure/OpenAI socket cannot freeze the pipeline.
        from app.core.llm import LLM_REQUEST_TIMEOUT_SEC

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(self.base_llm.invoke, input_data)
            try:
                response = fut.result(timeout=LLM_REQUEST_TIMEOUT_SEC + 5)
            except concurrent.futures.TimeoutError as e:
                raise TimeoutError(
                    f"LLM invoke exceeded {LLM_REQUEST_TIMEOUT_SEC + 5}s"
                ) from e

        if hasattr(response, "content"):
            self.cache[prompt_hash] = response.content
            self._save_cache()

        return response
