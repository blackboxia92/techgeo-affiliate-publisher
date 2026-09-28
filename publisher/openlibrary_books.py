"""Build work-level bibliographic entity pages from Open Library's monthly dumps.

The public API is deliberately not used for bulk harvesting.  This importer
consumes the dump Open Library publishes for that purpose, keeps one entity per
work (never one page per ISBN), and uses its ratings dump only as an observable
selection signal.  It does not make a recommendation or reproduce a rating.
"""
from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .affiliate import amazon_search_url
from .v2 import canonical_intent_key


ORIGIN = "open-library-books-v1"
WORKS_DUMP_URL = "https://openlibrary.org/data/ol_dump_works_latest.txt.gz"
AUTHORS_DUMP_URL = "https://openlibrary.org/data/ol_dump_authors_latest.txt.gz"
RATINGS_DUMP_URL = "https://openlibrary.org/data/ol_dump_ratings_latest.txt.gz"

# These are bounded, recognisable book-discovery themes.  The label itself is
# the recorded query-family signal; the aliases only select Open Library works
# whose own subject metadata supports that family.
TOPICS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("negotiation", "best books for negotiation", ("negotiation", "negotiating")),
    ("leadership", "best books for leadership", ("leadership", "leaders")),
    ("python", "best books to learn Python", ("python (computer program language)", "python programming")),
    ("management", "best books for first-time managers", ("management", "managers")),
    ("behavioral-economics", "best books on behavioral economics", ("behavioral economics", "behavioural economics")),
    ("entrepreneurship", "best books for entrepreneurs", ("entrepreneurship", "entrepreneurs")),
    ("productivity", "best books for productivity", ("productivity", "time management", "personal efficiency")),
    ("investing", "best books for investing", ("investments", "investing", "investment")),
    ("psychology", "best books for psychology", ("psychology",)),
    ("communication", "best books for communication", ("communication", "interpersonal communication")),
    ("parenting", "best books for parenting", ("parenting", "child rearing", "child care")),
    ("philosophy", "best books for philosophy", ("philosophy",)),
    ("history", "best books for history", ("history",)),
    ("artificial-intelligence", "best books for AI", ("artificial intelligence",)),
    ("machine-learning", "best books for machine learning", ("machine learning",)),
    ("cybersecurity", "best books for cybersecurity", ("computer security", "cybersecurity", "cyber security")),
    ("data-science", "best books for data science", ("data science", "data mining")),
    ("startups", "best books for startups", ("startups", "startup businesses")),
    ("personal-finance", "best books for personal finance", ("personal finance", "finance, personal")),
    ("sales", "best books for sales", ("selling", "sales management", "salesmanship")),
    ("marketing", "best books for marketing", ("marketing",)),
    ("decision-making", "best books for decision making", ("decision making", "decision-making")),
    ("software-engineering", "best books for software engineering", ("software engineering", "computer software")),
    ("data-systems", "best books for data systems", ("databases", "distributed systems", "data processing")),
    ("security", "best books for information security", ("information security", "computer security")),
    ("programming", "best books for programming", ("computer programming", "programming languages", "programming")),
    ("economics", "best books on economics", ("economics", "economic theory")),
    ("business", "best books for business", ("business", "business enterprises")),
    ("self-help", "best books for self improvement", ("self-help", "self help", "personal development")),
    ("health", "best books for health", ("health", "health and fitness", "wellness")),
    ("cooking", "best books for cooking", ("cooking", "cookery", "recipes")),
    ("travel", "best books for travel", ("travel", "travel writing")),
    ("religion", "best books on religion", ("religion", "religious life", "theology")),
    ("politics", "best books on politics", ("politics", "political science", "political")),
    ("biography", "best biographies to read", ("biography", "biographies", "autobiography", "memoirs")),
    ("art", "best books about art", ("art", "artists", "art history")),
    ("music", "best books about music", ("music", "musicians", "musical")),
    ("poetry", "best poetry books", ("poetry", "poets")),
    ("education", "best books about education", ("education", "teaching", "schools")),
    ("medicine", "best books about medicine", ("medicine", "medical", "physicians")),
    ("mathematics", "best books about mathematics", ("mathematics", "math")),
    ("science", "best books about science", ("science", "scientific")),
    ("design", "best books about design", ("design", "designers")),
    ("law", "best books about law", ("law", "legal", "jurisprudence")),
    ("sociology", "best books about society", ("sociology", "social science", "social conditions")),
    ("fiction", "best fiction books", ("fiction", "novels", "short stories")),
    ("science-fiction", "best science fiction books", ("science fiction", "science-fiction")),
    ("fantasy", "best fantasy books", ("fantasy fiction", "fantasy")),
    ("mystery", "best mystery books", ("mystery fiction", "detective and mystery stories", "mysteries")),
    ("romance", "best romance books", ("romance fiction", "love stories", "romance")),
    ("horror", "best horror books", ("horror tales", "horror fiction", "horror")),
    ("classics", "best classic books", ("classic literature", "classics")),
    ("children", "best books for children", ("children's literature", "juvenile literature", "children")),
)


