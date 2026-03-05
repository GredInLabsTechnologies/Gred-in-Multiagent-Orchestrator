import os
import re
import logging
from pathlib import Path
import subprocess

logger = logging.getLogger("orchestrator.services.diff_application_service")

class DiffApplicationService:
    SEARCH_TAG = "<<<< SEARCH"
    REPLACE_TAG = "REPLACE >>>>"
    DIVIDER_TAG = "===="

    @staticmethod
    def apply(worktree_path: str, agent_content: str) -> None:
        """Parses LLM output and applies changes to the worktree."""
        
        # Strategy 1: Search-Replace Blocks
        if DiffApplicationService.SEARCH_TAG in agent_content and DiffApplicationService.REPLACE_TAG in agent_content:
            logger.info("Detected Search-Replace format.")
            DiffApplicationService._apply_search_replace(worktree_path, agent_content)
            return
            
        # Strategy 2: Git patch (Unified Diff)
        if "diff --git" in agent_content and "--- a/" in agent_content and "+++ b/" in agent_content:
            logger.info("Detected Unified Diff format.")
            DiffApplicationService._apply_git_patch(worktree_path, agent_content)
            return

        # Strategy 3: Full file write / Artifact markdown
        logger.info("Attempting file-level write parsing.")
        DiffApplicationService._apply_file_writes(worktree_path, agent_content)

    @staticmethod
    def _is_safe_path(worktree_root: Path, target_path: Path) -> bool:
        """Prevents path traversal vulnerabilities."""
        try:
            resolved_target = target_path.resolve()
            resolved_root = worktree_root.resolve()
            return str(resolved_target).startswith(str(resolved_root))
        except Exception:
            return False

    @staticmethod
    def _extract_filepath(preceding_text: str) -> str | None:
        lines = preceding_text.split('\n')
        for line in reversed(lines):
            line = line.strip()
            if not line: continue
            match = re.search(r'([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)', line)
            if match:
                return match.group(1).replace('\\', '/').lstrip('./')
        return None

    @staticmethod
    def _apply_search_replace(worktree_path: str, agent_content: str) -> None:
        blocks = agent_content.split(DiffApplicationService.SEARCH_TAG)
        root = Path(worktree_path)
        
        for i in range(1, len(blocks)):
            block = blocks[i]
            if DiffApplicationService.DIVIDER_TAG not in block or DiffApplicationService.REPLACE_TAG not in block:
                continue
                
            preceding = blocks[i-1]
            filepath = DiffApplicationService._extract_filepath(preceding)
            
            if not filepath:
                logger.error("Could not determine filepath for search/replace block.")
                continue
                
            parts = block.split(DiffApplicationService.DIVIDER_TAG)
            search_str = parts[0].strip('\n')
            replace_str = parts[1].split(DiffApplicationService.REPLACE_TAG)[0].strip('\n')
            
            full_path = root / filepath
            if not DiffApplicationService._is_safe_path(root, full_path):
                logger.error(f"Path traversal blocked for: {filepath}")
                continue
                
            if full_path.exists():
                content = full_path.read_text(encoding='utf-8')
                if search_str in content:
                    content = content.replace(search_str, replace_str)
                    full_path.write_text(content, encoding='utf-8')
                    logger.info(f"Applied search/replace to {filepath}")
                else:
                    logger.error(f"Search string not found in {filepath} (Exact match failed)")

    @staticmethod
    def _apply_git_patch(worktree_path: str, agent_content: str) -> None:
        import tempfile
        patch_text = agent_content
        match = re.search(r'```(?:diff|patch)?\n(diff --git.*?)\n```', agent_content, re.DOTALL)
        if match:
            patch_text = match.group(1)
            
        with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, encoding='utf-8') as f:
            f.write(patch_text)
            patch_file = f.name
            
        try:
            result = subprocess.run(
                ['git', 'apply', patch_file],
                cwd=worktree_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                logger.info("Successfully applied git patch.")
            else:
                logger.error(f"Git apply failed: {result.stderr}")
        finally:
            os.remove(patch_file)

    @staticmethod
    def _apply_file_writes(worktree_path: str, agent_content: str) -> None:
        parts = agent_content.split('```')
        root = Path(worktree_path)
        
        for i in range(1, len(parts), 2):
            code_block = parts[i]
            preceding_text = parts[i-1]
            
            lines = code_block.split('\n', 1)
            if len(lines) < 2: continue
            content = lines[1]
            
            filepath = DiffApplicationService._extract_filepath(preceding_text)
            if filepath:
                full_path = root / filepath
                if not DiffApplicationService._is_safe_path(root, full_path):
                    logger.error(f"Path traversal blocked for: {filepath}")
                    continue
                    
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding='utf-8')
                    logger.info(f"Wrote file {filepath}")
                except Exception as e:
                    logger.error(f"Failed to write file {filepath}: {e}")
