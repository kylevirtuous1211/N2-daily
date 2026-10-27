"""Render image crops for official questions from the original PDFs.

Usage (PyMuPDF is only needed for this import step, so it is not a project dependency):
    uv run --with pymupdf python tools/official_crops.py

Every question with "image_crop": {"field", "pdf", "page", "box": [x0, y0, x1, y1]} (fractions of the page)
gets its field (passage_image / question_image) set to the rendered PNG under content/official/crops/.
"image_crop" may also be a list of such specs. The spec is kept so crops can be regenerated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

OFFICIAL_DIR = Path(__file__).resolve().parent.parent / "content" / "official"
DPI = 200


def main() -> int:
    written = 0
    for path in sorted((OFFICIAL_DIR / "questions").glob("*.json")):
        questions = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for question in questions:
            specs = question.get("image_crop")
            if not specs:
                continue
            for spec in specs if isinstance(specs, list) else [specs]:
                official_set = question["official"]["set"]
                pdf_path = OFFICIAL_DIR / "raw" / official_set / f"{spec['pdf']}.pdf"
                with pymupdf.open(pdf_path) as document:
                    page = document[spec["page"] - 1]
                    width, height = page.rect.width, page.rect.height
                    x0, y0, x1, y1 = spec["box"]
                    clip = pymupdf.Rect(x0 * width, y0 * height, x1 * width, y1 * height) & page.rect
                    relative = f"crops/{official_set}/{question['id']}-{spec['field']}.png"
                    target = OFFICIAL_DIR / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    page.get_pixmap(dpi=DPI, clip=clip).save(target)
                if question.get(spec["field"]) != relative:
                    question[spec["field"]] = relative
                    changed = True
                written += 1
                print(f"{question['id']:14} {spec['field']:15} {spec['pdf']} p{spec['page']} -> {relative}")
        if changed:
            path.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{written} crops written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
