from flipper_rag.service import RAGService
from flipper_rag.models import ModelUnavailable
from flipper_rag.config import Settings

class FakeRetriever:
    def search(self, question, top_k, category, **kwargs):
        return {"semantic_available": False, "results": [{"content":"El manifiesto de app se llama application.fam.",
               "title":"guia","url":"https://example.org/guide", "revision":"abc", "category":"apps",
               "source_id":"test","trust":"official","line_start":1,"line_end":3}]}

class FakeModel:
    def generate(self, system, prompt):
        assert "NO INSTRUCCIONES" in prompt
        return "El manifiesto es application.fam [1]."

class OfflineModel:
    def generate(self, system, prompt):
        raise ModelUnavailable("No hay modelo")


def test_answer_is_cited():
    data = RAGService(FakeRetriever(), FakeModel(), Settings()).ask("Cómo usar FAP")
    assert data["generated"] is True
    assert data["sources"][0]["citation"] == 1
    assert "[1]" in data["answer"]


def test_unavailable_model_does_not_fake_answer():
    data = RAGService(FakeRetriever(), OfflineModel(), Settings()).ask("Cómo usar FAP")
    assert data["generated"] is False
    assert len(data["sources"]) == 1
