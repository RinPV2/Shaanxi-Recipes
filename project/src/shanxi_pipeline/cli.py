from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .config import load_context
from .confirmation_reader import parse_confirmation_source, write_confirmation_learning
from .manifest import load_books, normalize_book_manifest, upsert_book
from .mineru_json_parser import parse_mineru_book
from .models import PageFallbackNote, RecipeCandidate, ReviewItem
from .obsidian_exporter import build_indexes, export_notes
from .page_normalizer import normalize_page
from .page_review_builder import build_page_review_dataset
from .pdf_reviewer import render_book_pages, render_review_pages
from .pdf_splitter import split_books
from .recipe_segmenter import segment_book
from .review_priority import build_review_priority_report
from .reports import (
    write_directory_tree,
    write_ingestion_manifest,
    write_manifest_strategy,
    write_review_queue,
    write_summary,
    write_validation_checklist,
)
from .review_web import serve_review_web
from .utils import ensure_dir, setup_logging, write_json


def _select_books(all_books, requested_ids):
    if requested_ids:
        wanted = set(requested_ids)
        return [book for book in all_books if book.book_id in wanted]
    return [book for book in all_books if book.enabled and book.status != "pending"]


def _load_persisted_outputs(context) -> tuple[list[RecipeCandidate], list[PageFallbackNote]]:
    recipes: list[RecipeCandidate] = []
    recipe_root = context.work_root / "recipe_candidates"
    if recipe_root.exists():
        for path in sorted(recipe_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            recipes.extend(RecipeCandidate(**row) for row in payload)

    fallbacks: list[PageFallbackNote] = []
    fallback_root = context.work_root / "page_fallback_notes"
    if fallback_root.exists():
        for path in sorted(fallback_root.glob("*/*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            fallbacks.append(PageFallbackNote(**payload))
    return recipes, fallbacks


def _load_existing_review_queue(path: Path, skip_book_ids: set[str]) -> list[ReviewItem]:
    if not path.exists():
        return []
    rows: list[ReviewItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        item = ReviewItem(**payload)
        if item.book_id not in skip_book_ids:
            rows.append(item)
    return rows


def _collect_page_counts(context) -> dict[str, int]:
    counts: dict[str, int] = {}
    root = context.work_root / "normalized_json"
    if root.exists():
        for book_dir in root.iterdir():
            if book_dir.is_dir():
                counts[book_dir.name] = len(list(book_dir.glob("page-*.json")))
    return counts


def prepare(root: Path) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "prepare")
    books = normalize_book_manifest(context.book_manifest)
    for rel in [
        context.work_root / "parsed_pages",
        context.work_root / "normalized_json",
        context.work_root / "recipe_candidates",
        context.work_root / "review_queue",
        context.work_root / "page_fallback_notes",
        context.work_root / "final_markdown",
        context.work_root / "reports",
        context.vault_root,
    ]:
        ensure_dir(rel)
    logger.info("Prepared workspace for %s books.", len(books))


def process_books(root: Path, requested_ids: list[str] | None = None) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "process-existing-json")
    normalize_book_manifest(context.book_manifest)
    all_manifest_books = load_books(context.book_manifest)
    books = _select_books(all_manifest_books, requested_ids)
    thresholds = context.pipeline_config["thresholds"]

    all_reviews = _load_existing_review_queue(context.work_root / "reports" / "review_queue.jsonl", {book.book_id for book in books})
    for book in books:
        if not book.json_path or not book.json_path.exists():
            logger.warning("Skipping %s because MinerU JSON is missing.", book.book_id)
            continue
        logger.info("Processing %s", book.book_id)
        parsed_pages, _meta = parse_mineru_book(book)

        parsed_root = ensure_dir(context.work_root / "parsed_pages" / book.book_id)
        normalized_root = ensure_dir(context.work_root / "normalized_json" / book.book_id)

        normalized_pages = []
        for page in parsed_pages:
            write_json(parsed_root / f"page-{page.local_page:04d}.json", page.to_dict())
            normalized = normalize_page(page, context.cleaning_rules, thresholds)
            normalized_pages.append(normalized)
            write_json(normalized_root / f"page-{page.local_page:04d}.json", normalized.to_dict())

        recipes, fallbacks, review_items = segment_book(book, normalized_pages)
        write_json(context.work_root / "recipe_candidates" / f"{book.book_id}.json", [recipe.to_dict() for recipe in recipes])

        for fallback in fallbacks:
            write_json(
                ensure_dir(context.work_root / "page_fallback_notes" / book.book_id)
                / f"{fallback.book_id}-page-{fallback.local_pages[0]:04d}.json",
                fallback.to_dict(),
            )

        all_reviews.extend(review_items)

        logger.info(
            "Completed %s: %s pages, %s recipes, %s fallbacks, %s review items.",
            book.book_id,
            len(normalized_pages),
            len(recipes),
            len(fallbacks),
            len(review_items),
        )

    all_recipes, all_fallbacks = _load_persisted_outputs(context)
    page_counts = _collect_page_counts(context)
    recipes_by_book = defaultdict(list)
    fallbacks_by_book = defaultdict(list)
    reviews_by_book = defaultdict(list)
    for recipe in all_recipes:
        recipes_by_book[recipe.book_id].append(recipe)
    for fallback in all_fallbacks:
        fallbacks_by_book[fallback.book_id].append(fallback)
    for review in all_reviews:
        reviews_by_book[review.book_id].append(review)
    export_notes(context.work_root / "final_markdown", context.vault_root, all_recipes, all_fallbacks, context.obsidian_schema)
    build_indexes(context.vault_root, all_recipes, all_fallbacks, context.obsidian_schema)

    report_root = ensure_dir(context.work_root / "reports")
    write_review_queue(report_root, all_reviews)
    write_ingestion_manifest(report_root, all_manifest_books, recipes_by_book, fallbacks_by_book, reviews_by_book, page_counts)
    write_summary(report_root, books, all_recipes, all_fallbacks, all_reviews, page_counts)
    write_manifest_strategy(report_root)
    write_validation_checklist(report_root)
    write_directory_tree(report_root, context.project_root)
    logger.info("Finished processing %s books.", len(books))


def review_ambiguous(root: Path, requested_ids: list[str] | None = None, limit: int | None = None) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "review-ambiguous")
    review_path = context.work_root / "reports" / "review_queue.jsonl"
    if not review_path.exists():
        logger.info("No review queue found.")
        return

    all_rows = []
    rows_to_render = []
    for line in review_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        item = ReviewItem(**payload)
        all_rows.append(item)
        if requested_ids and item.book_id not in requested_ids:
            continue
        rows_to_render.append(item)

    rendered = render_review_pages(rows_to_render, context.work_root / "review_queue" / "rendered", limit=limit)
    rendered_lookup = {
        (item.book_id, item.local_page, item.reason): item.rendered_page_path
        for item in rendered
    }
    for item in all_rows:
        key = (item.book_id, item.local_page, item.reason)
        if key in rendered_lookup:
            item.rendered_page_path = rendered_lookup[key]
    write_review_queue(context.work_root / "reports", all_rows)
    logger.info("Rendered %s review page images.", len(rendered))


def render_all_pages(
    root: Path,
    requested_ids: list[str] | None = None,
    overwrite: bool = False,
) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "render-book-pages")
    normalize_book_manifest(context.book_manifest)
    books = _select_books(load_books(context.book_manifest), requested_ids)
    total = 0
    for book in books:
        if not book.pdf_path.exists():
            logger.warning("Skipping %s because PDF is missing.", book.book_id)
            continue
        rendered = render_book_pages(book, context.work_root / "review_queue" / "rendered", overwrite=overwrite)
        total += len(rendered)
        logger.info("Rendered %s pages for %s.", len(rendered), book.book_id)
    logger.info("Rendered or verified %s total page PNGs.", total)


