import hashlib
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


class DeterministicLLM:
    """
    Layer 4: Maximize determinism in LLM calls.
    Ensures that identical prompts result in identical seeds for reproducible outputs.
    """

    def __init__(self, api_key: str):
        """
        Initialize the deterministic LLM client.

        Args:
            api_key (str): The OpenAI API key.
        """
        if not api_key:
            raise ValueError("API key must be provided")

        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4-turbo-preview"
        self.default_max_tokens = 2000

    def call_with_max_determinism(
        self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Call OpenAI API with maximum determinism settings.

        Args:
            system_prompt (str): The system instructions.
            user_prompt (str): The user input or code to analyze.
            max_tokens (int, optional): Max tokens for response. Defaults to 2000.

        Returns:
            Dict: {
                'response': str,
                'usage': dict,
                'fingerprint': str,
                'seed': int,
                'model': str
            }
        """
        tokens_to_use = max_tokens if max_tokens is not None else self.default_max_tokens

        # Generate deterministic seed from input prompts
        # Using SHA256 to create a unique fingerprint for the prompt combination
        input_string = (system_prompt + user_prompt).encode("utf-8")
        input_hash = hashlib.sha256(input_string).hexdigest()

        # Convert first 8 chars of hex to int for a 32-bit seed
        seed = int(input_hash[:8], 16) % (2**31)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,  # Maximum determinism
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                max_tokens=tokens_to_use,
                seed=seed,  # Reproducibility (GPT-4 Turbo+)
                n=1,  # Single response
            )

            result = {
                "response": response.choices[0].message.content,
                "usage": response.usage.model_dump(),
                "fingerprint": response.system_fingerprint,
                "seed": seed,
                "model": self.model,
            }
            return result

        except Exception as e:
            logger.error(f"LLM API call failed: {str(e)}")
            # Fail-safe: return error info with DENY action
            return {
                "error": str(e),
                "action": "DENY",
                "reason": f"API call failed: {type(e).__name__}",
            }


if __name__ == "__main__":
    # Example usage in docstring/main block for reference
    """
    Example usage:
    llm = DeterministicLLM(api_key="your-key")
    result = llm.call_with_max_determinism(
        system_prompt="You are a helper.",
        user_prompt="Say hello."
    )
    print(result['response'])
    """
    pass
