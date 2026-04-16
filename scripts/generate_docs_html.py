from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a single-file ReDoc HTML page from an OpenAPI spec.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Path to a local OpenAPI JSON file.")
    source.add_argument("--url", help="URL of an OpenAPI JSON document.")
    parser.add_argument("--output", required=True, help="Path to the generated HTML file.")
    return parser.parse_args()


def load_spec(input_path: str | None, url: str | None) -> dict[str, Any]:
    if input_path:
        return json.loads(Path(input_path).read_text(encoding="utf-8"))

    if not url:
        raise ValueError("Either --input or --url must be provided.")

    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def build_html(spec: dict[str, Any]) -> str:
    info = spec.get("info", {})
    title = str(info.get("title") or "API Docs")
    version = str(info.get("version") or "").strip()
    description = str(info.get("description") or "").strip()

    page_title = f"{title} API Docs"
    subtitle = version if version else "OpenAPI Documentation"
    safe_title = html.escape(title)
    safe_page_title = html.escape(page_title)
    safe_subtitle = html.escape(subtitle)
    safe_description = html.escape(description)
    spec_json = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_page_title}</title>
  <meta name="description" content="{safe_description}">
  <link rel="icon" href="data:,">
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3f6f8;
      --panel: #ffffff;
      --text: #14213d;
      --muted: #52606d;
      --accent: #0f766e;
      --border: #d9e2ec;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.08), transparent 30%),
        linear-gradient(180deg, #f8fbfc 0%, var(--bg) 100%);
      color: var(--text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}

    .hero {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 1rem;
      align-items: center;
      justify-content: space-between;
      padding: 1rem 1.5rem;
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
    }}

    .hero__copy {{
      min-width: 0;
    }}

    .hero h1 {{
      margin: 0;
      font-size: 1.1rem;
      line-height: 1.3;
    }}

    .hero p {{
      margin: 0.25rem 0 0;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.4;
    }}

    .hero__badge {{
      flex-shrink: 0;
      padding: 0.45rem 0.75rem;
      border: 1px solid rgba(15, 118, 110, 0.18);
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.08);
      color: var(--accent);
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
    }}

    #redoc-container {{
      min-height: calc(100vh - 84px);
    }}

    @media (max-width: 700px) {{
      .hero {{
        align-items: flex-start;
        flex-direction: column;
      }}

      .hero__badge {{
        white-space: normal;
      }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <div class="hero__copy">
      <h1>{safe_title}</h1>
      <p>{safe_description}</p>
    </div>
    <div class="hero__badge">{safe_subtitle}</div>
  </header>
  <main id="redoc-container"></main>
  <script src="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"></script>
  <script>
    window.__OPENAPI_SPEC__ = {spec_json};
    Redoc.init(window.__OPENAPI_SPEC__, {{
      hideDownloadButton: false,
      theme: {{
        colors: {{
          primary: {{
            main: "#0f766e"
          }}
        }},
        sidebar: {{
          backgroundColor: "#f8fbfc",
          textColor: "#102a43"
        }},
        typography: {{
          fontFamily: 'Segoe UI, PingFang SC, Microsoft YaHei, sans-serif',
          headings: {{
            fontFamily: 'Segoe UI, PingFang SC, Microsoft YaHei, sans-serif'
          }}
        }}
      }},
      scrollYOffset: 84
    }}, document.getElementById("redoc-container"));
  </script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    spec = load_spec(args.input, args.url)
    output_path = Path(args.output)
    output_path.write_text(build_html(spec), encoding="utf-8")


if __name__ == "__main__":
    main()
