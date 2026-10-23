import unittest
from types import SimpleNamespace

from rag.embeddings import EmbeddingError, SentenceEmbeddingProvider


class EncoderResult:
    def __init__(self, vectors):
        self.vectors = vectors

    def tolist(self):
        return self.vectors


def provider_with_result(vectors):
    provider = SentenceEmbeddingProvider.__new__(SentenceEmbeddingProvider)
    provider.max_tokens = 10
    provider.dimension = 2
    provider.batch_size = 2
    provider.model = SimpleNamespace(
        tokenizer=SimpleNamespace(encode=lambda text, **kwargs: list(range(len(text) + 2))),
        encode=lambda texts, **kwargs: EncoderResult(vectors),
    )
    return provider


class EmbeddingValidationTest(unittest.TestCase):
    def test_overlong_inputs_fail_before_encoder_instead_of_truncating(self):
        provider = provider_with_result([[1.0, 0.0]])
        with self.assertRaisesRegex(EmbeddingError, "Re-chunk"):
            provider.embed(["x" * 9])
        self.assertEqual(provider.count_tokens("hello"), 7)

    def test_empty_bad_shape_nonfinite_and_unnormalized_vectors(self):
        for vectors in ([], [[1.0]], [[float("nan"), 0.0]], [[0.0, 0.0]], [[2.0, 0.0]]):
            with self.subTest(vectors=vectors), self.assertRaises(EmbeddingError):
                provider_with_result(vectors).embed(["hello"])
        self.assertEqual(provider_with_result([]).embed([]), [])
        self.assertEqual(provider_with_result([[1.0, 0.0]]).embed(["hello"]), [[1.0, 0.0]])

    def test_model_revision_must_be_pinned_before_loading_any_dependency(self):
        with self.assertRaisesRegex(EmbeddingError, "pinned"):
            SentenceEmbeddingProvider(model_id="test/model", revision="main", cache_dir="unused")


if __name__ == "__main__":
    unittest.main()
