"""Buat payload QR signed token untuk satu kendaraan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sticker import create_signed_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Smart Gate signed QR token")
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=365 * 24 * 3600)
    args = parser.parse_args()
    print(create_signed_token(args.vehicle_id, args.code, args.ttl_seconds))


if __name__ == "__main__":
    main()
