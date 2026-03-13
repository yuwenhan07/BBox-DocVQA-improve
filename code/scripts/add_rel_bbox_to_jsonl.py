#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path):
    with path.open("rb") as f:
        header = f.read(24)
    if header[:8] != PNG_SIGNATURE:
        raise ValueError(f"Unsupported image format: {path}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return width, height


def normalize_page_boxes(page_boxes):
    if not page_boxes:
        return []
    if isinstance(page_boxes[0], (int, float)):
        return [page_boxes]
    return page_boxes


def normalize_bbox(box, width, height, precision):
    x1, y1, x2, y2 = [float(v) for v in box]
    rel_box = [
        round(x1 / width * 1000, precision),
        round(y1 / height * 1000, precision),
        round(x2 / width * 1000, precision),
        round(y2 / height * 1000, precision),
    ]
    return rel_box


def build_rel_bbox(record, benchmark_dir, precision):
    category = record["category"]
    doc_name = record["doc_name"]
    pages = record.get("evidence_page", [])
    bbox_pages = record.get("bbox", [])
    rel_bbox_pages = []

    for page_idx, page in enumerate(pages):
        image_path = benchmark_dir / category / doc_name / f"{doc_name}_{page}.png"
        if not image_path.exists():
            raise FileNotFoundError(f"Page image not found: {image_path}")

        width, height = png_size(image_path)
        page_boxes = normalize_page_boxes(bbox_pages[page_idx] if page_idx < len(bbox_pages) else [])
        rel_page_boxes = []

        for box in page_boxes:
            if len(box) != 4:
                continue
            rel_page_boxes.append(normalize_bbox(box, width, height, precision))

        rel_bbox_pages.append(rel_page_boxes)

    return rel_bbox_pages


def rename_and_reorder_record(record, rel_bbox):
    ordered_record = {}

    for key, value in record.items():
        ordered_record[key] = value

        if key == "bbox":
            ordered_record["rel_bbox"] = rel_bbox

    if "bbox" not in ordered_record:
        ordered_record["rel_bbox"] = rel_bbox

    if "subimg_type" in record:
        ordered_record["subimg_type"] = record["subimg_type"]

    if "category" in record:
        category_value = ordered_record.pop("category", record["category"])
        ordered_record["category"] = category_value

    return ordered_record


def convert_jsonl(input_path, benchmark_dir, output_path, precision):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as infile, output_path.open(
        "w", encoding="utf-8"
    ) as outfile:
        for line in infile:
            record = json.loads(line)
            rel_bbox = build_rel_bbox(record, benchmark_dir, precision)
            ordered_record = rename_and_reorder_record(record, rel_bbox)
            outfile.write(json.dumps(ordered_record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Add normalized 0-1000 rel_bbox fields to the bbox-docvqa JSONL."
    )
    parser.add_argument("--input", default="benchmark/bbox-docvqa.jsonl")
    parser.add_argument("--benchmark-dir", default="benchmark")
    parser.add_argument(
        "--output",
        default="benchmark/bbox-docvqa-rel.jsonl",
        help="Output JSONL with added rel_bbox field.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=6,
        help="Decimal places for 0-1000 normalized coordinates.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    benchmark_dir = Path(args.benchmark_dir).resolve()
    output_path = Path(args.output).resolve()

    convert_jsonl(input_path, benchmark_dir, output_path, args.precision)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
