from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Voice2 short API benchmark")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    request = Request(f"{args.url.rstrip('/')}/api/v1/runtime/benchmark", method="POST")
    with urlopen(request, timeout=65) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

