#!/usr/bin/env python3

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from xml.sax.saxutils import escape


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PALETTE = {
    "ink": "#14213d",
    "blue": "#3a86ff",
    "red": "#d62828",
    "gold": "#f4a261",
    "green": "#2a9d8f",
    "gray": "#6b7280",
    "light": "#e5e7eb",
    "bg": "#fffdf7",
}
QUERY_LENGTH_EDGES = [10, 15, 20, 25, 30, 40]
ANSWER_LENGTH_EDGES = [1, 2, 4, 6, 10]
A4_WIDTH = 210
A4_HEIGHT = 297
BBOX_CENTER_HEATMAP_COLS = 42
BBOX_CENTER_HEATMAP_ROWS = 59
BBOX_CENTER_HEATMAP_SIGMA = 1.35
BBOX_CENTER_HEATMAP_PALETTE = [
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


def flatten_strings(value, output):
    if isinstance(value, list):
        for item in value:
            flatten_strings(item, output)
    elif isinstance(value, str):
        output.append(value)


def count_boxes(value):
    if isinstance(value, list):
        if len(value) == 4 and all(isinstance(v, (int, float)) for v in value):
            return 1
        return sum(count_boxes(item) for item in value)
    return 0


def normalize_page_boxes(page_boxes):
    if not page_boxes:
        return []
    if isinstance(page_boxes[0], (int, float)):
        return [page_boxes]
    return page_boxes


def to_pretty_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def write_text(path, text):
    path.write_text(text, encoding="utf-8")


def svg_text(x, y, text, size=14, fill=None, anchor="start", weight="normal"):
    fill = fill or PALETTE["ink"]
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-family="Helvetica,Arial,sans-serif" text-anchor="{anchor}" '
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


def svg_circle(cx, cy, r, fill, opacity=1.0):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" opacity="{opacity}"/>'


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
    if not palette:
        return PALETTE["light"]
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


def draw_bar_chart(path, title, items, x_label=None, value_suffix="", color=None):
    width = 980
    height = 560
    left = 100
    right = 40
    top = 70
    bottom = 110
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_value = max(value for _, value in items) if items else 1
    step = plot_width / max(len(items), 1)
    bar_width = step * 0.66
    color = color or PALETTE["blue"]

    body = [svg_text(left, 36, title, size=24, weight="bold")]

    for idx, (_, value) in enumerate(items):
        tick_value = round(max_value * idx / 4)
        y = top + plot_height - plot_height * idx / 4
        body.append(svg_line(left, y, left + plot_width, y, stroke=PALETTE["light"]))
        body.append(svg_text(left - 12, y + 5, tick_value, size=12, anchor="end", fill=PALETTE["gray"]))

    body.append(svg_line(left, top + plot_height, left + plot_width, top + plot_height, stroke=PALETTE["ink"], stroke_width=1.5))

    for idx, (label, value) in enumerate(items):
        x = left + step * idx + (step - bar_width) / 2
        bar_height = 0 if max_value == 0 else plot_height * value / max_value
        y = top + plot_height - bar_height
        body.append(svg_rect(x, y, bar_width, bar_height, color, rx=4))
        body.append(svg_text(x + bar_width / 2, y - 8, f"{value}{value_suffix}", size=12, anchor="middle"))
        body.append(
            f'<text x="{x + bar_width / 2}" y="{top + plot_height + 22}" '
            f'font-size="12" fill="{PALETTE["ink"]}" font-family="Helvetica,Arial,sans-serif" '
            f'text-anchor="end" transform="rotate(-28 {x + bar_width / 2} {top + plot_height + 22})">{escape(str(label))}</text>'
        )

    if x_label:
        body.append(svg_text(width / 2, height - 18, x_label, size=13, anchor="middle", fill=PALETTE["gray"]))

    save_svg(path, width, height, "".join(body), title)


def draw_grouped_bar_chart(path, title, categories, series_names, series_values, series_colors):
    width = 1040
    height = 580
    left = 100
    right = 40
    top = 80
    bottom = 120
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_value = max(max(values) for values in series_values) if series_values else 1
    step = plot_width / max(len(categories), 1)
    inner = step * 0.82
    bar_width = inner / max(len(series_names), 1)

    body = [svg_text(left, 36, title, size=24, weight="bold")]

    for idx in range(5):
        tick_value = round(max_value * idx / 4)
        y = top + plot_height - plot_height * idx / 4
        body.append(svg_line(left, y, left + plot_width, y, stroke=PALETTE["light"]))
        body.append(svg_text(left - 12, y + 5, tick_value, size=12, anchor="end", fill=PALETTE["gray"]))

    body.append(svg_line(left, top + plot_height, left + plot_width, top + plot_height, stroke=PALETTE["ink"], stroke_width=1.5))

    for idx, label in enumerate(categories):
        group_x = left + idx * step + (step - inner) / 2
        for s_idx, values in enumerate(series_values):
            value = values[idx]
            bar_height = 0 if max_value == 0 else plot_height * value / max_value
            x = group_x + s_idx * bar_width
            y = top + plot_height - bar_height
            body.append(svg_rect(x, y, bar_width - 2, bar_height, series_colors[s_idx], rx=3))
        body.append(
            f'<text x="{group_x + inner / 2}" y="{top + plot_height + 24}" '
            f'font-size="12" fill="{PALETTE["ink"]}" font-family="Helvetica,Arial,sans-serif" '
            f'text-anchor="end" transform="rotate(-28 {group_x + inner / 2} {top + plot_height + 24})">{escape(str(label))}</text>'
        )

    legend_x = width - right - 250
    legend_y = 28
    for idx, name in enumerate(series_names):
        body.append(svg_rect(legend_x + idx * 80, legend_y, 14, 14, series_colors[idx], rx=2))
        body.append(svg_text(legend_x + idx * 80 + 20, legend_y + 12, name, size=12))

    save_svg(path, width, height, "".join(body), title)


def draw_stacked_bar_chart(path, title, labels, stacks, stack_names, stack_colors):
    width = 980
    height = 560
    left = 100
    right = 40
    top = 80
    bottom = 110
    plot_width = width - left - right
    plot_height = height - top - bottom
    totals = [sum(stacks[row][i] for row in range(len(stacks))) for i in range(len(labels))]
    max_total = max(totals) if totals else 1
    step = plot_width / max(len(labels), 1)
    bar_width = step * 0.62

    body = [svg_text(left, 36, title, size=24, weight="bold")]

    for idx in range(5):
        tick_value = round(max_total * idx / 4)
        y = top + plot_height - plot_height * idx / 4
        body.append(svg_line(left, y, left + plot_width, y, stroke=PALETTE["light"]))
        body.append(svg_text(left - 12, y + 5, tick_value, size=12, anchor="end", fill=PALETTE["gray"]))

    body.append(svg_line(left, top + plot_height, left + plot_width, top + plot_height, stroke=PALETTE["ink"], stroke_width=1.5))

    for idx, label in enumerate(labels):
        x = left + step * idx + (step - bar_width) / 2
        accumulated = 0
        for stack_idx, values in enumerate(stacks):
            value = values[idx]
            bar_height = 0 if max_total == 0 else plot_height * value / max_total
            y = top + plot_height - accumulated - bar_height
            body.append(svg_rect(x, y, bar_width, bar_height, stack_colors[stack_idx], rx=2))
            accumulated += bar_height
        body.append(svg_text(x + bar_width / 2, top + plot_height + 22, label, size=12, anchor="middle"))
        body.append(svg_text(x + bar_width / 2, top + plot_height - accumulated - 8, totals[idx], size=12, anchor="middle"))

    legend_x = width - right - 280
    legend_y = 28
    for idx, name in enumerate(stack_names):
        body.append(svg_rect(legend_x + idx * 85, legend_y, 14, 14, stack_colors[idx], rx=2))
        body.append(svg_text(legend_x + idx * 85 + 20, legend_y + 12, name, size=12))

    save_svg(path, width, height, "".join(body), title)


def draw_histogram(path, title, labels, values, color):
    items = list(zip(labels, values))
    draw_bar_chart(path, title, items, x_label="Bin", color=color)


def draw_heatmap(path, title, row_labels, col_labels, matrix, palette):
    width = 980
    height = 620
    left = 150
    top = 90
    cell_w = 86
    cell_h = 58
    body = [svg_text(left, 40, title, size=24, weight="bold")]
    max_value = max(max(row) for row in matrix) if matrix else 1

    for c_idx, label in enumerate(col_labels):
        x = left + c_idx * cell_w + cell_w / 2
        body.append(svg_text(x, top - 16, label, size=12, anchor="middle"))

    for r_idx, label in enumerate(row_labels):
        y = top + r_idx * cell_h + cell_h / 2 + 5
        body.append(svg_text(left - 16, y, label, size=12, anchor="end"))
        for c_idx, value in enumerate(matrix[r_idx]):
            ratio = 0 if max_value == 0 else value / max_value
            color_idx = min(int(ratio * (len(palette) - 1)), len(palette) - 1)
            x = left + c_idx * cell_w
            y0 = top + r_idx * cell_h
            body.append(svg_rect(x, y0, cell_w - 2, cell_h - 2, palette[color_idx], rx=6))
            text_color = "#ffffff" if ratio > 0.55 else PALETTE["ink"]
            body.append(svg_text(x + cell_w / 2, y0 + cell_h / 2 + 5, value, size=12, anchor="middle", fill=text_color, weight="bold"))

    save_svg(path, width, height, "".join(body), title)


def draw_matrix_table(path, title, row_header, col_header, row_labels, col_labels, matrix, palette):
    width = 1320
    height = 760
    left = 220
    top = 130
    cell_w = 170
    cell_h = 78
    header_h = 70
    body = [svg_text(24, 60, title, size=28, weight="bold")]
    max_value = max((max(row) for row in matrix), default=0)

    body.append(svg_text(24, top - 18, f"{row_header} \\ {col_header}", size=24, weight="bold"))

    for col_idx, label in enumerate(col_labels):
        x = left + col_idx * cell_w
        body.append(svg_text(x + cell_w / 2, top - 18, label, size=22, anchor="middle", weight="bold"))

    for row_idx, row_label in enumerate(row_labels):
        y = top + row_idx * cell_h
        body.append(svg_text(24, y + cell_h / 2 + 8, row_label, size=22, weight="normal"))
        body.append(svg_line(24, y, left + len(col_labels) * cell_w, y, stroke="#d6d3d1"))
        for col_idx, value in enumerate(matrix[row_idx]):
            ratio = 0.0 if max_value == 0 else value / max_value
            fill = sample_palette(palette, ratio ** 0.82)
            x = left + col_idx * cell_w
            body.append(svg_rect(x, y + 10, cell_w - 8, cell_h - 18, fill, stroke="none", rx=10))
            text_fill = "#ffffff" if ratio > 0.55 else PALETTE["ink"]
            body.append(
                svg_text(
                    x + cell_w / 2,
                    y + cell_h / 2 + 8,
                    value,
                    size=22,
                    anchor="middle",
                    fill=text_fill,
                    weight="bold",
                )
            )

    bottom_y = top + len(row_labels) * cell_h
    body.append(svg_line(24, bottom_y, left + len(col_labels) * cell_w, bottom_y, stroke="#d6d3d1"))
    body.append(svg_line(left - 16, top - header_h + 14, left - 16, bottom_y, stroke="#d6d3d1"))

    save_svg(path, width, height, "".join(body), title)


def draw_center_heatmap(path, title, heatmap_data):
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
        svg_text(left, 54, title, size=28, weight="bold"),
        svg_text(
            left,
            84,
            f"Fine-grained center density over {heatmap_data['total_bbox_instances']} bbox instances",
            size=14,
            fill=PALETTE["gray"],
        ),
    ]

    body.append(svg_rect(left, top, plot_width, plot_height, "#fffaf0", stroke=PALETTE["light"], rx=0))
    for row_idx, row in enumerate(heatmap_data["smoothed_counts"]):
        for col_idx, value in enumerate(row):
            ratio = 0.0 if max_value == 0 else value / max_value
            fill = sample_palette(BBOX_CENTER_HEATMAP_PALETTE, ratio ** 0.72)
            x = left + col_idx * cell_w
            y = top + row_idx * cell_h
            body.append(svg_rect(x, y, cell_w + 0.25, cell_h + 0.25, fill))

    for frac, label in [(0.0, "0%"), (0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "100%")]:
        x = left + plot_width * frac
        y = top + plot_height * frac
        body.append(svg_line(x, top, x, top + plot_height, stroke="#ffffff", stroke_width=0.7, dash="4 6"))
        body.append(svg_line(left, y, left + plot_width, y, stroke="#ffffff", stroke_width=0.7, dash="4 6"))
        body.append(svg_text(x, top + plot_height + 28, label, size=12, anchor="middle", fill=PALETTE["gray"]))
        body.append(svg_text(left - 16, y + 4, label, size=12, anchor="end", fill=PALETTE["gray"]))

    body.append(svg_rect(left, top, plot_width, plot_height, "none", stroke=PALETTE["ink"], rx=0))
    body.append(svg_text(left + plot_width / 2, top + plot_height + 72, "Page width", size=14, anchor="middle", fill=PALETTE["gray"]))
    body.append(
        f'<text x="{42}" y="{top + plot_height / 2}" font-size="14" fill="{PALETTE["gray"]}" '
        f'font-family="Helvetica,Arial,sans-serif" text-anchor="middle" transform="rotate(-90 42 {top + plot_height / 2})">Page height</text>'
    )
    body.append(svg_text(left + plot_width / 2, top - 14, "Top", size=13, anchor="middle", fill=PALETTE["gray"]))
    body.append(svg_text(left + plot_width / 2, top + plot_height + 46, "Bottom", size=13, anchor="middle", fill=PALETTE["gray"]))
    body.append(svg_text(left - 38, top + plot_height / 2, "Center Y", size=13, anchor="middle", fill=PALETTE["gray"]))
    body.append(svg_text(plot_right + right / 2 - 8, top + plot_height / 2, "A4 portrait ratio", size=13, anchor="middle", fill=PALETTE["gray"]))

    colorbar_x = plot_right + colorbar_gap
    segment_height = plot_height / 240
    for idx in range(240):
        ratio = idx / 239
        y = top + plot_height - (idx + 1) * segment_height
        fill = sample_palette(BBOX_CENTER_HEATMAP_PALETTE, ratio)
        body.append(svg_rect(colorbar_x, y, colorbar_width, segment_height + 0.5, fill))
    body.append(svg_rect(colorbar_x, top, colorbar_width, plot_height, "none", stroke=PALETTE["ink"], rx=0))
    body.append(svg_text(colorbar_x + colorbar_width / 2, top - 14, "Density", size=13, anchor="middle", fill=PALETTE["gray"]))

    for frac, label in [(0.0, "low"), (0.5, "mid"), (1.0, "high")]:
        y = top + plot_height - plot_height * frac
        value = max_value * frac
        body.append(svg_line(colorbar_x + colorbar_width, y, colorbar_x + colorbar_width + 8, y, stroke=PALETTE["gray"]))
        body.append(
            svg_text(
                colorbar_x + colorbar_width + 14,
                y + 4,
                f"{label} ({value:.1f})",
                size=12,
                fill=PALETTE["gray"],
            )
        )

    save_svg(path, width, height, "".join(body), title)


