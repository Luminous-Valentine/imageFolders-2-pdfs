"""Batch convert image subfolders into PDFs using img2pdf.

This script scans the immediate subdirectories of an input directory, gathers
supported image files in natural sort order, and produces one PDF per folder
in the specified output directory.
"""
from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import img2pdf

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass
class ConversionStats:
    """Track conversion outcomes."""

    success: int = 0
    failed: int = 0
    skipped: int = 0

    def log_summary(self) -> None:
        logging.info(
            "Summary: %d succeeded, %d failed, %d skipped",
            self.success,
            self.failed,
            self.skipped,
        )


def natural_sort_key(path: Path) -> List[object]:
    """Return a key for natural sorting of paths based on filename.

    Example: 1.jpg, 2.jpg, 10.jpg => 1, 2, 10
    """

    def _split(token: str) -> Iterable[object]:
        for part in re.split(r"(\d+)", token):
            if part.isdigit():
                yield int(part)
            elif part:
                yield part.lower()

    return list(_split(path.name))


def iter_image_files(folder: Path) -> List[Path]:
    """Collect supported image files in natural sort order for a folder."""
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=natural_sort_key)


def convert_folder_to_pdf(folder: Path, output_dir: Path) -> bool:
    """Convert images inside a folder into a single PDF.

    Returns True on success, False on failure or if skipped due to no images.
    """
    images = iter_image_files(folder)
    if not images:
        logging.warning("Skipping '%s': no target images found.", folder.name)
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{folder.name}.pdf"

    try:
        logging.info("Converting %d image(s) in '%s' -> %s", len(images), folder.name, output_path)
        with output_path.open("wb") as pdf_file:
            pdf_bytes = img2pdf.convert([str(img) for img in images])
            pdf_file.write(pdf_bytes)
        logging.info("Completed '%s'", output_path)
        return True
    except Exception:
        logging.exception("Failed to convert folder '%s'", folder.name)
        return False


def process_directories(input_dir: Path, output_dir: Path) -> ConversionStats:
    """Process each immediate subfolder of input_dir and convert to PDFs."""
    stats = ConversionStats()
    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        logging.info(
            "Created input directory '%s' because it did not exist; no subfolders to process yet.",
            input_dir,
        )
        return stats

    if not input_dir.is_dir():
        raise ValueError(f"Input path exists but is not a directory: {input_dir}")

    for item in sorted(input_dir.iterdir()):
        if not item.is_dir():
            continue
        success = convert_folder_to_pdf(item, output_dir)
        if success:
            stats.success += 1
        else:
            # distinguish between skip and failure based on images
            if iter_image_files(item):
                stats.failed += 1
            else:
                stats.skipped += 1
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert subfolders of images to PDFs using img2pdf.")
    parser.add_argument("input_dir", type=Path, help="Input directory containing subfolders of images")
    parser.add_argument("output_dir", type=Path, help="Output directory for generated PDFs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Input directory: %s", args.input_dir)
    logging.info("Output directory: %s", args.output_dir)

    try:
        stats = process_directories(args.input_dir, args.output_dir)
        stats.log_summary()
    except Exception:
        logging.exception("Processing aborted due to an unrecoverable error.")


if __name__ == "__main__":
    main()
