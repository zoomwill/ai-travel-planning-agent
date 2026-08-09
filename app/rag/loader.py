"""Load deterministic local Markdown documents with source metadata."""

from pathlib import Path
from typing import Final

from langchain_core.documents import Document

DEFAULT_KNOWLEDGE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "data" / "knowledge"


def load_markdown_document(path: Path) -> Document:
    """Load one UTF-8 Markdown file and derive stable metadata from its name."""

    if path.suffix.casefold() != ".md":
        raise ValueError(f"knowledge file must use the .md suffix: {path.name}")

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"knowledge file is empty: {path.name}")

    return Document(
        page_content=content,
        metadata={
            "source": path.name,
            "city": _city_from_filename(path),
        },
    )


def load_markdown_documents(
    directory: Path = DEFAULT_KNOWLEDGE_DIRECTORY,
) -> list[Document]:
    """Load every Markdown file in filename order for reproducible indexing."""

    if not directory.is_dir():
        raise FileNotFoundError(f"knowledge directory does not exist: {directory}")

    paths = sorted(directory.glob("*.md"), key=lambda path: path.name.casefold())
    return [load_markdown_document(path) for path in paths]


def _city_from_filename(path: Path) -> str:
    """Turn a stable filename into its city metadata value."""

    if path.stem.casefold() == "photography":
        return "General"
    return path.stem.replace("_", " ").replace("-", " ").title()