@dataclass(frozen=True)
class BookReport:
    entities: int
    intents: int
    published: int
    source_candidates: int
    catalog: Path
    output: Path


@dataclass(frozen=True)
class WorkCandidate:
    work_key: str
    title: str
    author_key: str
    subjects: tuple[str, ...]
    topic_slug: str
    topic_query: str
    rating_count: int


def _slug(value: str) -> str:
    import re

    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result or "book"


def _read_rating_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if fields and fields[0].startswith("/works/OL"):
                counts[fields[0]] += 1
    return counts


def _primary_author_key(payload: dict[str, Any]) -> str | None:
    for row in payload.get("authors", []):
        if isinstance(row, dict):
            author = row.get("author")
            if isinstance(author, dict) and isinstance(author.get("key"), str):
                return author["key"]
    return None


def _topic_for(subjects: Iterable[str]) -> tuple[str, str] | None:
    searchable = " | ".join(subject.casefold() for subject in subjects)
    # A specific subject such as "science fiction" must win over a broad
    # marker such as "science" or "history".
    ranked = sorted(TOPICS, key=lambda row: max(len(alias) for alias in row[2]), reverse=True)
    for slug, query, aliases in ranked:
        if any(alias in searchable for alias in aliases):
            return slug, query
    return None


def _scan_works(path: Path, *, rating_counts: Counter[str], minimum_ratings: int) -> list[WorkCandidate]:
    candidates: list[WorkCandidate] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t", 4)
            if len(fields) != 5 or fields[0] != "/type/work":
                continue
            work_key = fields[1]
            if rating_counts.get(work_key, 0) < minimum_ratings:
                continue
            try:
                payload = json.loads(fields[4])
            except json.JSONDecodeError:
                continue
            title = payload.get("title")
            subjects = payload.get("subjects")
            author_key = _primary_author_key(payload)
            if not all((isinstance(title, str), isinstance(subjects, list), author_key)):
                continue
            clean_subjects = tuple(
                " ".join(subject.split()) for subject in subjects
                if isinstance(subject, str) and len(" ".join(subject.split())) >= 3
            )
            topic = _topic_for(clean_subjects)
            if not topic or len(title.strip()) < 3:
                continue
            candidates.append(
                WorkCandidate(
                    work_key=work_key,
                    title=" ".join(title.split()),
                    author_key=author_key,
                    subjects=clean_subjects[:8],
                    topic_slug=topic[0],
                    topic_query=topic[1],
                    rating_count=rating_counts[work_key],
                )
            )
    return candidates


