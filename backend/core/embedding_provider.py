"""An explicit OpenAI-compatible embedding provider for Chroma collections."""
import os
import httpx

class ConfiguredEmbeddings:
    def __init__(self):
        self._key = os.environ["EMBEDDING_API_KEY"]
        self._url = os.environ["EMBEDDING_BASE_URL"].rstrip("/") + "/embeddings"
        self._model = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
        self._dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

    def __call__(self, input):
        vectors = []
        for start in range(0, len(input), 10):
            response = httpx.post(self._url,
                headers={"Authorization": "Bearer " + self._key},
                json={"model": self._model, "input": list(input[start:start+10]),
                      "dimensions": self._dimensions}, timeout=60)
            if response.status_code != 200:
                # Provider response bodies can contain credentials or user content.
                raise RuntimeError(f"Embedding provider returned HTTP {response.status_code}")
            batch = sorted(response.json()["data"], key=lambda item: item["index"])
            if len(batch) != len(input[start:start+10]):
                raise ValueError("Embedding response count mismatch")
            for item in batch:
                vector = item["embedding"]
                if len(vector) != self._dimensions:
                    raise ValueError("Embedding response dimension mismatch")
                vectors.append(vector)
        return vectors

def configured_embeddings():
    # Empty kwargs preserve Chroma's original local MiniLM default.
    if os.getenv("EMBEDDING_API_KEY"):
        return {"embedding_function": ConfiguredEmbeddings()}
    return {}