def learn_from_confirmations(root: Path, source: str | None = None) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "learn-from-confirmations")
    source_path = Path(source) if source else context.work_root / "page_review_md"
    rows = parse_confirmation_source(source_path)
    records_path, rules_path, md_path = write_confirmation_learning(context.work_root / "reports", rows)
    logger.info("Parsed %s queue entries from %s.", len(rows), source_path)
    logger.info("Wrote confirmation records to %s", records_path)
    logger.info("Wrote learned rules to %s and %s", rules_path, md_path)


def build_page_review(root: Path, requested_ids: list[str] | None = None) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "build-page-review")
    manifest_path, total_pages = build_page_review_dataset(context, requested_ids)
    logger.info("Built page review dataset with %s pages.", total_pages)
    logger.info("Wrote manifest to %s", manifest_path)


def start_review_web(root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "review-web")
    manifest_path = context.work_root / "reports" / "page_review_manifest.json"
    if not manifest_path.exists():
        build_page_review(root)
    logger.info("Serving review web at http://%s:%s", host, port)
    serve_review_web(context, host=host, port=port)


def split_pdfs(root: Path, requested_ids: list[str] | None = None, max_pages: int = 200, max_megabytes: int = 100) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "split-pdfs")
    manifest_path = split_books(context, requested_ids=requested_ids, max_pages=max_pages, max_megabytes=max_megabytes)
    logger.info("Wrote split PDF manifest to %s", manifest_path)


