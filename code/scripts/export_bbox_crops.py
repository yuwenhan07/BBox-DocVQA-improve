'''
python export_bbox_crops.py \
    --input ../../benchmark/bbox-docvqa.jsonl \
    --benchmark-dir ../../benchmark \
    --output-dir ./bbox_crops_out \
    --limit 10
'''
#!/usr/bin/env python3

import argparse
import json
import struct
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_chunks(data):
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        crc = data[offset + 8 + length:offset + 12 + length]
        yield chunk_type, chunk_data, crc
        offset += 12 + length


def paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def load_png_rgb(path):
    data = path.read_bytes()
    if data[:8] != PNG_SIGNATURE:
        raise ValueError(f"Not a PNG file: {path}")

    width = height = None
    bit_depth = color_type = interlace = None
    idat_parts = []

    for chunk_type, chunk_data, _crc in read_chunks(data):
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _comp, _flt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width is None:
        raise ValueError(f"Missing IHDR: {path}")
    if bit_depth != 8 or color_type != 2 or interlace != 0:
        raise ValueError(
            f"Unsupported PNG format for {path}: bit_depth={bit_depth}, "
            f"color_type={color_type}, interlace={interlace}"
        )

    bytes_per_pixel = 3
    stride = width * bytes_per_pixel
    raw = zlib.decompress(b"".join(idat_parts))
    expected = height * (1 + stride)
    if len(raw) != expected:
        raise ValueError(f"Unexpected decompressed size for {path}: {len(raw)} != {expected}")

    rows = []
    prev_row = bytearray(stride)
    offset = 0

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        filtered = bytearray(raw[offset:offset + stride])
        offset += stride
        row = bytearray(stride)

        if filter_type == 0:
            row[:] = filtered
        elif filter_type == 1:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                row[i] = (filtered[i] + left) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                row[i] = (filtered[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up = prev_row[i]
                row[i] = (filtered[i] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up = prev_row[i]
                up_left = prev_row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                row[i] = (filtered[i] + paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"Unsupported PNG filter {filter_type} in {path}")

        rows.append(bytes(row))
        prev_row = row

    return width, height, rows


def png_chunk(chunk_type, chunk_data):
    return (
        struct.pack(">I", len(chunk_data))
        + chunk_type
        + chunk_data
        + struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
    )


def save_png_rgb(path, width, height, rows):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    compressed = zlib.compress(raw, level=9)
    png = (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", compressed)
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def normalize_page_boxes(page_boxes):
    if not page_boxes:
        return []
    if isinstance(page_boxes[0], (int, float)):
        return [page_boxes]
    return page_boxes


def normalize_page_types(page_types, size):
    if not page_types:
        return ["unknown"] * size
    if isinstance(page_types, str):
        return [page_types]
    return page_types


def clamp_bbox(box, width, height):
    x1, y1, x2, y2 = [int(v) for v in box]
    x1 = max(0, min(x1, width))
    x2 = max(0, min(x2, width))
    y1 = max(0, min(y1, height))
    y2 = max(0, min(y2, height))
    if x2 <= x1:
        x2 = min(width, x1 + 1)
    if y2 <= y1:
        y2 = min(height, y1 + 1)
    return x1, y1, x2, y2


def crop_rows(rows, bbox):
    x1, y1, x2, y2 = bbox
    start = x1 * 3
    end = x2 * 3
    return [row[start:end] for row in rows[y1:y2]]


def export_crops(input_jsonl, benchmark_dir, output_dir, limit):
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    with input_jsonl.open("r", encoding="utf-8") as infile:
        for sample_idx, line in enumerate(infile, start=1):
            if sample_idx > limit:
                break

            record = json.loads(line)
            category = record["category"]
            doc_name = record["doc_name"]
            pages = record.get("evidence_page", [])
            bbox_pages = record.get("bbox", [])
            type_pages = record.get("subimg_type", [])

            for page_idx, page in enumerate(pages):
                image_path = benchmark_dir / category / doc_name / f"{doc_name}_{page}.png"
                image_path = benchmark_dir / category / doc_name / f"{page}.png"
                if not image_path.exists():
                    continue

                width, height, rows = load_png_rgb(image_path)
                page_boxes = normalize_page_boxes(bbox_pages[page_idx] if page_idx < len(bbox_pages) else [])
                page_types = normalize_page_types(type_pages[page_idx] if page_idx < len(type_pages) else [], len(page_boxes))

                for region_idx, box in enumerate(page_boxes, start=1):
                    if len(box) != 4:
                        continue

                    bbox = clamp_bbox(box, width, height)
                    crop = crop_rows(rows, bbox)
                    crop_width = bbox[2] - bbox[0]
                    crop_height = bbox[3] - bbox[1]
                    region_type = page_types[region_idx - 1] if region_idx - 1 < len(page_types) else "unknown"

                    out_name = (
                        f"sample_{sample_idx:03d}"
                        f"_{category}_{doc_name}_p{page}_r{region_idx}_{region_type}.png"
                    )
                    out_path = output_dir / out_name
                    save_png_rgb(out_path, crop_width, crop_height, crop)

                    manifest.append(
                        {
                            "sample_index": sample_idx,
                            "query": record["query"],
                            "answer": record["answer"],
                            "category": category,
                            "doc_name": doc_name,
                            "page": page,
                            "region_index": region_idx,
                            "subimg_type": region_type,
                            "bbox": list(bbox),
                            "source_image": str(image_path),
                            "crop_image": str(out_path),
                            "crop_size": [crop_width, crop_height],
                        }
                    )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, len(manifest)


def main():
    parser = argparse.ArgumentParser(description="Crop bbox regions from benchmark page PNGs.")
    parser.add_argument("--input", default="benchmark/bbox-docvqa.jsonl")
    parser.add_argument("--benchmark-dir", default="benchmark")
    parser.add_argument("--output-dir", default="code/bbox_crops_out")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    input_jsonl = Path(args.input).resolve()
    benchmark_dir = Path(args.benchmark_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    manifest_path, crop_count = export_crops(input_jsonl, benchmark_dir, output_dir, args.limit)
    print(f"Exported {crop_count} crop(s)")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
