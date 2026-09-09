"""Small, flushed deployment diagnostics without exception messages or document content."""

import re

BOOTSTRAP_STAGES = frozenset(
    {
        "postgres_start",
        "postgres_ready",
        "embedding_load_start",
        "embedding_ready",
        "corpus_ready",
        "chroma_connect_start",
        "chroma_connected",
        "chroma_existing_ids_ready",
        "chroma_index_batch_start",
        "chroma_index_batch_complete",
        "chroma_ready",
        "redis_start",
        "redis_ready",
        "manifest_ready",
        "memory_released",
        "complete",
    }
)
STARTUP_PHASES = frozenset({"settings", "bootstrap", "application", "uvicorn", "entrypoint"})


def bootstrap_stage(stage: str, **counts: int) -> None:
    """Print only a fixed stage and bounded integer counts, immediately."""

    if stage not in BOOTSTRAP_STAGES or not counts.keys() <= {"batch", "batches", "children"}:
        raise ValueError("invalid bootstrap diagnostic fields")
    if any(type(value) is not int or not 0 <= value <= 1_000_000 for value in counts.values()):
        raise ValueError("invalid bootstrap diagnostic count")
    fields = "".join(f" {key}={value}" for key, value in counts.items())
    print(f"BOOTSTRAP stage={stage}{fields}", flush=True)


class DeploymentFailure(Exception):
    """Carry only safe phase/class fields across the synchronous entry-point boundary."""

    def __init__(self, phase: str, error: BaseException) -> None:
        self.phase = phase if phase in STARTUP_PHASES else "entrypoint"
        name = type(error).__name__
        self.error_type = (
            name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "Exception"
        )
        super().__init__("deployment failed")

    def report(self) -> None:
        """Never stringify the original exception, its traceback, input or connection data."""

        print(
            f"FAIL deployment startup phase={self.phase} error_type={self.error_type}",
            flush=True,
        )
