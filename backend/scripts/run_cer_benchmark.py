"""
Week 9 deliverable: "Multi-script OCR benchmark — CER reported per script
per engine on the sample set; engine selected per script."

Segment 4 shipped the `/admin/cer-benchmark` *endpoint*, but the rows it
served were placeholders carried over from the frontend mock (see
app/seed.py's comment: "nothing here runs OCR against the sample set and
measures real CER yet"). This script is that missing piece: it runs every
configured engine against every image in the synthetic sample set (see
generate_synthetic_samples.py), diffs the output against the ground-truth
text, and writes real `CerBenchmarkEntry` rows.

CER (Character Error Rate) here is Levenshtein edit distance between the
engine's raw transcription and the ground-truth text, divided by the
ground-truth character count — the standard OCR metric, computed with a
plain-Python DP implementation (no extra dependency).

Prerequisites
-------------
1. Run generate_synthetic_samples.py first (needs storage/synthetic/ to
   exist with images + ground_truth.json).
2. For a *complete* benchmark: `tesseract-ocr-urd` + `tesseract-ocr-mar`
   installed, and SARVAM_API_KEY / GEMINI_API_KEY set in .env. Any engine
   that isn't configured is skipped for that run (reported as such) rather
   than failing the whole benchmark — same degrade-cleanly behavior as the
   live upload pipeline.
3. Network access (Sarvam/Gemini are hosted APIs) — this script does nothing
   to change that; it just calls the same engine adapters app/services/ocr
   uses in production.

Usage
-----
    python -m scripts.run_cer_benchmark
    python -m scripts.run_cer_benchmark --engines tesseract gemini_vision
    python -m scripts.run_cer_benchmark --dry-run   # print table, don't write to DB
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import CerBenchmarkEntry, ScriptType  # noqa: E402
from app.services.ocr import gemini_engine, sarvam_engine, tesseract_engine  # noqa: E402
from app.services.ocr.base import RawTextResult  # noqa: E402

logger = logging.getLogger("run_cer_benchmark")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

SYNTHETIC_DIR = Path(__file__).resolve().parent.parent / "storage" / "synthetic"

ENGINES = ["sarvam_vision", "tesseract", "gemini_vision"]
# Surya isn't wired into this backend as a callable engine (it's listed in
# the frontend's CER benchmark UI as an option the pod could add, per the
# project doc's stack line) — flagged rather than silently dropped so
# whoever reviews benchmark output knows why it's missing.
SURYA_NOTE = (
    "surya has no engine adapter under app/services/ocr yet (project doc lists it as a stack option, "
    "not something Segment 2 implemented) — no CER row is produced for it."
)


def cer(hypothesis: str, reference: str) -> float:
    """Character Error Rate = Levenshtein(hyp, ref) / len(ref).
    Returns 1.0 (worst) if the reference is empty or the engine returned
    nothing, rather than dividing by zero or rewarding a blank OCR read."""
    reference = reference or ""
    hypothesis = hypothesis or ""
    if not reference:
        return 1.0
    if not hypothesis:
        return 1.0

    # Standard DP edit distance, O(len(hyp) * len(ref)) — fine at
    # document-sized text (a few hundred characters).
    m, n = len(hypothesis), len(reference)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if hypothesis[i - 1] == reference[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    distance = prev[n]
    return min(distance / n, 1.0)


def run_engine(engine: str, image_bytes: bytes, filename: str, script_type: ScriptType) -> RawTextResult:
    if engine == "tesseract":
        return tesseract_engine.run_tesseract(image_bytes, "image/png")
    if engine == "sarvam_vision":
        return sarvam_engine.run_sarvam_vision(image_bytes, filename, script_type)
    if engine == "gemini_vision":
        return gemini_engine.run_gemini_ocr(image_bytes, "image/png")
    raise ValueError(f"Unknown engine: {engine}")


def run_benchmark(engines: list[str], synthetic_dir: Path) -> list[dict]:
    manifest_path = synthetic_dir / "ground_truth.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path} not found — run `python -m scripts.generate_synthetic_samples` first."
        )
    docs = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Only score against clean documents — seeded-error docs have
    # deliberately corrupted ground truth, which isn't a fair OCR-accuracy
    # comparison (that's what score_synthetic_set.py's validation-catch-rate
    # check is for, not the CER benchmark).
    docs = [d for d in docs if not d.get("seeded_error_type")]

    # {(script_type, engine): [cer, cer, ...]}
    results: dict[tuple[str, str], list[float]] = defaultdict(list)
    skipped_engines: set[str] = set()

    for doc in docs:
        image_path = synthetic_dir / doc["filename"]
        if not image_path.exists():
            logger.warning("Missing image for %s, skipping.", doc["filename"])
            continue
        image_bytes = image_path.read_bytes()
        script_type = ScriptType(doc["script_type"])

        for engine in engines:
            result = run_engine(engine, image_bytes, doc["filename"], script_type)
            if result.error and not result.text:
                if engine not in skipped_engines:
                    skipped_engines.add(engine)
                    logger.warning("%s not usable in this environment (%s) — skipping its rows.", engine, result.error)
                continue
            score = cer(result.text, doc["rendered_text"])
            results[(script_type.value, engine)].append(score)

    if "surya" not in engines:
        logger.info(SURYA_NOTE)

    rows = []
    for (script_type, engine), scores in results.items():
        rows.append(
            {
                "script_type": script_type,
                "engine": engine,
                "cer": round(sum(scores) / len(scores), 4),
                "sample_size": len(scores),
            }
        )
    return rows


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No CER rows produced — every requested engine was unusable in this environment.")
        return
    print(f"{'Script':<22}{'Engine':<16}{'CER':>8}{'N':>6}")
    for row in sorted(rows, key=lambda r: (r["script_type"], r["cer"])):
        print(f"{row['script_type']:<22}{row['engine']:<16}{row['cer']*100:>7.1f}%{row['sample_size']:>6}")


def write_to_db(rows: list[dict]) -> None:
    """Replaces the entire CerBenchmarkEntry table with freshly-measured
    rows — same "replace, don't append" pattern app/services/validation.py
    uses for ValidationResult, so /admin/cer-benchmark always reflects the
    latest run rather than accumulating stale ones."""
    db = SessionLocal()
    try:
        db.query(CerBenchmarkEntry).delete()
        for row in rows:
            db.add(CerBenchmarkEntry(
                script_type=ScriptType(row["script_type"]),
                engine=row["engine"],
                cer=row["cer"],
                sample_size=row["sample_size"],
            ))
        db.commit()
        logger.info("Wrote %d CerBenchmarkEntry rows to the database.", len(rows))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", nargs="+", default=ENGINES, choices=ENGINES)
    parser.add_argument("--synthetic-dir", type=Path, default=SYNTHETIC_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Print the table but don't write to the DB.")
    args = parser.parse_args()

    rows = run_benchmark(args.engines, args.synthetic_dir)
    print_table(rows)
    if not args.dry_run:
        if not rows:
            logger.error("Refusing to overwrite existing CerBenchmarkEntry rows with an empty result set.")
            sys.exit(1)
        write_to_db(rows)


if __name__ == "__main__":
    main()
