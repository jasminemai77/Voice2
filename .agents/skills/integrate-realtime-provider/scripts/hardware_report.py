from __future__ import annotations

import json
from pathlib import Path

from voice2.runtime import HardwareDetector

if __name__ == "__main__":
    report = HardwareDetector(Path(".voice2-data")).detect()
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
