"""Demo worker: adds /version endpoint to the sample FastAPI app."""
import sys
from pathlib import Path

repo = Path(sys.argv[1])
main_py = repo / "app" / "main.py"

if "/version" in main_py.read_text():
    print("Already has /version endpoint")
    sys.exit(0)

main_py.write_text(
    'from pathlib import Path\n'
    '\n'
    'import tomllib\n'
    'from fastapi import FastAPI\n'
    '\n'
    'app = FastAPI(title="Sample FastAPI App")\n'
    '\n'
    'with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:\n'
    '    _version = tomllib.load(f)["project"]["version"]\n'
    '\n'
    '\n'
    '@app.get("/health")\n'
    'def health() -> dict[str, str]:\n'
    '    return {"status": "ok"}\n'
    '\n'
    '\n'
    '@app.get("/version")\n'
    'def version() -> dict[str, str]:\n'
    '    return {"version": _version}\n'
)

(repo / "tests" / "test_version.py").write_text(
    'from fastapi.testclient import TestClient\n'
    'from app.main import app\n'
    '\n'
    'client = TestClient(app)\n'
    '\n'
    '\n'
    'def test_version_endpoint() -> None:\n'
    '    resp = client.get("/version")\n'
    '    assert resp.status_code == 200\n'
    '    assert "version" in resp.json()\n'
)

print("Added /version endpoint and test_version.py")
