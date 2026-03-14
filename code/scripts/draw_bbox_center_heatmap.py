#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PALETTE = {
    "ink": "#14213d",
    "gray": "#6b7280",
    "light": "#e5e7eb",
    "bg": "#fffdf7",
}
FONT_FAMILY = "'Comic Sans MS', 'Comic Sans', cursive"
A4_WIDTH = 210
A4_HEIGHT = 297
DEFAULT_PALETTE = [
    "#fff7ec",
    "#fee8c8",
    "#fdd49e",
    "#fdbb84",
    "#fc8d59",
    "#ef6548",
    "#d7301f",
    "#990000",
]


def png_size(path):
    with path.open("rb") as file_obj:
        header = file_obj.read(24)
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


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def svg_text(x, y, text, size=14, fill=None, anchor="start", weight="normal"):
    fill = fill or PALETTE["ink"]
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-family="{FONT_FAMILY}" text-anchor="{anchor}" '
        f'font-weight="{weight}">{escape(str(text))}</text>'
    )


def svg_rect(x, y, width, height, fill, stroke="none", rx=0, opacity=1.0):
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" '
        f'stroke="{stroke}" rx="{rx}" opacity="{opacity}"/>'
    )


def svg_line(x1, y1, x2, y2, stroke=None, stroke_width=1, dash=None):
    stroke = stroke or PALETTE["gray"]
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"{dash_attr}/>'
    )


def wrap_svg(width, height, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<title>{escape(title)}</title>'
        f'{svg_rect(0, 0, width, height, PALETTE["bg"])}'
        f"{body}</svg>"
    )


def save_svg(path, width, height, body, title):
    write_text(path, wrap_svg(width, height, body, title))


def clamp(value, lower, upper):
    return max(lower, min(value, upper))


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[idx : idx + 2], 16) for idx in range(0, 6, 2))


def interpolate_color(color_a, color_b, ratio):
    ratio = clamp(ratio, 0.0, 1.0)
    rgb_a = hex_to_rgb(color_a)
    rgb_b = hex_to_rgb(color_b)
    channels = [
        round(channel_a + (channel_b - channel_a) * ratio)
        for channel_a, channel_b in zip(rgb_a, rgb_b)
    ]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def sample_palette(palette, ratio):
    if len(palette) == 1:
        return palette[0]
    ratio = clamp(ratio, 0.0, 1.0)
    scaled = ratio * (len(palette) - 1)
    lower = int(math.floor(scaled))
    upper = min(lower + 1, len(palette) - 1)
    if lower == upper:
        return palette[lower]
    return interpolate_color(palette[lower], palette[upper], scaled - lower)


def gaussian_kernel_1d(sigma):
    radius = max(1, int(math.ceil(sigma * 3)))
    weights = []
    for offset in range(-radius, radius + 1):
        weights.append(math.exp(-(offset ** 2) / (2 * sigma ** 2)))
    total = sum(weights) or 1.0
    return [value / total for value in weights]


def smooth_matrix(matrix, sigma):
    if not matrix or not matrix[0]:
        return matrix
    kernel = gaussian_kernel_1d(sigma)
    radius = len(kernel) // 2
    height = len(matrix)
    width = len(matrix[0])

    horizontal = []
    for row in matrix:
        smoothed_row = []
        for x in range(width):
            total = 0.0
            for offset, weight in enumerate(kernel):
                src_x = clamp(x + offset - radius, 0, width - 1)
                total += row[src_x] * weight
            smoothed_row.append(total)
        horizontal.append(smoothed_row)

    smoothed = []
    for y in range(height):
        smoothed_row = []
        for x in range(width):
            total = 0.0
            for offset, weight in enumerate(kernel):
                src_y = clamp(y + offset - radius, 0, height - 1)
                total += horizontal[src_y][x] * weight
            smoothed_row.append(total)
        smoothed.append(smoothed_row)
    return smoothed


