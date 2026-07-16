from __future__ import annotations

import argparse

from voice2.providers import ProviderRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Voice2 provider manifest")
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    manifest = ProviderRegistry().get(args.provider).manifest()
    assert manifest.id == args.provider
    assert manifest.license and manifest.version and manifest.variants
    assert len({variant.id for variant in manifest.variants}) == len(manifest.variants)
    for variant in manifest.variants:
        assert variant.estimated_ram_mib >= 0 and variant.estimated_vram_mib >= 0
    print(f"OK: {manifest.id} ({manifest.kind}) has {len(manifest.variants)} variant(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

