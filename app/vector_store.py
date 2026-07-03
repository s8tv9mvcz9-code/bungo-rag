"""
vector_store.py — ローカル・ハイブリッド検索（Azure AI Search のゼロコスト代替）

corpus/index.npz + corpus/meta.json を読み込み、
  - ベクトル検索: numpy 総当たりコサイン類似度
  - キーワード検索: 文字 bigram BM25（形態素解析なしで日本語に対応）
を RRF（Reciprocal Rank Fusion）で融合する。

数千〜数万チャンク規模なら総当たりで十分高速（1万件×1536次元 ≒ 60MB, 数十ms）。
返却契約は rag.py の search_chunks と同じ:
  [{"text":…, "title":…, "author":…, "style":…}, …]
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from typing import List

import numpy as np

# 既定のインデックス配置（リポジトリ直下 corpus/）
_DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus")

_WS_RE = re.compile(r"\s+")


def _bigrams(text: str) -> List[str]:
    """文字 bigram トークナイザ。空白・記号を潰してから2文字窓で切る。"""
    t = _WS_RE.sub("", text)
    return [t[i : i + 2] for i in range(len(t) - 1)] if len(t) >= 2 else [t]


class _BM25:
    """依存ゼロの最小 BM25 実装（Okapi, k1=1.5, b=0.75）。"""

    def __init__(self, docs_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_freqs = [Counter(toks) for toks in docs_tokens]
        self.doc_lens = np.array([len(toks) for toks in docs_tokens], dtype=np.float32)
        self.avgdl = float(self.doc_lens.mean()) if len(docs_tokens) else 1.0
        self.N = len(docs_tokens)
        df: Counter = Counter()
        for freqs in self.doc_freqs:
            df.update(freqs.keys())
        self.idf = {
            term: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for term, n in df.items()
        }

    def scores(self, query_tokens: List[str]) -> np.ndarray:
        out = np.zeros(self.N, dtype=np.float32)
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([f.get(term, 0) for f in self.doc_freqs], dtype=np.float32)
            denom = tf + self.k1 * (1 - self.b + self.b * self.doc_lens / self.avgdl)
            out += idf * tf * (self.k1 + 1) / np.maximum(denom, 1e-9)
        return out


class LocalVectorStore:
    """corpus/index.npz（embeddings）+ corpus/meta.json（チャンク情報）を検索する。"""

    def __init__(self, corpus_dir: str | None = None):
        d = corpus_dir or os.environ.get("CORPUS_DIR", _DEFAULT_DIR)
        npz_path = os.path.join(d, "index.npz")
        meta_path = os.path.join(d, "meta.json")
        if not (os.path.exists(npz_path) and os.path.exists(meta_path)):
            raise FileNotFoundError(
                f"ローカルインデックスが見つかりません: {npz_path} / {meta_path}。"
                "scripts/build_index.py で構築してください。"
            )
        self.embeddings = np.load(npz_path)["embeddings"].astype(np.float32)
        # 正規化済みでなければ正規化（コサイン→内積化）
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        self.embeddings /= np.maximum(norms, 1e-9)
        with open(meta_path, encoding="utf-8") as f:
            self.meta: List[dict] = json.load(f)
        if len(self.meta) != self.embeddings.shape[0]:
            raise ValueError(
                f"meta.json({len(self.meta)}) と index.npz({self.embeddings.shape[0]}) の件数不一致"
            )
        self._bm25 = _BM25([_bigrams(m["text"]) for m in self.meta])

    def search(self, query_text: str, query_vector: List[float], top: int = 5) -> List[dict]:
        """ハイブリッド検索: ベクトル順位と BM25 順位を RRF(k=60) で融合。"""
        q = np.asarray(query_vector, dtype=np.float32)
        q /= max(float(np.linalg.norm(q)), 1e-9)
        vec_scores = self.embeddings @ q
        bm_scores = self._bm25.scores(_bigrams(query_text))

        k = 60.0
        vec_rank = np.argsort(-vec_scores)
        bm_rank = np.argsort(-bm_scores)
        rrf = np.zeros(len(self.meta), dtype=np.float32)
        for rank, idx in enumerate(vec_rank):
            rrf[idx] += 1.0 / (k + rank + 1)
        # BM25 が全ゼロ（クエリ語彙がコーパスに無い）なら融合しない
        if bm_scores.max() > 0:
            for rank, idx in enumerate(bm_rank):
                rrf[idx] += 1.0 / (k + rank + 1)

        top_idx = np.argsort(-rrf)[:top]
        return [dict(self.meta[i]) for i in top_idx]


_store: LocalVectorStore | None = None


def get_store() -> LocalVectorStore:
    """プロセス内シングルトン（Streamlit の再実行でも再ロードしない）。"""
    global _store
    if _store is None:
        _store = LocalVectorStore()
    return _store


def index_exists(corpus_dir: str | None = None) -> bool:
    d = corpus_dir or os.environ.get("CORPUS_DIR", _DEFAULT_DIR)
    return os.path.exists(os.path.join(d, "index.npz")) and os.path.exists(
        os.path.join(d, "meta.json")
    )