def build_review_priority(root: Path, requested_ids: list[str] | None = None) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "build-review-priority")
    json_path, md_path = build_review_priority_report(context, requested_ids=requested_ids)
    logger.info("Wrote review priority reports to %s and %s", json_path, md_path)


def import_book(root: Path, book_id: str, mineru_json: str) -> None:
    context = load_context(root)
    logger = setup_logging(context.logs_root, "import-book")
    books = normalize_book_manifest(context.book_manifest)
    target = next((book for book in books if book.book_id == book_id), None)
    if target is None:
        raise ValueError(f"Unknown book_id: {book_id}")

    target.mineru_json = str(Path(mineru_json))
    target.status = "ready"
    target.enabled = True
    upsert_book(context.book_manifest, target)
    logger.info("Updated manifest for %s", book_id)
    process_books(root, [book_id])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shanxi MinerU to Obsidian pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--root", default=".")

    process_parser = subparsers.add_parser("process-existing-json")
    process_parser.add_argument("--root", default=".")
    process_parser.add_argument("--book-id", action="append", default=[])

    review_parser = subparsers.add_parser("review-ambiguous")
    review_parser.add_argument("--root", default=".")
    review_parser.add_argument("--book-id", action="append", default=[])
    review_parser.add_argument("--limit", type=int, default=20)

    render_pages_parser = subparsers.add_parser("render-book-pages")
    render_pages_parser.add_argument("--root", default=".")
    render_pages_parser.add_argument("--book-id", action="append", default=[])
    render_pages_parser.add_argument("--overwrite", action="store_true")

    learn_parser = subparsers.add_parser("learn-from-confirmations")
    learn_parser.add_argument("--root", default=".")
    learn_parser.add_argument("--source", default=None)

    build_review_parser = subparsers.add_parser("build-page-review")
    build_review_parser.add_argument("--root", default=".")
    build_review_parser.add_argument("--book-id", action="append", default=[])

    serve_review_parser = subparsers.add_parser("serve-review-web")
    serve_review_parser.add_argument("--root", default=".")
    serve_review_parser.add_argument("--host", default="127.0.0.1")
    serve_review_parser.add_argument("--port", type=int, default=8765)

    split_parser = subparsers.add_parser("split-pdfs")
    split_parser.add_argument("--root", default=".")
    split_parser.add_argument("--book-id", action="append", default=[])
    split_parser.add_argument("--max-pages", type=int, default=200)
    split_parser.add_argument("--max-megabytes", type=int, default=100)

    review_priority_parser = subparsers.add_parser("build-review-priority")
    review_priority_parser.add_argument("--root", default=".")
    review_priority_parser.add_argument("--book-id", action="append", default=[])

    import_parser = subparsers.add_parser("import-book")
    import_parser.add_argument("--root", default=".")
    import_parser.add_argument("--book-id", required=True)
    import_parser.add_argument("--mineru-json", required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.root)

    if args.command == "prepare":
        prepare(root)
    elif args.command == "process-existing-json":
        process_books(root, args.book_id)
    elif args.command == "review-ambiguous":
        review_ambiguous(root, args.book_id, args.limit)
    elif args.command == "render-book-pages":
        render_all_pages(root, args.book_id, args.overwrite)
    elif args.command == "learn-from-confirmations":
        learn_from_confirmations(root, args.source)
    elif args.command == "build-page-review":
        build_page_review(root, args.book_id)
    elif args.command == "serve-review-web":
        start_review_web(root, args.host, args.port)
    elif args.command == "split-pdfs":
        split_pdfs(root, args.book_id, args.max_pages, args.max_megabytes)
    elif args.command == "build-review-priority":
        build_review_priority(root, args.book_id)
    elif args.command == "import-book":
        import_book(root, args.book_id, args.mineru_json)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
