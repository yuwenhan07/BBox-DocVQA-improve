# Repository Guidelines

## Project Structure & Module Organization
This repository stores the BBox-DocVQA benchmark and lightweight preprocessing scripts.

- `benchmark/`: page-level PNG assets grouped by category and document ID, plus `benchmark/bbox-docvqa.jsonl`.
- `benchmark_raw/`: source PDF files grouped by the same category layout.
- `code/crop/`: Python utilities for bbox-based crop export and generated sample outputs in `bbox_crops_out/`.
- `code/improve/`: reserved for future model or preprocessing improvements; keep new code organized by task.

Use category and document paths consistently, for example: `benchmark/cs/2311.07631/2311.07631_4.png`.

## Build, Test, and Development Commands
This project currently uses standalone Python scripts rather than a package build system.

- `python code/crop/export_bbox_crops.py`: export cropped PNGs for the first 10 records using default paths.
- `python code/crop/export_bbox_crops.py --limit 50 --output-dir code/crop/custom_out`: run a larger export to a custom folder.
- `python -m py_compile code/crop/export_bbox_crops.py`: quick syntax validation before commit.

Run commands from the repository root unless a script explicitly documents otherwise.

## Coding Style & Naming Conventions
- Target Python 3 and keep scripts dependency-light; prefer the standard library when practical.
- Use 4-space indentation and `snake_case` for functions, variables, and file names.
- Keep scripts focused and single-purpose. Put reusable helpers near the top-level workflow they support.
- Name generated crop files predictably, for example: `sample_001_cs_2311.07631_p4_r1_image.png`.

Avoid committing one-off notebooks or ad hoc shell fragments when the same logic can live in a script.

## Testing Guidelines
There is no formal test suite yet. For script changes:

- Run `python -m py_compile <script>` on edited files.
- Execute a small end-to-end sample, e.g. `python code/crop/export_bbox_crops.py --limit 3`.
- Check output artifacts and `manifest.json` for path, bbox, and image-size correctness.

If you add tests, place them under a new `tests/` directory and prefer `test_<feature>.py` naming.

## Commit & Pull Request Guidelines
The current history is minimal (`Initial commit`), so use short, imperative commit messages such as:

- `Add bbox crop export script`
- `Fix PNG filter decoding for RGB pages`

For pull requests, include:

- a brief summary of the change,
- affected paths or datasets,
- exact commands run for validation,
- sample output notes or screenshots when output files change.

Do not rewrite benchmark data unless the PR clearly explains the source and impact.