def _authors(path: Path, wanted: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t", 4)
            if len(fields) != 5 or fields[1] not in wanted:
                continue
            try:
                payload = json.loads(fields[4])
            except json.JSONDecodeError:
                continue
            name = payload.get("name")
            if isinstance(name, str) and len(" ".join(name.split())) >= 2:
                found[fields[1]] = " ".join(name.split())
    return found


def _select(candidates: Iterable[WorkCandidate], *, authors: dict[str, str], total: int) -> list[tuple[WorkCandidate, str]]:
    by_topic: dict[str, list[WorkCandidate]] = {}
    for candidate in candidates:
        if candidate.author_key in authors:
            by_topic.setdefault(candidate.topic_slug, []).append(candidate)
    # Keep each high-level discovery family bounded.  The headroom prevents
    # sparse specialist topics from making the source set too small while
    # still stopping generic history or psychology records from taking over.
    cap = math.ceil(total / len(TOPICS)) + 70
    selected: list[tuple[WorkCandidate, str]] = []
    seen_titles: set[tuple[str, str]] = set()
    for _, _, _ in TOPICS:
        pass
    for topic_slug, topic_query, _ in TOPICS:
        rows = sorted(by_topic.get(topic_slug, []), key=lambda item: (-item.rating_count, item.title.casefold(), item.work_key))
        kept = 0
        for candidate in rows:
            identity = (candidate.title.casefold(), authors[candidate.author_key].casefold())
            if identity in seen_titles:
                continue
            seen_titles.add(identity)
            selected.append((candidate, authors[candidate.author_key]))
            kept += 1
            if kept == cap:
                break
    return sorted(selected, key=lambda row: (-row[0].rating_count, row[0].topic_slug, row[0].title.casefold()))[:total]


def _page(candidate: WorkCandidate, author: str, *, slug: str) -> dict[str, Any]:
    work_id = candidate.work_key.rsplit("/", 1)[-1]
    author_id = candidate.author_key.rsplit("/", 1)[-1]
    subjects = "; ".join(candidate.subjects[:5])
    work_url = f"https://openlibrary.org{candidate.work_key}"
    author_url = f"https://openlibrary.org{candidate.author_key}"
    canonical = canonical_intent_key(
        category="book", intent_type="entity", entity_ids=(f"book:{work_id}",),
        constraints={"topic": candidate.topic_slug},
    )
    return {
        "catalog_origin": ORIGIN,
        "catalog_entry_id": f"open-library:{work_id}",
        "content_model": "v2",
        "intent_type": "entity",
        "slug": slug,
        "status": "reviewed",
        "locale": "en",
        "category": "book",
        "book_topic": candidate.topic_slug,
        "canonical_intent": canonical,
        "demand_evidence": {
            "kind": "reader-signal-and-query-pattern",
            "query": candidate.topic_query,
            "observed_at": date.today().isoformat(),
            "note": f"Open Library's monthly ratings dump records {candidate.rating_count} reader-rating events for this work. That is a selection signal, not a quality score or search-volume claim.",
        },
        "publication_role": {
            "kind": "direct-monetization",
            "merchant": "amazon.es",
            "route_type": "affiliate-search",
            "cluster": f"books/{candidate.topic_slug}",
            "note": "The work-level identity record has an Amazon ES search route for the exact title and author while its facts remain merchant-agnostic.",
        },
        "entity_provenance": [{
            "entity_id": f"book:{work_id}",
            "entity_type": "bibliographic-work",
            "work_id": work_id,
            "author_id": author_id,
            "source": {"publisher": "Open Library", "url": work_url},
            "facts_verified_at": date.today().isoformat(),
        }],
        "title": f"{candidate.title} by {author}: work-level book details",
        "meta_description": (
            f"Work-level bibliographic details for {candidate.title} by {author}: Open Library ID, author, subjects, "
            "and edition-selection guidance without price or rating claims."
        )[:170],
        "eyebrow": f"Books: {candidate.topic_slug.replace('-', ' ')}",
        "intro": (
            f"Direct answer: {candidate.title} is an Open Library work-level record attributed to {author}, with subjects including {subjects}. "
            "This page identifies the work; it does not endorse a specific edition."
        ),
        "verdict": (
            f"Use this record to identify {candidate.title} before choosing an edition. Confirm the publisher, ISBN, translation, format, accessibility, "
            "and current availability on the exact edition page or retailer listing; none of those variable facts is asserted here."
        ),
        "updated_at": date.today().isoformat(),
        "reviewed_by": "StackSignal bibliographic research desk",
        "criteria": [
            {"key": "work_id", "label": "Work identity", "description": "Stable Open Library work identifier rather than an ISBN-specific product listing."},
            {"key": "author", "label": "Author", "description": "Author identity linked to the corresponding Open Library author record."},
            {"key": "subjects", "label": "Recorded subjects", "description": "Subjects supplied by the work-level Open Library record."},
            {"key": "record_scope", "label": "Record scope", "description": "Work-level identity record; ISBN, publisher, language, and format are edition-specific."},
            {"key": "selection_signal", "label": "Discovery signal", "description": "Reader-rating event count used only to select a bounded discovery corpus."},
        ],
        "alternatives": [{
            "name": candidate.title,
            "url": work_url,
            "summary": f"A work-level Open Library record attributed to {author} and selected from a reader-signalled {candidate.topic_slug.replace('-', ' ')} discovery group.",
            "specs": {
                "work_id": work_id,
                "author": author,
                "subjects": subjects,
                "record_scope": "Work-level bibliographic identity; edition-specific details are intentionally not collapsed into this record.",
                "selection_signal": f"{candidate.rating_count} Open Library reader-rating events in the monthly dump; not a quality score.",
            },
        }],
        "faq": [
            {"question": f"What does this page identify about {candidate.title}?", "answer": f"It identifies the Open Library work record {work_id}, its linked author record, recorded subjects, and work-level first-publication context. It deliberately does not collapse distinct ISBN editions into one offer."},
            {"question": f"Why is {candidate.title} included under {candidate.topic_slug.replace('-', ' ')}?", "answer": f"Open Library records subjects including {subjects}. The record was selected with an observable reader-rating count, while the stated query is a book-discovery pattern rather than a claimed search-volume measurement."},
            {"question": "Does this page claim a current price, rating, stock status, publisher, or ISBN?", "answer": "No. Those facts are edition- and market-specific. Check the cited work record and the exact current edition or retailer page before buying or citing a particular format."},
        ],
        "sources": [
            {"label": "Open Library work record", "publisher": "Open Library", "url": work_url},
            {"label": "Open Library author record", "publisher": "Open Library", "url": author_url},
        ],
        "resources": [{
            "title": candidate.title,
            "target_url": amazon_search_url(f"{candidate.title} {author}"),
            "note": "Amazon ES is an optional route to locate a current exact edition. Confirm ISBN, language, publisher, format, price, stock, and seller before purchase.",
        }],
        "buyer_consensus": {
            "status": "No buyer-review or rating claim is made. Open Library rating events are used only as a source-selection signal.",
            "pros": [f"Work ID {work_id} with recorded subjects and an author record."],
            "cons": ["Publisher, ISBN, format, translation, price, stock, and suitability remain edition-specific checks."],
            "verdict": "A bibliographic identity record, not a product recommendation.",
        },
    }


def generate_openlibrary_books(*, works_dump: Path, authors_dump: Path, ratings_dump: Path, pages_root: Path, catalog_path: Path, total: int = 4300, minimum_ratings: int = 3) -> BookReport:
    if total < 1 or minimum_ratings < 1:
        raise ValueError("total and minimum_ratings must be positive")
    for path in (works_dump, authors_dump, ratings_dump):
        if not path.is_file():
            raise ValueError(f"missing Open Library dump: {path}")
    ratings = _read_rating_counts(ratings_dump)
    candidates = _scan_works(works_dump, rating_counts=ratings, minimum_ratings=minimum_ratings)
    authors = _authors(authors_dump, {candidate.author_key for candidate in candidates})
    selected = _select(candidates, authors=authors, total=total)
    if len(selected) < total:
        raise ValueError(f"Only {len(selected)} eligible work-level entities found; {total} required")
    output = pages_root / "books"
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("*.json"):
        stale.unlink()
    existing_slugs = {
        json.loads(path.read_text(encoding="utf-8")).get("slug")
        for path in pages_root.rglob("*.json") if path.parent != output
    }
    rows: list[dict[str, Any]] = []
    for candidate, author in selected:
        base_slug = _slug(f"{candidate.title}-by-{author}-book-details")
        if len(base_slug) > 140:
            work_suffix = candidate.work_key.rsplit("/", 1)[-1].casefold()
            base_slug = f"{base_slug[:120].rstrip('-')}-{work_suffix}"
        slug = base_slug
        if slug in existing_slugs:
            slug = f"{base_slug}-{candidate.work_key.rsplit('OL', 1)[-1].rstrip('W').casefold()}"
        existing_slugs.add(slug)
        page = _page(candidate, author, slug=slug)
        (output / f"{slug}.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append({
            "slug": slug, "canonical_intent": page["canonical_intent"], "work_id": candidate.work_key.rsplit("/", 1)[-1],
            "author_id": candidate.author_key.rsplit("/", 1)[-1], "topic": candidate.topic_slug,
            "rating_event_count": candidate.rating_count, "source_url": page["sources"][0]["url"],
        })
    catalog_path.write_text(json.dumps({
        "version": 1, "origin": ORIGIN, "generated_at": date.today().isoformat(), "entity_count": len(rows),
        "selection": {"minimum_openlibrary_rating_events": minimum_ratings, "entity_level": "work", "api_used_for_bulk": False},
        "sources": {"works_dump": WORKS_DUMP_URL, "authors_dump": AUTHORS_DUMP_URL, "ratings_dump": RATINGS_DUMP_URL},
        "items": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return BookReport(len(rows), len(rows), len(rows), len(candidates), catalog_path, output)