def analyze_dataset(input_path, benchmark_dir):
    category_counts = Counter()
    docs_per_category = defaultdict(set)
    subimg_counts = Counter()
    combo_counts = Counter()
    category_modality = defaultdict(Counter)
    page_count_hist = Counter()
    bbox_count_hist = Counter()
    query_lengths = []
    answer_lengths = []
    samples_per_doc = Counter()
    bbox_area_ratios = []
    bbox_center_grid = [[0 for _ in range(3)] for _ in range(3)]
    bbox_center_heatmap = [
        [0 for _ in range(BBOX_CENTER_HEATMAP_COLS)]
        for _ in range(BBOX_CENTER_HEATMAP_ROWS)
    ]
    total_bbox_instances = 0

    with input_path.open("r", encoding="utf-8") as infile:
        for line in infile:
            record = json.loads(line)
            category = record["category"]
            doc_name = record["doc_name"]
            category_counts[category] += 1
            docs_per_category[category].add(doc_name)
            samples_per_doc[(category, doc_name)] += 1
            query_lengths.append(len(record["query"].split()))
            answer_lengths.append(len(record["answer"].split()))

            pages = record.get("evidence_page", [])
            page_total = len(pages) if isinstance(pages, list) else 1
            page_count_hist[page_total] += 1

            bbox = record.get("bbox", [])
            bbox_total = count_boxes(bbox)
            bbox_count_hist[bbox_total] += 1

            modalities = []
            flatten_strings(record.get("subimg_type", []), modalities)
            unique_modalities = tuple(sorted(set(modalities)))
            combo_counts[unique_modalities] += 1
            for modality in set(modalities):
                subimg_counts[modality] += 1
                category_modality[category][modality] += 1

            bbox_pages = record.get("bbox", [])
            for page_idx, page in enumerate(pages):
                image_path = benchmark_dir / category / doc_name / f"{doc_name}_{page}.png"
                width, height = png_size(image_path)
                page_boxes = normalize_page_boxes(bbox_pages[page_idx] if page_idx < len(bbox_pages) else [])
                for box in page_boxes:
                    if len(box) != 4:
                        continue
                    x1, y1, x2, y2 = [float(v) for v in box]
                    box_width = max(0.0, x2 - x1)
                    box_height = max(0.0, y2 - y1)
                    area_ratio = (box_width * box_height) / (width * height)
                    bbox_area_ratios.append(area_ratio)
                    center_x = min(max((x1 + x2) / 2 / width, 0.0), 0.999999)
                    center_y = min(max((y1 + y2) / 2 / height, 0.0), 0.999999)
                    grid_x = min(int(center_x * 3), 2)
                    grid_y = min(int(center_y * 3), 2)
                    bbox_center_grid[grid_y][grid_x] += 1
                    heatmap_x = min(int(center_x * BBOX_CENTER_HEATMAP_COLS), BBOX_CENTER_HEATMAP_COLS - 1)
                    heatmap_y = min(int(center_y * BBOX_CENTER_HEATMAP_ROWS), BBOX_CENTER_HEATMAP_ROWS - 1)
                    bbox_center_heatmap[heatmap_y][heatmap_x] += 1
                    total_bbox_instances += 1

    area_bins = Counter()
    for value in bbox_area_ratios:
        if value < 0.05:
            area_bins["<5%"] += 1
        elif value < 0.10:
            area_bins["5-10%"] += 1
        elif value < 0.15:
            area_bins["10-15%"] += 1
        elif value < 0.20:
            area_bins["15-20%"] += 1
        elif value < 0.30:
            area_bins["20-30%"] += 1
        else:
            area_bins[">30%"] += 1

    docs_count_list = [len(docs) for docs in docs_per_category.values()]
    samples_per_doc_list = list(samples_per_doc.values())
    smoothed_bbox_center_heatmap = smooth_matrix(bbox_center_heatmap, BBOX_CENTER_HEATMAP_SIGMA)

    summary = {
        "num_records": sum(category_counts.values()),
        "num_categories": len(category_counts),
        "num_docs": len(samples_per_doc),
        "total_bbox_instances": total_bbox_instances,
        "records_per_doc_avg": round(mean(samples_per_doc_list), 3),
        "records_per_doc_median": median(samples_per_doc_list),
        "docs_per_category_avg": round(mean(docs_count_list), 3),
        "multi_page_records": sum(v for k, v in page_count_hist.items() if k > 1),
        "multi_bbox_records": sum(v for k, v in bbox_count_hist.items() if k > 1),
        "query_length_avg": round(mean(query_lengths), 3),
        "answer_length_avg": round(mean(answer_lengths), 3),
        "bbox_area_ratio_avg": round(mean(bbox_area_ratios), 6),
        "bbox_area_ratio_median": round(median(bbox_area_ratios), 6),
    }

    tables = {
        "category_counts": dict(sorted(category_counts.items())),
        "docs_per_category": {key: len(value) for key, value in sorted(docs_per_category.items())},
        "subimg_counts": dict(sorted(subimg_counts.items())),
        "modality_combinations": {" + ".join(key): value for key, value in combo_counts.most_common()},
        "category_modality": {key: dict(sorted(value.items())) for key, value in sorted(category_modality.items())},
        "page_count_hist": dict(sorted(page_count_hist.items())),
        "bbox_count_hist": dict(sorted(bbox_count_hist.items())),
        "bbox_area_bins": dict(area_bins),
    }

    series = {
        "query_length_bins": build_length_bins(query_lengths, QUERY_LENGTH_EDGES),
        "answer_length_bins": build_length_bins(answer_lengths, ANSWER_LENGTH_EDGES),
        "qa_length_matrix": build_joint_length_matrix(
            query_lengths,
            answer_lengths,
            QUERY_LENGTH_EDGES,
            ANSWER_LENGTH_EDGES,
        ),
        "samples_per_doc_top10": [
            {"category": cat, "doc_name": doc, "samples": count}
            for (cat, doc), count in samples_per_doc.most_common(10)
        ],
        "bbox_center_grid": bbox_center_grid,
        "bbox_center_heatmap": {
            "rows": BBOX_CENTER_HEATMAP_ROWS,
            "cols": BBOX_CENTER_HEATMAP_COLS,
            "sigma": BBOX_CENTER_HEATMAP_SIGMA,
            "raw_counts": bbox_center_heatmap,
            "smoothed_counts": [
                [round(value, 4) for value in row]
                for row in smoothed_bbox_center_heatmap
            ],
            "max_raw_count": max((max(row) for row in bbox_center_heatmap), default=0),
            "max_smoothed_count": round(
                max((max(row) for row in smoothed_bbox_center_heatmap), default=0.0),
                4,
            ),
            "total_bbox_instances": total_bbox_instances,
        },
    }

    return summary, tables, series


