from __future__ import annotations

from pathlib import Path

import yaml

from .models import PipelineContext


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_context(root: Path | None = None) -> PipelineContext:
    project_root = Path(root or ".").resolve()
    config_root = project_root / "project" / "config"
    pipeline_config = load_yaml(config_root / "pipeline.yaml")
    cleaning_rules = load_yaml(config_root / "cleaning_rules.yaml")
    obsidian_schema = load_yaml(config_root / "obsidian_schema.yaml")
    return PipelineContext(
        project_root=project_root,
        work_root=Path(pipeline_config["work_root"]),
        vault_root=Path(pipeline_config["vault_root"]),
        logs_root=Path(pipeline_config["logs_root"]),
        book_manifest=Path(pipeline_config["book_manifest"]),
        pipeline_config=pipeline_config,
        cleaning_rules=cleaning_rules,
        obsidian_schema=obsidian_schema,
    )
