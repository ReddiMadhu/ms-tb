"""
Centralized LLM client factory — supports OpenAI and Azure OpenAI.

Ported from db-tb pattern: single `get_llm()` entry point with
optional CachedLLM wrapper (ADR-018).

Usage in any agent:
    from app.core.llm import get_llm
    llm = get_llm(temperature=0.1)
    result = llm.invoke(prompt)
"""

import os
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

USE_LLM_CACHE = settings.use_llm_cache
# Prevent indefinite hangs on Azure/OpenAI (seen on live calc translate/judge).
LLM_REQUEST_TIMEOUT_SEC = float(os.getenv("LLM_REQUEST_TIMEOUT_SEC", "45"))


def get_llm(temperature: float = 0.1):
    """
    Returns an instance of ChatOpenAI or AzureChatOpenAI based on configuration.
    Returns None if no API key is configured.

    Priority: Azure OpenAI > OpenAI.
    If USE_LLM_CACHE is True, wraps the LLM in a CachedLLM for SHA-256 hash-based
    JSON file caching.
    """
    llm = None
    openai_api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    azure_api_key = settings.azure_openai_api_key or os.getenv("AZURE_OPENAI_API_KEY")
    timeout = LLM_REQUEST_TIMEOUT_SEC

    if azure_api_key:
        azure_endpoint = settings.azure_openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        # Azure AI Services / Models endpoint (newer style)
        if azure_endpoint and (
            "services.ai.azure.com" in azure_endpoint
            or "models.ai.azure.com" in azure_endpoint
        ):
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                api_key=azure_api_key,
                base_url=azure_endpoint,
                model=settings.azure_openai_deployment,
                temperature=temperature,
                default_headers={"api-key": azure_api_key},
                timeout=timeout,
                max_retries=1,
            )
            logger.info("Using Azure AI Services endpoint: %s", azure_endpoint)
        else:
            # Classic Azure OpenAI endpoint
            from langchain_openai import AzureChatOpenAI

            llm = AzureChatOpenAI(
                api_key=azure_api_key,
                azure_endpoint=azure_endpoint,
                azure_deployment=settings.azure_openai_deployment,
                api_version=settings.azure_openai_api_version,
                temperature=temperature,
                timeout=timeout,
                max_retries=1,
            )
            logger.info("Using Azure OpenAI endpoint: %s", azure_endpoint)
    elif openai_api_key:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            api_key=openai_api_key,
            model=settings.openai_model,
            temperature=temperature,
            timeout=timeout,
            max_retries=1,
        )
        logger.info("Using OpenAI model: %s", settings.openai_model)

    if llm and USE_LLM_CACHE:
        from app.core.cache import CachedLLM

        return CachedLLM(llm)

    return llm