def build_length_bins(values, edges):
    labels = []
    counts = [0 for _ in range(len(edges) + 1)]
    previous = None
    for edge in edges:
        if previous is None:
            labels.append(f"<={edge}")
        elif previous + 1 == edge:
            labels.append(str(edge))
        else:
            labels.append(f"{previous + 1}-{edge}")
        previous = edge
    labels.append(f">{edges[-1]}")

    for value in values:
        placed = False
        for idx, edge in enumerate(edges):
            if value <= edge:
                counts[idx] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return {"labels": labels, "counts": counts}


def assign_bin(value, edges):
    for idx, edge in enumerate(edges):
        if value <= edge:
            return idx
    return len(edges)


def build_joint_length_matrix(query_lengths, answer_lengths, query_edges, answer_edges):
    matrix = [[0 for _ in range(len(answer_edges) + 1)] for _ in range(len(query_edges) + 1)]
    for query_length, answer_length in zip(query_lengths, answer_lengths):
        query_idx = assign_bin(query_length, query_edges)
        answer_idx = assign_bin(answer_length, answer_edges)
        matrix[query_idx][answer_idx] += 1
    return {
        "row_labels": build_length_bins([], query_edges)["labels"],
        "col_labels": build_length_bins([], answer_edges)["labels"],
        "matrix": matrix,
    }


