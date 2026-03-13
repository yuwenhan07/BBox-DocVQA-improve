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


def draw_center_heatmap(path, title, grid_counts):
    width = 620
    height = 620
    left = 110
    top = 90
    cell = 120
    body = [svg_text(left, 40, title, size=24, weight="bold")]
    max_value = max(max(row) for row in grid_counts)
    palette = ["#fff5eb", "#fee6ce", "#fdae6b", "#f16913", "#a63603"]

    for row in range(3):
        for col in range(3):
            value = grid_counts[row][col]
            ratio = 0 if max_value == 0 else value / max_value
            color_idx = min(int(ratio * (len(palette) - 1)), len(palette) - 1)
            x = left + col * cell
            y = top + row * cell
            body.append(svg_rect(x, y, cell - 4, cell - 4, palette[color_idx], rx=8))
            text_color = "#ffffff" if ratio > 0.55 else PALETTE["ink"]
            body.append(svg_text(x + cell / 2, y + cell / 2 + 5, value, size=18, anchor="middle", fill=text_color, weight="bold"))

    labels = ["top", "middle", "bottom"]
    for idx, label in enumerate(labels):
        body.append(svg_text(left - 18, top + idx * cell + cell / 2 + 5, label, size=13, anchor="end"))
    for idx, label in enumerate(["left", "center", "right"]):
        body.append(svg_text(left + idx * cell + cell / 2, top + 3 * cell + 24, label, size=13, anchor="middle"))

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
                    total_bbox_instances += 1

    area_bins = Counter()
    for value in bbox_area_ratios:
        if value < 0.05:
            area_bins["<5%"] += 1
        elif value < 0.15:
            area_bins["5-15%"] += 1
        elif value < 0.30:
            area_bins["15-30%"] += 1
        else:
            area_bins[">30%"] += 1

    docs_count_list = [len(docs) for docs in docs_per_category.values()]
    samples_per_doc_list = list(samples_per_doc.values())

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
        "query_length_bins": build_length_bins(query_lengths, [10, 15, 20, 25, 30, 40]),
        "answer_length_bins": build_length_bins(answer_lengths, [1, 2, 4, 6, 10]),
        "samples_per_doc_top10": [
            {"category": cat, "doc_name": doc, "samples": count}
            for (cat, doc), count in samples_per_doc.most_common(10)
        ],
        "bbox_center_grid": bbox_center_grid,
    }

    return summary, tables, series


def build_length_bins(values, edges):
    labels = []
    counts = [0 for _ in range(len(edges) + 1)]
    previous = None
    for edge in edges:
        if previous is None:
            labels.append(f"<={edge}")
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
        series["bbox_center_grid"],
    )

    draw_grouped_bar_chart(
        output_dir / "qa_length_distribution.svg",
        "Query and Answer Length Distribution",
        series["query_length_bins"]["labels"],
        ["query", "answer"],
        [
            series["query_length_bins"]["counts"],
            rebin_answer_counts(series["answer_length_bins"], len(series["query_length_bins"]["labels"])),
        ],
        [PALETTE["ink"], PALETTE["gold"]],
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
