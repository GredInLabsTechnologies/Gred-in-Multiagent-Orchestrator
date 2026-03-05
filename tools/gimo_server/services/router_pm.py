import json
import logging
import re
from typing import Optional

from tools.gimo_server.ops_models import StrictContract, RepoContext
from tools.gimo_server.services.provider_service import ProviderService

logger = logging.getLogger("orchestrator.services.router_pm")

class RouterPM:
    """Product Manager Agent acting as the strict entry point for LangGraph execution.
    Translates raw user requests into JSON StrictContracts."""

    @staticmethod
    async def generate_contract(user_request_raw: str, repo_context: RepoContext) -> StrictContract:
        logger.info(f"RouterPM generating contract for request: {user_request_raw[:80]}...")
        
        # Pass 1 & 2 combined into a single strict LLM call
        system_prompt = (
            "ROL: Staff Engineer + Product Manager Técnico\n"
            "OBJETIVO: Producir SOLO JSON válido siguiendo el Schema exacto de StrictContract.\n"
            "REGLAS ESTRICTAS:\n"
            "1. NO inventar rutas, comandos ni tecnologías. Usa ÚNICAMENTE lo presente en `repo_context`.\n"
            "2. `acceptance_criteria` DEBE ser verificable empíricamente.\n"
            "3. Ante ambigüedades, añade `constraints` conservadoras y seguras.\n"
            "4. Lista explícitamente exclusiones en `out_of_scope` para evitar scope creep.\n"
            "5. Selecciona la clase de intención `intent_class` entre: feature, bugfix, refactor, chore.\n\n"
            "INPUTS:\n"
            f"- user_request_raw: {user_request_raw}\n"
            f"- repo_context (stack, commands, paths_of_interest): {repo_context.model_dump_json()}\n\n"
            "OUTPUT FORMAT: ONLY JSON compatible with this schema:\n"
            '{"objective":"...", "constraints":["..."], "acceptance_criteria":["..."], "execution":{"intent_class":"feature|bugfix|refactor|chore", "path_scope":["src/file.py"]}, "out_of_scope":["..."]}\n'
            "NO MARKDOWN CODE BLOCKS. ONLY RAW JSON TEXT."
        )

        try:
            # Using ProviderService to call LLM for contract generation
            resp = await ProviderService.static_generate(system_prompt, context={"task_type": "disruptive_planning"})
            raw = resp.get("content", "").strip()
            
            # Clean up markdown if present
            raw = re.sub(r'```(?:json)?\s*\n?', '', raw).strip()
            if raw.endswith('```'):
                raw = raw[:-3].strip()
            
            # Find JSON boundaries
            start = raw.find('{')
            end = raw.rfind('}')
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
                
            parsed = json.loads(raw)
            contract = StrictContract.model_validate(parsed)
            return contract
            
        except json.JSONDecodeError as e:
            logger.error(f"RouterPM received invalid JSON from LLM: {raw}")
            raise ValueError(f"Failed to parse LLM response into JSON: {e}")
        except Exception as e:
            logger.error(f"RouterPM contract generation failed: {str(e)}")
            raise ValueError(f"RouterPM failed to compile prompt to contract: {e}")