def collect_bbox_center_heatmap(input_path, benchmark_dir, rows, cols):
    heatmap = [[0 for _ in range(cols)] for _ in range(rows)]
    total_bbox_instances = 0

    with input_path.open("r", encoding="utf-8") as infile:
        for line in infile:
            record = json.loads(line)
            category = record["category"]
            doc_name = record["doc_name"]
            pages = record.get("evidence_page", [])
            bbox_pages = record.get("bbox", [])

            for page_idx, page in enumerate(pages):
                image_path = benchmark_dir / category / doc_name / f"{doc_name}_{page}.png"
                width, height = png_size(image_path)
                page_boxes = normalize_page_boxes(
                    bbox_pages[page_idx] if page_idx < len(bbox_pages) else []
                )
                for box in page_boxes:
                    if len(box) != 4:
                        continue
                    x1, y1, x2, y2 = [float(value) for value in box]
                    center_x = min(max((x1 + x2) / 2 / width, 0.0), 0.999999)
                    center_y = min(max((y1 + y2) / 2 / height, 0.0), 0.999999)
                    grid_x = min(int(center_x * cols), cols - 1)
                    grid_y = min(int(center_y * rows), rows - 1)
                    heatmap[grid_y][grid_x] += 1
                    total_bbox_instances += 1

    return heatmap, total_bbox_instances


def build_heatmap_data(input_path, benchmark_dir, rows, cols, sigma):
    raw_counts, total_bbox_instances = collect_bbox_center_heatmap(
        input_path=input_path,
        benchmark_dir=benchmark_dir,
        rows=rows,
        cols=cols,
    )
    smoothed_counts = smooth_matrix(raw_counts, sigma)
    return {
        "rows": rows,
        "cols": cols,
        "sigma": sigma,
        "raw_counts": raw_counts,
        "smoothed_counts": smoothed_counts,
        "max_raw_count": max((max(row) for row in raw_counts), default=0),
        "max_smoothed_count": max((max(row) for row in smoothed_counts), default=0.0),
        "total_bbox_instances": total_bbox_instances,
    }


