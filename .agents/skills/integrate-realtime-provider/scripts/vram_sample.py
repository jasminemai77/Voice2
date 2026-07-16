from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample NVIDIA VRAM usage")
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        raise SystemExit("nvidia-smi is unavailable")
    print("timestamp_ms,index,memory_used_mib,memory_free_mib")
    deadline = time.monotonic() + max(1, args.seconds)
    while time.monotonic() < deadline:
        output = subprocess.check_output(
            [
                nvidia_smi,
                "--query-gpu=index,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
        now = int(time.time() * 1000)
        for row in csv.reader(output.splitlines()):
            print(now, *(item.strip() for item in row), sep=",")
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