def write_summary_table(path, summary, tables):
    lines = ["metric\tvalue"]
    for key, value in summary.items():
        lines.append(f"{key}\t{value}")
    lines.append("")
    lines.append("category\tsamples\tdocuments")
    category_counts = tables["category_counts"]
    docs_per_category = tables["docs_per_category"]
    for category in category_counts:
        lines.append(f"{category}\t{category_counts[category]}\t{docs_per_category[category]}")
    write_text(path, "\n".join(lines) + "\n")


def generate_figures(output_dir, summary, tables, series):
    draw_bar_chart(
        output_dir / "category_distribution.svg",
        "Samples per Category",
        list(tables["category_counts"].items()),
        x_label="Category",
        color=PALETTE["blue"],
    )

    draw_grouped_bar_chart(
        output_dir / "category_modality_heatmap.svg",
        "Modality Coverage by Category",
        list(tables["category_modality"].keys()),
        ["text", "image", "table"],
        [
            [tables["category_modality"][cat].get("text", 0) for cat in tables["category_modality"]],
            [tables["category_modality"][cat].get("image", 0) for cat in tables["category_modality"]],
            [tables["category_modality"][cat].get("table", 0) for cat in tables["category_modality"]],
        ],
        [PALETTE["ink"], PALETTE["blue"], PALETTE["gold"]],
    )

    combo_items = list(tables["modality_combinations"].items())[:6]
    draw_bar_chart(
        output_dir / "modality_combinations.svg",
        "Top Modality Combinations",
        combo_items,
        x_label="Combination",
        color=PALETTE["green"],
    )

    draw_stacked_bar_chart(
        output_dir / "complexity_breakdown.svg",
        "Reasoning Complexity",
        ["Single-page", "Multi-page", "Single-box", "Multi-box"],
        [
            [summary["num_records"] - summary["multi_page_records"], summary["multi_page_records"], 0, 0],
            [0, 0, summary["num_records"] - summary["multi_bbox_records"], summary["multi_bbox_records"]],
        ],
        ["count", "count"],
        [PALETTE["blue"], PALETTE["red"]],
    )

    draw_histogram(
        output_dir / "bbox_area_distribution.svg",
        "BBox Area Ratio Distribution",
        list(tables["bbox_area_bins"].keys()),
        list(tables["bbox_area_bins"].values()),
        PALETTE["red"],
    )

    draw_center_heatmap(
        output_dir / "bbox_center_heatmap.svg",
        "BBox Center Distribution",
        series["bbox_center_heatmap"],
    )

    draw_matrix_table(
        output_dir / "qa_length_distribution.svg",
        "Query × Answer Length Matrix",
        "Query",
        "Answer",
        series["qa_length_matrix"]["row_labels"],
        series["qa_length_matrix"]["col_labels"],
        series["qa_length_matrix"]["matrix"],
        ["#fff7ed", "#fed7aa", "#fdba74", "#fb923c", "#ea580c", "#9a3412"],
    )

    draw_heatmap(
        output_dir / "category_modality_matrix.svg",
        "Category × Modality Matrix",
        ["text", "image", "table"],
        list(tables["category_modality"].keys()),
        [
            [tables["category_modality"][cat].get("text", 0) for cat in tables["category_modality"]],
            [tables["category_modality"][cat].get("image", 0) for cat in tables["category_modality"]],
            [tables["category_modality"][cat].get("table", 0) for cat in tables["category_modality"]],
        ],
        ["#fef3c7", "#fcd34d", "#f59e0b", "#d97706", "#92400e"],
    )


