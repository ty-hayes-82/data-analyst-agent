"""Safety guardrail callbacks for ADK agents."""
import re
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from data_analyst_agent.logging_config import setup_logging

logger = setup_logging(__name__)


# Common PII patterns
PII_PATTERNS = {
    "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "credit_card": re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "phone": re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
}


def content_safety_filter(
    callback_context: CallbackContext,
    llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """
    Block requests containing PII or prohibited content before sending to LLM.
    
    Args:
        callback_context: ADK callback context
        llm_request: LLM request to validate
    
    Returns:
        LlmResponse with error if blocked, None to proceed
    """
    prompt_text = str(llm_request.prompt)
    
    # Check for PII
    for pii_type, pattern in PII_PATTERNS.items():
        if pattern.search(prompt_text):
            logger.warning(
                f"Blocked LLM request containing {pii_type}",
                extra={"pii_type": pii_type, "agent": callback_context.agent_name}
            )
            return LlmResponse(
                content=f"Request blocked: contains sensitive {pii_type} data",
                blocked=True
            )
    
    return None


def rate_limit_check(
    callback_context: CallbackContext,
    llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """
    Rate limit LLM calls per session.
    
    Args:
        callback_context: ADK callback context
        llm_request: LLM request
    
    Returns:
        LlmResponse with error if rate limited, None to proceed
    """
    session_state = callback_context.session.state
    rate_limit_key = "llm_call_count"
    max_calls = int(os.getenv("MAX_LLM_CALLS_PER_SESSION", "100"))
    
    call_count = session_state.get(rate_limit_key, 0)
    
    if call_count >= max_calls:
        logger.warning(
            f"Rate limit exceeded: {call_count}/{max_calls}",
            extra={"session_id": callback_context.session.id}
        )
        return LlmResponse(
            content=f"Rate limit exceeded: {max_calls} LLM calls per session",
            blocked=True
        )
    
    # Increment counter
    session_state[rate_limit_key] = call_count + 1
    return None


import os
