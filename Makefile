.PHONY: install test demo sync sync-full embeddings serve stats
install:
	python -m pip install -e '.[dev]'
test:
	python -m compileall -q src
	python -m pytest -q
demo:
	flipper-rag ingest --path knowledge/starter
sync:
	flipper-rag sync --web --crawl --max-pages 250 --depth 2
sync-full:
	flipper-rag sync --all --with-code --crawl --max-pages 350 --depth 2
embeddings:
	flipper-rag reembed
serve:
	uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000
stats:
	flipper-rag stats
