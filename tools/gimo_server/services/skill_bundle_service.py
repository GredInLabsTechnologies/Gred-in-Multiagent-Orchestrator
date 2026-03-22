from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path

from .skills_service import SKILLS_LOCK, SkillCreateRequest, SkillDefinition, SkillsService
from filelock import FileLock

logger = logging.getLogger("orchestrator.skills.bundle")


MANIFEST_FILENAME = "skill.json"
GRAPH_FILENAME = "graph.json"


class SkillBundleService:
    """Service to handle export and import of Skill Bundles (AI Containers base)."""

    @classmethod
    def export_bundle(cls, skill_id: str, output_path: Path) -> Path:
        """
        Exports a skill to a zip bundle containing manifest and graph.
        """
        skill = SkillsService.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill {skill_id} not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 1. skill.json (metadata/manifest)
            manifest = {
                "version": "1.0",
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "command": skill.command,
                "replace_graph": skill.replace_graph,
            }
            (tmpdir_path / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # 2. graph.json (nodes & edges)
            graph = {
                "nodes": skill.nodes,
                "edges": skill.edges,
            }
            (tmpdir_path / GRAPH_FILENAME).write_text(json.dumps(graph, indent=2), encoding="utf-8")

            # Create zip bundle
            if output_path.suffix != ".zip":
                output_path = output_path.with_suffix(".zip")

            output_path.parent.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(tmpdir_path / MANIFEST_FILENAME, MANIFEST_FILENAME)
                zipf.write(tmpdir_path / GRAPH_FILENAME, GRAPH_FILENAME)

            logger.info("Skill %s exported to %s", skill_id, output_path)
            return output_path

    @classmethod
    def install_bundle(cls, bundle_path: Path, overwrite: bool = False) -> SkillDefinition:
        """
        Installs a skill from a zip bundle.
        If overwrite is True, it will delete existing skill with same command if found.
        """
        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle not found: {bundle_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir).resolve()
            with zipfile.ZipFile(bundle_path, "r") as zipf:
                for member in zipf.infolist():
                    member_path = (tmpdir_path / member.filename).resolve()
                    if not member_path.is_relative_to(tmpdir_path):
                        raise ValueError(f"Dangerous zip member detected: {member.filename}")
                zipf.extractall(tmpdir_path)

            manifest_path = tmpdir_path / MANIFEST_FILENAME
            graph_path = tmpdir_path / GRAPH_FILENAME

            if not manifest_path.exists() or not graph_path.exists():
                raise ValueError(f"Invalid bundle: missing {MANIFEST_FILENAME} or {GRAPH_FILENAME}")

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse bundle files: {e}")

            command = manifest.get("command")
            if not command:
                raise ValueError("Bundle manifest missing command")

            with FileLock(SKILLS_LOCK):
                # Check if skill with same command exists
                existing_skills = SkillsService.list_skills()
                existing_skill = next((s for s in existing_skills if s.command == command), None)

                if existing_skill:
                    if overwrite:
                        logger.info("Overwriting existing skill for command %s", command)
                        SkillsService.delete_skill(existing_skill.id, use_lock=False)
                    else:
                        raise ValueError(f"Skill with command {command} already exists. Use overwrite=True if needed.")

                req = SkillCreateRequest(
                    name=manifest.get("name", "Imported Skill"),
                    description=manifest.get("description", ""),
                    command=command,
                    replace_graph=manifest.get("replace_graph", False),
                    nodes=graph.get("nodes", []),
                    edges=graph.get("edges", []),
                )

                skill = SkillsService.create_skill(req, use_lock=False)

            logger.info("Skill installed from bundle: %s (%s)", skill.name, skill.id)
            return skill
