from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_docs_html.py"


def test_generate_docs_html_embeds_openapi_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "openapi.json"
    output_path = tmp_path / "docs.html"

    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {
                    "title": "浅愈 API",
                    "version": "0.1.0",
                    "description": "用于测试的 API 文档",
                },
                "paths": {
                    "/ping": {
                        "get": {
                            "summary": "Ping",
                            "responses": {"200": {"description": "pong"}},
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(spec_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    html = output_path.read_text(encoding="utf-8")

    assert "<!DOCTYPE html>" in html
    assert "Redoc.init" in html
    assert "浅愈 API" in html
    assert "用于测试的 API 文档" in html
    assert "/openapi.json" not in html
    assert "fontFamily: 'Segoe UI, PingFang SC, Microsoft YaHei, sans-serif'" in html
