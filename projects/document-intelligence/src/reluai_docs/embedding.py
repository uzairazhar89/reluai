"""Sentence embeddings on CPU: BAAI bge-small-en-v1.5 in ONNX Runtime.

384-dimensional vectors from the [CLS] token, L2-normalised, so cosine similarity is a dot
product (and pgvector's ``<=>`` cosine distance is ``1 - similarity``). Queries get the
model's retrieval instruction prefix; passages do not, as its authors recommend.

The model file is fetched at image build time from a pinned Hugging Face revision and
checked against its SHA-256 (``artifacts/manifest.yaml``). An INT8 copy can be produced with
``quantize`` (dynamic quantisation): about a quarter of the size and faster on CPU. Which
one runs is a measured choice, recorded in the project README.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from reluai_docs.wordpiece import WordPieceTokenizer

DIMENSIONS = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_FILE = "bge-small-en-v1.5.onnx"
MODEL_INT8_FILE = "bge-small-en-v1.5.int8.onnx"
TOKENIZER_FILE = "bge-small-en-v1.5.tokenizer.json"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class TextEmbedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, query: str) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: str
    revision: str
    file: str
    sha256: str
    quantized: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class OnnxEmbedder:
    """Thread-safe: ONNX Runtime sessions may be run from several threads."""

    def __init__(
        self,
        model_path: Path,
        tokenizer_path: Path,
        *,
        threads: int = 2,
        max_tokens: int = 512,
        batch_size: int = 16,
    ) -> None:
        import onnxruntime as ort

        self.tokenizer = WordPieceTokenizer.from_file(tokenizer_path)
        self.max_tokens = max_tokens
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.batch_size = batch_size
        self.quantized = "int8" in model_path.name
        self.name = f"{MODEL_NAME}{' (INT8)' if self.quantized else ''}"
        self.model_path = model_path

    def _run(self, texts: Sequence[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch(list(texts), max_length=self.max_tokens)
        feeds: dict[str, Any] = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
        }
        if "token_type_ids" in self.inputs:
            feeds["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        hidden = np.asarray(self.session.run(None, feeds)[0])  # (batch, tokens, 384)
        cls = np.asarray(hidden[:, 0, :], dtype=np.float32)
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        return np.asarray(cls / np.maximum(norms, 1e-12), dtype=np.float32)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIMENSIONS), dtype=np.float32)
        # Batch texts of similar length together: less padding, same results.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
        for start in range(0, len(order), self.batch_size):
            idx = order[start : start + self.batch_size]
            out[idx] = self._run([texts[i] for i in idx])
        return out

    def embed_query(self, query: str) -> np.ndarray:
        vector: np.ndarray = self._run([QUERY_PREFIX + query])[0]
        return vector


_cache: dict[tuple[str, int], OnnxEmbedder] = {}
_lock = threading.Lock()


def model_files(model_dir: Path) -> tuple[Path, Path] | None:
    """The model to run (INT8 if present) and its tokenizer, or None if not installed."""
    tokenizer = model_dir / TOKENIZER_FILE
    for name in (MODEL_INT8_FILE, MODEL_FILE):
        if (model_dir / name).is_file() and tokenizer.is_file():
            return model_dir / name, tokenizer
    return None


def load_embedder(model_dir: Path, *, threads: int = 2) -> OnnxEmbedder | None:
    """A shared embedder for this process, or None when the model is not installed."""
    files = model_files(model_dir)
    if files is None:
        return None
    key = (str(files[0]), threads)
    with _lock:
        if key not in _cache:
            _cache[key] = OnnxEmbedder(files[0], files[1], threads=threads)
        return _cache[key]


def quantize(model_dir: Path) -> Path:
    """Write the INT8 (dynamic, per-channel weights) copy next to the FP32 model."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    source = model_dir / MODEL_FILE
    target = model_dir / MODEL_INT8_FILE
    quantize_dynamic(source, target, weight_type=QuantType.QInt8, per_channel=True)
    return target