def draw_center_heatmap(path, title, heatmap_data, palette):
    width = 840
    height = 1188
    left = 96
    top = 148
    right = 76
    colorbar_gap = 24
    colorbar_width = 24
    plot_width = width - left - right - colorbar_gap - colorbar_width
    plot_height = plot_width * A4_HEIGHT / A4_WIDTH
    plot_right = left + plot_width
    max_value = heatmap_data["max_smoothed_count"]
    rows = heatmap_data["rows"]
    cols = heatmap_data["cols"]
    cell_w = plot_width / cols
    cell_h = plot_height / rows

    body = [
        svg_text(left, 58, title, size=34, weight="bold"),
        svg_text(
            left,
            94,
            f"Fine-grained center density over {heatmap_data['total_bbox_instances']} bbox instances",
            size=18,
            fill=PALETTE["gray"],
        ),
    ]

    body.append(svg_rect(left, top, plot_width, plot_height, "#fffaf0", stroke=PALETTE["light"]))
    for row_idx, row in enumerate(heatmap_data["smoothed_counts"]):
        for col_idx, value in enumerate(row):
            ratio = 0.0 if max_value == 0 else value / max_value
            fill = sample_palette(palette, ratio ** 0.72)
            x = left + col_idx * cell_w
            y = top + row_idx * cell_h
            body.append(svg_rect(x, y, cell_w + 0.25, cell_h + 0.25, fill))

    for frac, label in [(0.0, "0%"), (0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "100%")]:
        x = left + plot_width * frac
        y = top + plot_height * frac
        body.append(svg_line(x, top, x, top + plot_height, stroke="#ffffff", stroke_width=0.7, dash="4 6"))
        body.append(svg_line(left, y, left + plot_width, y, stroke="#ffffff", stroke_width=0.7, dash="4 6"))
        body.append(svg_text(x, top + plot_height + 32, label, size=15, anchor="middle", fill=PALETTE["gray"]))
        body.append(svg_text(left - 18, y + 5, label, size=15, anchor="end", fill=PALETTE["gray"]))

    body.append(svg_rect(left, top, plot_width, plot_height, "none", stroke=PALETTE["ink"]))
    body.append(svg_text(left + plot_width / 2, top + plot_height + 80, "Page width", size=18, anchor="middle", fill=PALETTE["gray"]))
    body.append(
        f'<text x="{42}" y="{top + plot_height / 2}" font-size="18" fill="{PALETTE["gray"]}" '
        f'font-family="{FONT_FAMILY}" text-anchor="middle" transform="rotate(-90 42 {top + plot_height / 2})">Page height</text>'
    )
    body.append(svg_text(left + plot_width / 2, top - 18, "Top", size=16, anchor="middle", fill=PALETTE["gray"]))
    body.append(svg_text(left + plot_width / 2, top + plot_height + 50, "Bottom", size=16, anchor="middle", fill=PALETTE["gray"]))

    colorbar_x = plot_right + colorbar_gap
    segment_height = plot_height / 240
    for idx in range(240):
        ratio = idx / 239
        y = top + plot_height - (idx + 1) * segment_height
        fill = sample_palette(palette, ratio)
        body.append(svg_rect(colorbar_x, y, colorbar_width, segment_height + 0.5, fill))
    body.append(svg_rect(colorbar_x, top, colorbar_width, plot_height, "none", stroke=PALETTE["ink"]))
    body.append(svg_text(colorbar_x + colorbar_width / 2, top - 18, "Density", size=16, anchor="middle", fill=PALETTE["gray"]))

    for frac, label in [(0.0, "low"), (0.5, "mid"), (1.0, "high")]:
        y = top + plot_height - plot_height * frac
        value = max_value * frac
        body.append(svg_line(colorbar_x + colorbar_width, y, colorbar_x + colorbar_width + 8, y, stroke=PALETTE["gray"]))
        body.append(svg_text(colorbar_x + colorbar_width + 14, y + 5, f"{label} ({value:.1f})", size=15, fill=PALETTE["gray"]))

    save_svg(path, width, height, "".join(body), title)


def parse_palette(value):
    colors = [item.strip() for item in value.split(",") if item.strip()]
    if len(colors) < 2:
        raise ValueError("Palette must contain at least two comma-separated colors.")
    return colors


def main():
    parser = argparse.ArgumentParser(
        description="Draw a fine-grained A4 bbox-center heatmap as SVG."
    )
    parser.add_argument("--input", default="benchmark/bbox-docvqa.jsonl", help="Input benchmark JSONL.")
    parser.add_argument("--benchmark-dir", default="benchmark", help="Root directory of page PNG files.")
    parser.add_argument(
        "--output",
        default="code/scripts/analysis_out/bbox_center_heatmap.svg",
        help="Output SVG path.",
    )
    parser.add_argument("--title", default="BBox Center Distribution", help="Figure title.")
    parser.add_argument("--rows", type=int, default=59, help="Heatmap grid rows.")
    parser.add_argument("--cols", type=int, default=42, help="Heatmap grid cols.")
    parser.add_argument("--sigma", type=float, default=1.35, help="Gaussian smoothing sigma.")
    parser.add_argument(
        "--palette",
        default=",".join(DEFAULT_PALETTE),
        help="Comma-separated heatmap colors from low to high density.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    benchmark_dir = Path(args.benchmark_dir).resolve()
    output_path = Path(args.output).resolve()
    palette = parse_palette(args.palette)

    heatmap_data = build_heatmap_data(
        input_path=input_path,
        benchmark_dir=benchmark_dir,
        rows=args.rows,
        cols=args.cols,
        sigma=args.sigma,
    )
    draw_center_heatmap(
        path=output_path,
        title=args.title,
        heatmap_data=heatmap_data,
        palette=palette,
    )
    print(f"Wrote bbox center heatmap to: {output_path}")


if __name__ == "__main__":
    main()
