"""WordPiece tokenisation, checked against hand-worked BERT behaviour on a tiny vocabulary.

The real vocabulary is compared with the reference implementation in
``test_real_sample.py`` when the model files are installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reluai_docs.wordpiece import WordPieceTokenizer, basic_tokens

VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "the", "refund", "##s", "un", "##aff", "##able",
         "cafe", "naive", ",", ".", "!", "中", "2024", "-", "a", "##i"]  # fmt: skip


@pytest.fixture
def tok(tmp_path: Path) -> WordPieceTokenizer:
    path = tmp_path / "tokenizer.json"
    path.write_text(
        json.dumps(
            {
                "model": {
                    "type": "WordPiece",
                    "vocab": {t: i for i, t in enumerate(VOCAB)},
                    "unk_token": "[UNK]",
                    "continuing_subword_prefix": "##",
                    "max_input_chars_per_word": 100,
                }
            }
        )
    )
    return WordPieceTokenizer.from_file(path)


def test_basic_tokens() -> None:
    assert basic_tokens("Café NAÏVE, refunds!") == ["cafe", "naive", ",", "refunds", "!"]
    assert basic_tokens("e-mail\u00a0x\x00y") == ["e", "-", "mail", "xy"]  # NUL dropped
    assert basic_tokens("ab中cd") == ["ab", "中", "cd"]
    assert basic_tokens("“quoted”") == ["“", "quoted", "”"]


def test_wordpiece_ids(tok: WordPieceTokenizer) -> None:
    ids = tok.encode("The refunds, unaffable cafe!")
    words = [VOCAB[i] for i in ids]
    assert words == ["[CLS]", "the", "refund", "##s", ",", "un", "##aff", "##able", "cafe", "!",
                     "[SEP]"]  # fmt: skip
    # A word that cannot be split becomes a single [UNK].
    assert [VOCAB[i] for i in tok.encode("zebra")] == ["[CLS]", "[UNK]", "[SEP]"]


def test_truncation_and_padding(tok: WordPieceTokenizer) -> None:
    assert len(tok.encode("the " * 600, max_length=512)) == 512
    batch = tok.encode_batch(["the", "the refund"])
    assert [len(e.ids) for e in batch] == [4, 4]
    assert batch[0].ids == [2, 4, 3, 0]
    assert batch[0].attention_mask == [1, 1, 1, 0]
    assert batch[1].type_ids == [0, 0, 0, 0]


def test_rejects_other_tokenizers(tmp_path: Path) -> None:
    path = tmp_path / "bpe.json"
    path.write_text(json.dumps({"model": {"type": "BPE", "vocab": {}}}))
    with pytest.raises(ValueError, match="WordPiece"):
        WordPieceTokenizer.from_file(path)
