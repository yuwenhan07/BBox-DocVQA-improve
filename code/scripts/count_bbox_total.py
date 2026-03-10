import argparse
import json
from pathlib import Path


DEFAULT_JSONL_PATH = Path("LlamaFactory/data/bbox_docvqa_crop/bbox_docvqa_rel_crop.jsonl")


def is_bbox(item):
    return (
        isinstance(item, list)
        and len(item) == 4
        and all(isinstance(value, (int, float)) for value in item)
    )


def count_bboxes(item):
    if is_bbox(item):
        return 1
    if isinstance(item, list):
        return sum(count_bboxes(child) for child in item)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Count total bbox blocks in a JSONL file.")
    parser.add_argument(
        "jsonl_path",
        nargs="?",
        default=str(DEFAULT_JSONL_PATH),
        help="Path to the JSONL file.",
    )
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl_path)
    total_bboxes = 0
    total_samples = 0

    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            record = json.loads(line)
            total_samples += 1
            total_bboxes += count_bboxes(record.get("bbox", []))

    print(f"文件: {jsonl_path}")
    print(f"样本数: {total_samples}")
    print(f"bbox 总数: {total_bboxes}")


if __name__ == "__main__":
    main()
