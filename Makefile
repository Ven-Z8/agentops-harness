.PHONY: run test lint bench docker demo frontend-test showcase-import showcase showcase-check

run:
	uv run --extra dev agentops run --repo examples/sample_fastapi_app --task "Add request logging middleware"

test:
	uv run --extra dev pytest -q

lint:
	uv run --extra dev ruff check .

bench:
	uv run --extra dev python scripts/benchmark.py

docker:
	docker build -t agentops-harness .

demo:
	uv run --extra dev agentops scan --repo examples/sample_fastapi_app
	uv run --extra dev agentops run --repo examples/sample_fastapi_app --task "Add request logging middleware"

frontend-test:
	node --test web/tests/*.test.js

showcase-import:
	uv run --extra dev python scripts/showcase.py --import-only

showcase:
	uv run --extra dev python scripts/showcase.py

showcase-check: showcase-import frontend-test
	uv run --extra dev python -m pytest -q tests/test_showcase.py tests/test_cockpit.py
