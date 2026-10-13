"""BERT WordPiece tokenisation (uncased), as used by bge-small-en-v1.5.

A small pure-Python equivalent of the Hugging Face ``BertTokenizer`` with its default
settings (lowercase, strip accents, split CJK characters and punctuation, then greedy
longest-match WordPiece). It reads the vocabulary from the model's ``tokenizer.json``, so no
tokenizer library (and its download machinery) is needed at run time. The test suite checks
it produces the same ids as the reference implementation on the sample document.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def _is_control(ch: str) -> bool:
    if ch in "\t\n\r":
        return False
    return unicodedata.category(ch).startswith("C")


def _is_whitespace(ch: str) -> bool:
    return ch in " \t\n\r" or unicodedata.category(ch) == "Zs"


def _is_punctuation(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0x2A700 <= cp <= 0x2B73F
        or 0x2B740 <= cp <= 0x2B81F
        or 0x2B820 <= cp <= 0x2CEAF
        or 0xF900 <= cp <= 0xFAFF
        or 0x2F800 <= cp <= 0x2FA1F
    )


def basic_tokens(text: str) -> list[str]:
    """Clean, lowercase, strip accents, and split on whitespace, punctuation and CJK."""
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp in (0, 0xFFFD) or _is_control(ch):
            continue
        if _is_whitespace(ch):
            out.append(" ")
        elif _is_cjk(cp):
            out.append(f" {ch} ")
        else:
            out.append(ch)
    tokens: list[str] = []
    for raw in "".join(out).split():
        decomposed = unicodedata.normalize("NFD", raw.lower())
        word = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
        current = ""
        for ch in word:
            if _is_punctuation(ch):
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
            else:
                current += ch
        if current:
            tokens.append(current)
    return tokens


@dataclass(frozen=True, slots=True)
class Encoding:
    ids: list[int]
    attention_mask: list[int]
    type_ids: list[int]


class WordPieceTokenizer:
    def __init__(
        self,
        vocab: dict[str, int],
        *,
        unk: str = "[UNK]",
        cls: str = "[CLS]",
        sep: str = "[SEP]",
        prefix: str = "##",
        max_word_chars: int = 100,
    ) -> None:
        self.vocab = vocab
        self.unk_id = vocab[unk]
        self.cls_id = vocab[cls]
        self.sep_id = vocab[sep]
        self.prefix = prefix
        self.max_word_chars = max_word_chars
        self._cache: dict[str, list[int]] = {}

    @classmethod
    def from_file(cls, path: Path) -> WordPieceTokenizer:
        data = json.loads(path.read_text(encoding="utf-8"))
        model = data["model"]
        if model.get("type") != "WordPiece":
            raise ValueError(f"{path.name}: not a WordPiece tokenizer")
        return cls(
            {str(k): int(v) for k, v in model["vocab"].items()},
            unk=model.get("unk_token", "[UNK]"),
            prefix=model.get("continuing_subword_prefix", "##"),
            max_word_chars=int(model.get("max_input_chars_per_word", 100)),
        )

    def _word(self, word: str) -> list[int]:
        cached = self._cache.get(word)
        if cached is not None:
            return cached
        ids: list[int] = []
        if len(word) > self.max_word_chars:
            ids = [self.unk_id]
        else:
            start = 0
            while start < len(word):
                end = len(word)
                found: int | None = None
                while start < end:
                    piece = word[start:end] if start == 0 else self.prefix + word[start:end]
                    found = self.vocab.get(piece)
                    if found is not None:
                        break
                    end -= 1
                if found is None:
                    ids = [self.unk_id]  # a word that cannot be split becomes one [UNK]
                    break
                ids.append(found)
                start = end
        if len(self._cache) < 100_000:
            self._cache[word] = ids
        return ids

    def encode(self, text: str, *, max_length: int = 512) -> list[int]:
        ids: list[int] = []
        for word in basic_tokens(text):
            ids.extend(self._word(word))
        return [self.cls_id, *ids[: max_length - 2], self.sep_id]

    def encode_batch(self, texts: list[str], *, max_length: int = 512) -> list[Encoding]:
        """Encodings padded (with id 0) to the longest text in the batch."""
        encoded = [self.encode(t, max_length=max_length) for t in texts]
        width = max((len(e) for e in encoded), default=0)
        return [
            Encoding(
                ids=e + [0] * (width - len(e)),
                attention_mask=[1] * len(e) + [0] * (width - len(e)),
                type_ids=[0] * width,
            )
            for e in encoded
        ]
