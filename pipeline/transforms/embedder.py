"""Dense-ish text embeddings with a deterministic, offline default.

The default path is TF-IDF followed by TruncatedSVD (latent semantic analysis),
which is deterministic and captures lexical-semantic structure without a model
download. A sentence-transformers model is used only when explicitly enabled.
"""
import logging
import os
from typing import List, Optional

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

logger = logging.getLogger("pipeline.transforms.embedder")


class Embedder:
    def __init__(self, n_components: int = 256):
        self.n_components = n_components
        self.model = None
        if os.getenv("ENABLE_REMOTE_EMBEDDER", "false").lower() == "true":
            try:
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
                logger.info("Loaded sentence-transformers model %s", self.model)
            except Exception as exc:
                logger.info("SentenceTransformer unavailable, using TF-IDF/LSA: %s", exc)

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1))
        cleaned = [text.strip() if text and text.strip() else "untitled" for text in texts]
        if self.model:
            vectors = self.model.encode(cleaned, show_progress_bar=False)
            return normalize(np.asarray(vectors, dtype=np.float64))
        return self._lsa(cleaned)

    def _lsa(self, texts: List[str]) -> np.ndarray:
        vectorizer = TfidfVectorizer(
            max_features=40000,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
            min_df=1,
            strip_accents="unicode",
        )
        try:
            matrix = vectorizer.fit_transform(texts)
        except ValueError:
            matrix = TfidfVectorizer(max_features=1000).fit_transform(texts)
        components = max(2, min(self.n_components, matrix.shape[0] - 1, matrix.shape[1] - 1))
        if components < 2 or matrix.shape[0] < 2:
            return normalize(matrix.toarray())
        svd = TruncatedSVD(n_components=components, random_state=42)
        reduced = svd.fit_transform(matrix)
        logger.info(
            "TF-IDF/LSA embeddings: %d texts, %d features, %d components (explained %.2f)",
            matrix.shape[0],
            matrix.shape[1],
            components,
            float(svd.explained_variance_ratio_.sum()),
        )
        return normalize(reduced)