def rebin_answer_counts(answer_bins, target_len):
    counts = answer_bins["counts"]
    if len(counts) >= target_len:
        return counts[:target_len]
    padded = list(counts)
    while len(padded) < target_len:
        padded.append(0)
    return padded


def main():
    parser = argparse.ArgumentParser(
        description="Analyze the BBox-DocVQA benchmark and export publication-ready SVG figures."
    )
    parser.add_argument("--input", default="benchmark/bbox-docvqa.jsonl", help="Input benchmark JSONL.")
    parser.add_argument("--benchmark-dir", default="benchmark", help="Root directory of page PNG files.")
    parser.add_argument(
        "--output-dir",
        default="code/analysis_out",
        help="Output directory for SVG figures and summary JSON/TSV files.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    benchmark_dir = Path(args.benchmark_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    ensure_dir(output_dir)

    summary, tables, series = analyze_dataset(input_path, benchmark_dir)

    write_text(output_dir / "summary.json", to_pretty_json(summary))
    write_text(output_dir / "tables.json", to_pretty_json(tables))
    write_text(output_dir / "series.json", to_pretty_json(series))
    write_summary_table(output_dir / "summary.tsv", summary, tables)
    generate_figures(output_dir, summary, tables, series)

    print(f"Wrote analysis outputs to: {output_dir}")


if __name__ == "__main__":
    main()
