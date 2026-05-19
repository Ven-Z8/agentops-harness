.PHONY: run test lint bench docker demo

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
