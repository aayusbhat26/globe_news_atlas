"""Storage layer: local Parquet lake mirrored to a Hugging Face dataset repo.

Exports are lazy so light modules (search index, JSON helpers) can be imported
without pulling in pandas/pyarrow. ``from pipeline.storage import
LocalParquetStore`` continues to work unchanged.
"""
from typing import Any

__all__ = ["LocalParquetStore", "HuggingFaceSync"]


def __getattr__(name: str) -> Any:
    if name == "LocalParquetStore":
        from .parquet_store import LocalParquetStore

        return LocalParquetStore
    if name == "HuggingFaceSync":
        from .huggingface_sync import HuggingFaceSync

        return HuggingFaceSync
    raise AttributeError(name)
