"""Convert image subfolders into PDFs (one PDF per folder).

This is a "plain img2pdf" approach:
  - Each subfolder under INPUT_DIR becomes one PDF in OUTPUT_DIR.
  - Images are ordered by filename (natural sort).
  - By default, JPEG files are embedded without re-encoding (no quality loss).
  - For other formats, an "auto" mode can re-encode very large images to keep PDF size reasonable.

Run via PowerShell launcher:
  - 01_run_folder2pdf.ps1
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, List, Optional, Sequence, Tuple

import img2pdf

try:
    from PIL import Image, ImageOps
except Exception as exc:  # pragma: no cover
    raise RuntimeError("Pillow is required: pip install pillow") from exc

from ref_paths import (
    default_ref_path,
    read_reference_text_best_effort,
    resolve_configured_path,
    resolve_ref_value,
)


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")

REF_KEY_INPUT_DIR = "INPUT_DIR"
REF_KEY_OUTPUT_DIR = "OUTPUT_DIR"

INVALID_WINDOWS_FILENAME_CHARS = '<>:"/\\|?*'


def natural_key(text: str) -> List[object]:
    parts: List[object] = []
    for chunk in re.split(r"(\d+)", text):
        if not chunk:
            continue
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(chunk.casefold())
    return parts


def sanitize_filename(name: str) -> str:
    cleaned = "".join("_" if ch in INVALID_WINDOWS_FILENAME_CHARS else ch for ch in name)
    cleaned = cleaned.strip().strip(".").strip()
    return cleaned or "output"


def strip_quotes(value: str) -> str:
    trimmed = value.strip()
    if len(trimmed) >= 2 and trimmed[0] == '"' and trimmed[-1] == '"':
        return trimmed[1:-1].strip()
    return trimmed


@dataclass(frozen=True)
class ConvertOptions:
    dpi: int
    optimize_mode: str  # lossless|auto|size
    jpeg_quality: int
    max_long_edge: int
    auto_reencode_threshold_bytes: int


def page_layout_fun(dpi: int):
    def _layout(imgwidthpx: int, imgheightpx: int, ndpi: Tuple[float, float]):
        w = img2pdf.px_to_pt(imgwidthpx, dpi)
        h = img2pdf.px_to_pt(imgheightpx, dpi)
        return w, h, w, h

    return _layout


def should_keep_lossless(path: Path, opts: ConvertOptions) -> bool:
    ext = path.suffix.lower()
    if opts.optimize_mode == "lossless":
        return True
    if opts.optimize_mode == "size":
        return ext in (".jpg", ".jpeg")
    if ext in (".jpg", ".jpeg"):
        return True
    if ext == ".png" and path.stat().st_size <= opts.auto_reencode_threshold_bytes:
        return True
    return False


def flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or ("transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.convert("RGBA").split()[-1]
        background.paste(img.convert("RGBA"), mask=alpha)
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def maybe_resize(img: Image.Image, max_long_edge: int) -> Image.Image:
    if max_long_edge <= 0:
        return img
    w, h = img.size
    if max(w, h) <= max_long_edge:
        return img
    resized = img.copy()
    resized.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
    return resized


def prepare_image(
    path: Path,
    *,
    tmp_dir: Path,
    index: int,
    opts: ConvertOptions,
) -> Path:
    if should_keep_lossless(path, opts):
        return path

    with Image.open(path) as opened:
        img = ImageOps.exif_transpose(opened)
        img = flatten_to_rgb(img)

        max_long_edge = opts.max_long_edge
        if opts.optimize_mode == "auto":
            if max_long_edge <= 0:
                max_long_edge = 5000
        elif opts.optimize_mode == "size":
            if max_long_edge <= 0:
                max_long_edge = 3508

        img = maybe_resize(img, max_long_edge)

        out_name = f"{index:04d}_{sanitize_filename(path.stem)}.jpg"
        out_path = tmp_dir / out_name
        img.save(
            out_path,
            format="JPEG",
            quality=int(opts.jpeg_quality),
            optimize=True,
            progressive=True,
        )
        return out_path


def gather_folders(input_root: Path) -> List[Path]:
    return sorted([p for p in input_root.iterdir() if p.is_dir()], key=lambda p: natural_key(p.name))


def gather_images(folder: Path) -> List[Path]:
    images = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    return sorted(images, key=lambda p: natural_key(p.name))


def resolve_dirs_from_ref(ref_path: Path) -> Tuple[Path, Path]:
    config = read_reference_text_best_effort(ref_path)
    input_value = (
        resolve_ref_value(config, REF_KEY_INPUT_DIR, default="01_images_input", required=False)
        if config
        else "01_images_input"
    )
    output_value = (
        resolve_ref_value(config, REF_KEY_OUTPUT_DIR, default="01_pdf_output", required=False)
        if config
        else "01_pdf_output"
    )
    input_dir = resolve_configured_path(ref_path, input_value)
    output_dir = resolve_configured_path(ref_path, output_value)
    return input_dir, output_dir


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert image subfolders into PDFs (one PDF per folder).")
    parser.add_argument("input_dir", nargs="?", type=Path, help="Root folder containing image subfolders.")
    parser.add_argument("output_dir", nargs="?", type=Path, help="Output folder for generated PDFs.")
    parser.add_argument(
        "--ref",
        type=Path,
        default=None,
        help="Settings file (.txt). Default: ./tool_settings.txt (fallback: ./reference_paths.txt).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PDFs.")
    parser.add_argument("--dpi", type=int, default=300, help="DPI used to determine PDF page size (default: 300).")
    parser.add_argument(
        "--optimize-mode",
        choices=("lossless", "auto", "size"),
        default="auto",
        help=(
            '"lossless": never re-encode; "auto": keep JPEG/most PNG lossless, '
            're-encode very large images; "size": re-encode non-JPEG aggressively.'
        ),
    )
    parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG quality used when re-encoding (default: 90).")
    parser.add_argument(
        "--max-long-edge",
        type=int,
        default=0,
        help="Max pixels for the longest image edge when re-encoding (0=auto default per optimize-mode).",
    )
    parser.add_argument(
        "--auto-reencode-threshold-mb",
        type=float,
        default=6.0,
        help="In auto mode, re-encode PNG if file size exceeds this threshold (default: 6.0 MB).",
    )
    return parser.parse_args(argv)


@dataclass
class RunSummary:
    total_folders: int = 0
    ok: int = 0
    skipped: int = 0
    fail: int = 0
    failed: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed is None:
            self.failed = []


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    tmp.write_bytes(data)
    tmp.replace(path)


def convert_folder_to_pdf(folder: Path, *, output_pdf: Path, opts: ConvertOptions) -> None:
    images = gather_images(folder)
    if not images:
        raise ValueError("no images found")

    with TemporaryDirectory(prefix="folder2pdf_") as td:
        tmp_dir = Path(td)
        prepared: List[Path] = []
        for i, img_path in enumerate(images, start=1):
            prepared.append(prepare_image(img_path, tmp_dir=tmp_dir, index=i, opts=opts))

        pdf_bytes = img2pdf.convert(prepared, layout_fun=page_layout_fun(opts.dpi))
        write_atomic(output_pdf, pdf_bytes)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    ref_path = (args.ref or default_ref_path(repo_root=repo_root)).resolve()

    if args.input_dir is None or args.output_dir is None:
        input_dir, output_dir = resolve_dirs_from_ref(ref_path)
        if args.input_dir is not None:
            input_dir = Path(strip_quotes(str(args.input_dir))).resolve()
        if args.output_dir is not None:
            output_dir = Path(strip_quotes(str(args.output_dir))).resolve()
    else:
        input_dir = Path(strip_quotes(str(args.input_dir))).resolve()
        output_dir = Path(strip_quotes(str(args.output_dir))).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] input_dir not found or not a directory: {input_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    opts = ConvertOptions(
        dpi=int(args.dpi),
        optimize_mode=str(args.optimize_mode),
        jpeg_quality=max(1, min(100, int(args.jpeg_quality))),
        max_long_edge=int(args.max_long_edge),
        auto_reencode_threshold_bytes=int(float(args.auto_reencode_threshold_mb) * 1024 * 1024),
    )

    folders = gather_folders(input_dir)
    summary = RunSummary(total_folders=len(folders))

    print(f"[INFO] input_dir={input_dir}")
    print(f"[INFO] output_dir={output_dir}")
    print(f"[INFO] folders={len(folders)}")
    print(f"[INFO] dpi={opts.dpi} optimize_mode={opts.optimize_mode} jpeg_quality={opts.jpeg_quality}")

    for folder in folders:
        out_name = f"{sanitize_filename(folder.name)}.pdf"
        out_path = output_dir / out_name

        try:
            images = gather_images(folder)
            if not images:
                print(f"[SKIP] {folder.name} (no images)")
                summary.skipped += 1
                continue

            if out_path.exists() and not args.overwrite:
                print(f"[SKIP] {folder.name} -> {out_path.name} (exists)")
                summary.skipped += 1
                continue

            convert_folder_to_pdf(folder, output_pdf=out_path, opts=opts)
            print(f"[OK] {folder.name} -> {out_path.name} ({len(images)} images)")
            summary.ok += 1
        except Exception as exc:
            print(f"[FAIL] {folder.name} : {exc}")
            summary.fail += 1
            summary.failed.append(f"{folder.name} : {exc}")

    print(f"[SUMMARY] folders={summary.total_folders} ok={summary.ok} skipped={summary.skipped} fail={summary.fail}")
    if summary.fail:
        print("[FAILED LIST]")
        for item in summary.failed:
            print(f"  - {item}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
