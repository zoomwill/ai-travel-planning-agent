"""Versioned local P10 manifest used by BM25 and Redis fallback."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from app.rag.models import ChildChunk, ParentDocument, RagIndexManifest

GENERATED_RAG_ROOT: Final = Path(__file__).resolve().parents[2] / "data" / "generated" / "rag"


@dataclass(frozen=True, slots=True)
class ManifestPaths:
    """The three generated JSON files belonging to one pipeline version."""

    directory: Path
    parents: Path
    children: Path
    manifest: Path


@dataclass(frozen=True, slots=True)
class LoadedRagManifest:
    """Validated local parent/child corpus and its metadata summary."""

    metadata: RagIndexManifest
    parents: tuple[ParentDocument, ...]
    children: tuple[ChildChunk, ...]


def manifest_paths(pipeline_version: str) -> ManifestPaths:
    """Return versioned paths without creating directories during import."""

    directory = GENERATED_RAG_ROOT / pipeline_version
    return ManifestPaths(
        directory=directory,
        parents=directory / "parents.json",
        children=directory / "children.json",
        manifest=directory / "manifest.json",
    )


def write_rag_manifest(
    metadata: RagIndexManifest,
    parents: list[ParentDocument],
    children: list[ChildChunk],
) -> ManifestPaths:
    """Write deterministic pretty JSON files for explicit indexing commands."""

    paths = manifest_paths(metadata.pipeline_version)
    paths.directory.mkdir(parents=True, exist_ok=True)
    _write_json(paths.parents, [parent.model_dump(mode="json") for parent in parents])
    _write_json(paths.children, [child.model_dump(mode="json") for child in children])
    _write_json(paths.manifest, metadata.model_dump(mode="json"))
    return paths


def load_rag_manifest(pipeline_version: str) -> LoadedRagManifest:
    """Read and strictly validate a locally generated manifest."""

    paths = manifest_paths(pipeline_version)
    metadata = RagIndexManifest.model_validate_json(paths.manifest.read_text(encoding="utf-8"))
    parents = TypeAdapter(list[ParentDocument]).validate_json(
        paths.parents.read_text(encoding="utf-8")
    )
    children = TypeAdapter(list[ChildChunk]).validate_json(
        paths.children.read_text(encoding="utf-8")
    )
    if metadata.parent_count != len(parents) or metadata.child_count != len(children):
        raise ValueError("manifest counts do not match parent and child files")
    return LoadedRagManifest(metadata, tuple(parents), tuple(children))


def _write_json(path: Path, value: object) -> None:
    """Write stable UTF-8 JSON with a trailing newline."""

    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
