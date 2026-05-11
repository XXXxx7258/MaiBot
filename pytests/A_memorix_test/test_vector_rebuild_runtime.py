from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from src.A_memorix.core.runtime import sdk_memory_kernel as kernel_module
from src.A_memorix.core.runtime.sdk_memory_kernel import SDKMemoryKernel


class _FakeEmbeddingManager:
    def __init__(self, dimension: int = 8) -> None:
        self.default_dimension = dimension

    async def _detect_dimension(self) -> int:
        return self.default_dimension

    async def encode(self, text: Any, **kwargs: Any) -> np.ndarray:
        del kwargs

        def _encode_one(raw: Any) -> np.ndarray:
            content = str(raw or "")
            vector = np.zeros(self.default_dimension, dtype=np.float32)
            for index, byte in enumerate(content.encode("utf-8")):
                vector[index % self.default_dimension] += float((byte % 17) + 1)
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vector /= norm
            return vector

        if isinstance(text, (list, tuple)):
            return np.stack([_encode_one(item) for item in text]).astype(np.float32)
        return _encode_one(text).astype(np.float32)

    async def encode_batch(self, texts: Any, **kwargs: Any) -> np.ndarray:
        return await self.encode(texts, **kwargs)


async def _fake_runtime_self_check(**kwargs: Any) -> dict[str, Any]:
    vector_store = kwargs["vector_store"]
    embedding_manager = kwargs["embedding_manager"]
    dimension = int(embedding_manager.default_dimension)
    return {
        "ok": int(vector_store.dimension) == dimension,
        "message": "ok",
        "configured_dimension": dimension,
        "requested_dimension": dimension,
        "vector_store_dimension": int(vector_store.dimension),
        "detected_dimension": dimension,
        "encoded_dimension": dimension,
        "elapsed_ms": 0.0,
        "sample_text": "test",
        "checked_at": 1_777_000_000.0,
    }


@pytest.mark.asyncio
async def test_runtime_admin_rebuild_all_vectors_replaces_existing_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_embedding_manager = _FakeEmbeddingManager(dimension=8)
    monkeypatch.setattr(
        kernel_module,
        "create_embedding_api_adapter",
        lambda **kwargs: fake_embedding_manager,
    )
    monkeypatch.setattr(kernel_module, "run_embedding_runtime_self_check", _fake_runtime_self_check)

    kernel = SDKMemoryKernel(
        plugin_root=tmp_path / "plugin_root",
        config={
            "storage": {"data_dir": str((tmp_path / "a_memorix_data").resolve())},
            "advanced": {"enable_auto_save": False},
            "embedding": {
                "dimension": fake_embedding_manager.default_dimension,
                "batch_size": 2,
                "paragraph_vector_backfill": {"enabled": False},
            },
            "retrieval": {
                "relation_vectorization": {"enabled": True},
                "sparse": {"enabled": False},
                "enable_ppr": False,
                "enable_parallel": False,
            },
        },
    )

    await kernel.initialize()
    assert kernel.metadata_store is not None
    assert kernel.vector_store is not None

    paragraph_hash = kernel.metadata_store.add_paragraph("用户喜欢蓝色围巾", source="test")
    entity_hash = kernel.metadata_store.add_entity("蓝色围巾")
    relation_hash = kernel.metadata_store.add_relation("用户", "喜欢", "蓝色围巾")
    kernel.vector_store.add(
        np.ones((1, fake_embedding_manager.default_dimension), dtype=np.float32),
        ["stale-vector"],
    )
    kernel.vector_store.save()

    preview = await kernel.memory_runtime_admin(action="rebuild_all_vectors", dry_run=True)
    assert preview["success"] is True
    assert preview["counts"] == {"paragraphs": 1, "entities": 1, "relations": 1}

    result = await kernel.memory_runtime_admin(action="rebuild_all_vectors", batch_size=2)
    assert result["success"] is True
    assert result["done"] == 3
    assert result["failed"] == 0
    assert paragraph_hash in kernel.vector_store
    assert entity_hash in kernel.vector_store
    assert relation_hash in kernel.vector_store
    assert "stale-vector" not in kernel.vector_store

    config = await kernel.memory_runtime_admin(action="get_config")
    assert config["vector_rebuild_required"] is False
    assert config["stored_vector_dimension"] == fake_embedding_manager.default_dimension

    await kernel.shutdown()
