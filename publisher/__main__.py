from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from .builder import build_site, expand_catalog
from .consumer_catalog import generate_consumer_catalog
from .indexnow import notify_indexnow
from .mass_catalog import generate_mass_catalog
from .weekly import generate_weekly_pages


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="publisher", description="Build quality-gated technical comparison pages")
    commands = root.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Build the static site")
    build.add_argument("--content", type=Path, default=Path(os.getenv("CONTENT_DIR", "content/pages")))
    build.add_argument("--output", type=Path, default=Path(os.getenv("OUTPUT_DIR", "dist")))
    build.add_argument("--state", type=Path, default=Path(os.getenv("DATABASE_PATH", "data/state.sqlite3")))
    build.add_argument("--base-url", default=os.getenv("BASE_URL", "https://example.com"))
    build.add_argument("--indexnow-key", default=os.getenv("INDEXNOW_KEY") or None)
    build.add_argument("--include-drafts", action="store_true")

    expand = commands.add_parser("expand", help="Generate noindex editorial drafts from a catalog")
    expand.add_argument("--catalog", type=Path, default=Path("content/catalog.json"))
    expand.add_argument("--output", type=Path, default=Path("content/pages/drafts"))
    expand.add_argument("--limit", type=int)

    weekly = commands.add_parser("weekly", help="Create the next batch of catalog-backed long-tail comparisons")
    weekly.add_argument("--catalog", type=Path, default=Path("content/catalog.json"))
    weekly.add_argument("--output", type=Path, default=Path("content/pages"))
    weekly.add_argument("--limit", type=int, default=20)

    mass = commands.add_parser("mass", help="Build an exact reviewed catalog from curated product facts")
    mass.add_argument("--source", type=Path, default=Path("content/products_source.json"))
    mass.add_argument("--catalog", type=Path, default=Path("content/products_catalog.json"))
    mass.add_argument("--output", type=Path, default=Path("content/pages"))
    mass.add_argument("--total", type=int, default=1000)

    consumer = commands.add_parser("consumer-mass", help="Build a reviewed evergreen consumer-product catalog")
    consumer.add_argument("--source", type=Path, default=Path("content/consumer_products_source.json"))
    consumer.add_argument("--catalog", type=Path, default=Path("content/products_catalog.json"))
    consumer.add_argument("--output", type=Path, default=Path("content/pages"))
    consumer.add_argument("--total", type=int, default=4000)

    notify = commands.add_parser("notify", help="Submit changed reviewed URLs to IndexNow")
    notify.add_argument("--state", type=Path, default=Path(os.getenv("DATABASE_PATH", "data/state.sqlite3")))
    notify.add_argument("--base-url", default=os.getenv("BASE_URL", "https://example.com"))
    notify.add_argument("--key", default=os.getenv("INDEXNOW_KEY"))
    notify.add_argument("--dry-run", action="store_true")
    notify.add_argument("--skip-key-check", action="store_true")

    commands.add_parser("key", help="Generate an IndexNow key")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "key":
        print(secrets.token_hex(16))
        return 0
    if args.command == "expand":
        count = expand_catalog(args.catalog, args.output, args.limit)
        print(json.dumps({"created_drafts": count, "output": str(args.output)}, indent=2))
        return 0
    if args.command == "weekly":
        report = generate_weekly_pages(args.catalog, args.output, args.limit)
        print(json.dumps(report.__dict__ | {"output": str(report.output), "slugs": list(report.slugs)}, indent=2))
        if report.created != args.limit:
            raise SystemExit(
                f"Only {report.created} unused catalog comparisons remain; {args.limit} were required. Extend the catalog."
            )
        return 0
    if args.command == "mass":
        report = generate_mass_catalog(
            source_path=args.source,
            pages_root=args.output,
            catalog_path=args.catalog,
            total=args.total,
        )
        print(json.dumps(report.__dict__ | {"catalog": str(report.catalog), "output": str(report.output)}, indent=2))
        return 0

    if args.command == "consumer-mass":
        report = generate_consumer_catalog(
            pages_root=args.output,
            catalog_path=args.catalog,
            source_path=args.source,
            total=args.total,
        )
        print(json.dumps(report.__dict__ | {"catalog": str(report.catalog), "output": str(report.output)}, indent=2))
        return 0
    if args.command == "build":
        report = build_site(
            content_dir=args.content,
            output_dir=args.output,
            state_path=args.state,
            base_url=args.base_url,
            indexnow_key=args.indexnow_key,
            configured_tag=os.getenv("AMAZON_ASSOCIATE_TAG"),
            include_drafts=args.include_drafts,
        )
        print(json.dumps(report.__dict__ | {"output": str(report.output)}, indent=2))
        return 0
    if args.command == "notify":
        if not args.key:
            raise SystemExit("INDEXNOW_KEY or --key is required")
        result = notify_indexnow(
            state_path=args.state,
            base_url=args.base_url,
            key=args.key,
            dry_run=args.dry_run,
            skip_key_check=args.skip_key_check,
        )
        print(json.dumps(result, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
