#!/usr/bin/env python3
"""Download fixed-ref Kubernetes sources using only the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


USER_AGENT = "k8s-release-xlsx-skill/1.0"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def download(url: str, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--add", action="append", default=[], metavar="TYPE=URL")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    config = load_json(run_dir / "config.json")
    source_dir = run_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    index_path = run_dir / "source-index.json"
    index = load_json(index_path) if index_path.exists() else {"sources": []}
    by_url = {item["url"]: item for item in index.get("sources", [])}

    requests: list[tuple[str, str, str]] = []
    for version in config["versions"]:
        ref = config["refs"][version]
        requests.append((
            "kube_features",
            f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/pkg/features/kube_features.go",
            f"kube_features-{version}-{ref}.go",
        ))
        requests.append((
            "changelog",
            f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/CHANGELOG/CHANGELOG-{version}.md",
            f"changelog-{version}-{ref}.md",
        ))
    # v1.32 split versioned feature gates into a separate file; merge it
    versioned_extra = "https://raw.githubusercontent.com/kubernetes/kubernetes/v1.32.0/pkg/features/versioned_kube_features.go"
    for version, ref in config["refs"].items():
        major_minor = tuple(int(x) for x in version.split("."))
        if major_minor <= (1, 32):
            requests.append((
                "kube_features_extra",
                f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/pkg/features/versioned_kube_features.go",
                f"versioned_kube_features-{version}-{ref}.go",
            ))
    for item in args.add:
        if "=" not in item:
            raise SystemExit("--add must be TYPE=URL")
        source_type, url = item.split("=", 1)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".html"
        requests.append((source_type, url, f"extra-{digest}{suffix}"))

    for source_type, url, filename in requests:
        destination = source_dir / filename
        if url in by_url and destination.exists():
            print(f"cached {url}")
            continue
        payload = download(url)
        destination.write_bytes(payload)
        record = {
            "type": source_type,
            "url": url,
            "path": str(destination.relative_to(run_dir)).replace("\\", "/"),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        by_url[url] = record
        print(f"downloaded {url}")

    index["sources"] = sorted(by_url.values(), key=lambda item: (item["type"], item["url"]))
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"indexed {len(index['sources'])} official sources")


if __name__ == "__main__":
    main()
