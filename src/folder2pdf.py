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
import locale
import re
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, List, Optional, Sequence, Tuple

import img2pdf

try:
    import pikepdf
except Exception:  # pragma: no cover
    pikepdf = None  # type: ignore[assignment]

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
    pikepdf_interpolate: bool = False
    pikepdf_force_png: bool = False


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


def px_to_pt(px: int, dpi: int) -> float:
    return float(img2pdf.px_to_pt(int(px), int(dpi)))


def _read_text_with_fallback(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        return path.read_text(encoding=encoding)


def read_paths_file(path: Path) -> List[Path]:
    if not path.exists():
        raise FileNotFoundError(f"--folders-file not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"--folders-file is a directory: {path}")

    content = _read_text_with_fallback(path)
    paths: List[Path] = []
    for raw_line in re.split(r"\r?\n", content):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        unquoted = line.strip().strip('"')
        if unquoted:
            paths.append(Path(unquoted))
    return paths


def expand_target_folders(inputs: Sequence[Path]) -> Tuple[List[Path], List[str], List[str]]:
    folders: List[Path] = []
    errors: List[str] = []
    warnings: List[str] = []

    seen: set[str] = set()

    def add_folder(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = str(path)
        key = resolved.lower()
        if key in seen:
            return
        seen.add(key)
        folders.append(path)

    for raw in inputs:
        path = Path(str(raw)).expanduser()
        if not path.exists():
            errors.append(f"not found: {path}")
            continue
        if not path.is_dir():
            warnings.append(f"skipped (not a directory): {path}")
            continue

        direct_images = [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        if direct_images:
            add_folder(path)
            continue

        subfolders = [p for p in path.iterdir() if p.is_dir()]
        if not subfolders:
            warnings.append(f"no images found under: {path}")
            continue

        added_any = False
        for sub in sorted(subfolders, key=lambda p: natural_key(p.name)):
            sub_images = [p for p in sub.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            if sub_images:
                add_folder(sub)
                added_any = True
        if not added_any:
            warnings.append(f"no image folders found under: {path}")

    return folders, errors, warnings


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
        "folders",
        nargs="*",
        type=Path,
        help=(
            "Optional target image folders. If provided, only these folders are converted "
            "(INPUT_DIR is ignored). You can also pass a parent folder; its direct subfolders "
            "that contain images are treated as targets."
        ),
    )
    parser.add_argument(
        "--ref",
        type=Path,
        default=None,
        help="Settings file (.txt). Default: ./tool_settings.txt (fallback: ./reference_paths.txt).",
    )
    parser.add_argument(
        "--folders-file",
        type=Path,
        default=None,
        help="Optional text file containing target folder paths (one per line).",
    )
    parser.add_argument(
        "--backend",
        choices=("img2pdf", "pikepdf"),
        default="img2pdf",
        help=(
            'PDF generation backend. "img2pdf" (default) is recommended. '
            '"pikepdf" is a JPEG-focused backend that embeds JPEG bytes as-is (requires pikepdf).'
        ),
    )
    parser.add_argument(
        "--pikepdf-interpolate",
        action="store_true",
        help="(pikepdf only) Set /Interpolate true on images to hint smooth scaling in viewers.",
    )
    parser.add_argument(
        "--pikepdf-png",
        action="store_true",
        help="(pikepdf only) Decode images and embed lossless (PNG-like) instead of embedding JPEG as-is.",
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


def write_atomic_from_file(path: Path, tmp_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.resolve() == path.resolve():
        return
    target_tmp = path.with_suffix(path.suffix + ".tmp")
    if target_tmp.exists():
        target_tmp.unlink()
    tmp_path.replace(target_tmp)
    target_tmp.replace(path)


def convert_folder_to_pdf_img2pdf(folder: Path, *, output_pdf: Path, opts: ConvertOptions) -> None:
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


def _jpeg_colorspace(mode: str) -> str:
    if mode == "L":
        return "/DeviceGray"
    if mode == "RGB":
        return "/DeviceRGB"
    if mode == "CMYK":
        return "/DeviceCMYK"
    return "/DeviceRGB"


def _flatten_image_for_png(img: Image.Image) -> Tuple[Image.Image, str, int]:
    img = ImageOps.exif_transpose(img)
    if img.mode == "RGB":
        return img, "/DeviceRGB", 3
    if img.mode == "L":
        return img, "/DeviceGray", 1
    # Palette/CMYKなどはRGBに寄せる
    return img.convert("RGB"), "/DeviceRGB", 3


def convert_folder_to_pdf_pikepdf(folder: Path, *, output_pdf: Path, opts: ConvertOptions) -> None:
    if pikepdf is None:  # pragma: no cover
        raise RuntimeError('pikepdf is not available. Install it with: pip install pikepdf')

    images = gather_images(folder)
    if not images:
        raise ValueError("no images found")

    # When not converting to PNG, we expect JPEG-only folders and embed JPEG bytes as-is.
    if not opts.pikepdf_force_png:
        for img_path in images:
            if img_path.suffix.lower() not in (".jpg", ".jpeg"):
                raise ValueError(f"pikepdf backend supports JPEG only: {img_path.name}")

    with TemporaryDirectory(prefix="folder2pdf_pikepdf_") as td:
        tmp_dir = Path(td)
        tmp_pdf = tmp_dir / "out.pdf"

        pdf = pikepdf.Pdf.new()

        for index, img_path in enumerate(images, start=1):
            with Image.open(img_path) as img:
                width_px, height_px = img.size
                if width_px <= 0 or height_px <= 0:
                    raise ValueError(f"invalid image size: {img_path.name}")

                if opts.pikepdf_force_png:
                    # 可逆(PNG相当)で埋め込む
                    prepared, colorspace, colors = _flatten_image_for_png(img)
                    raw = prepared.tobytes()
                    compressed = zlib.compress(raw)
                    xobj = pikepdf.Stream(pdf, compressed)
                    xobj["/Type"] = pikepdf.Name("/XObject")
                    xobj["/Subtype"] = pikepdf.Name("/Image")
                    xobj["/Width"] = int(width_px)
                    xobj["/Height"] = int(height_px)
                    xobj["/ColorSpace"] = pikepdf.Name(colorspace)
                    xobj["/BitsPerComponent"] = 8
                    xobj["/Filter"] = pikepdf.Name("/FlateDecode")
                    xobj["/DecodeParms"] = pikepdf.Dictionary(
                        {
                            "/Predictor": 15,
                            "/Colors": int(colors),
                            "/BitsPerComponent": 8,
                            "/Columns": int(width_px),
                        }
                    )
                else:
                    color_space = _jpeg_colorspace(getattr(img, "mode", "") or "RGB")
                    img_bytes = img_path.read_bytes()
                    xobj = pikepdf.Stream(pdf, img_bytes)
                    xobj["/Type"] = pikepdf.Name("/XObject")
                    xobj["/Subtype"] = pikepdf.Name("/Image")
                    xobj["/Width"] = int(width_px)
                    xobj["/Height"] = int(height_px)
                    xobj["/ColorSpace"] = pikepdf.Name(color_space)
                    xobj["/BitsPerComponent"] = 8
                    xobj["/Filter"] = pikepdf.Name("/DCTDecode")

                if opts.pikepdf_interpolate:
                    xobj["/Interpolate"] = True

            w_pt = px_to_pt(width_px, opts.dpi)
            h_pt = px_to_pt(height_px, opts.dpi)

            xname = f"/Im{index}"
            resources = pikepdf.Dictionary({"/XObject": pikepdf.Dictionary({xname: xobj})})
            contents = pikepdf.Stream(
                pdf,
                f"q\n{w_pt:.6f} 0 0 {h_pt:.6f} 0 0 cm\n{xname} Do\nQ\n".encode("ascii"),
            )

            page_dict = pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Page"),
                    "/MediaBox": pikepdf.Array([0, 0, w_pt, h_pt]),
                    "/Resources": resources,
                    "/Contents": contents,
                }
            )
            page = pikepdf.Page(page_dict)
            pdf.pages.append(page)

        pdf.save(tmp_pdf)
        write_atomic_from_file(output_pdf, tmp_pdf)


def convert_folder_to_pdf(folder: Path, *, output_pdf: Path, opts: ConvertOptions, backend: str) -> None:
    if backend == "img2pdf":
        return convert_folder_to_pdf_img2pdf(folder, output_pdf=output_pdf, opts=opts)
    if backend == "pikepdf":
        return convert_folder_to_pdf_pikepdf(folder, output_pdf=output_pdf, opts=opts)
    raise ValueError(f"unknown backend: {backend}")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    ref_path = (args.ref or default_ref_path(repo_root=repo_root)).resolve()

    if args.folders_file and args.folders:
        print("[ARGS] ERROR: use either --folders-file or positional folders, not both.")
        return 1

    explicit_folders: Optional[List[Path]] = None
    if args.folders_file or args.folders:
        try:
            raw_inputs = read_paths_file(args.folders_file) if args.folders_file else list(args.folders)
            explicit_folders, errors, warnings = expand_target_folders(raw_inputs)
        except Exception as exc:
            print(f"[ARGS] ERROR: {exc}")
            return 1

        for msg in warnings:
            print(f"[ARGS] WARN: {msg}")

        if errors:
            print("[ARGS] ERROR: invalid folder paths")
            for msg in errors:
                print(f"  - {msg}")
            return 1

        if not explicit_folders:
            print("[ARGS] ERROR: no image folders found in inputs.")
            return 1

        print("[ARGS] Using explicit folders; INPUT_DIR is ignored.")

    if args.input_dir is None or args.output_dir is None:
        input_dir, output_dir = resolve_dirs_from_ref(ref_path)
        if args.input_dir is not None:
            input_dir = Path(strip_quotes(str(args.input_dir))).resolve()
        if args.output_dir is not None:
            output_dir = Path(strip_quotes(str(args.output_dir))).resolve()
    else:
        input_dir = Path(strip_quotes(str(args.input_dir))).resolve()
        output_dir = Path(strip_quotes(str(args.output_dir))).resolve()

    if explicit_folders is None:
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
        pikepdf_interpolate=bool(args.pikepdf_interpolate),
        pikepdf_force_png=bool(args.pikepdf_png),
    )

    folders = explicit_folders if explicit_folders is not None else gather_folders(input_dir)
    summary = RunSummary(total_folders=len(folders))

    print(f"[INFO] input_dir={input_dir}")
    print(f"[INFO] output_dir={output_dir}")
    print(f"[INFO] folders={len(folders)}")
    extra = ""
    if args.backend == "pikepdf":
        extra = f" interpolate={opts.pikepdf_interpolate} png_embed={opts.pikepdf_force_png}"
    print(
        f"[INFO] backend={args.backend} dpi={opts.dpi} optimize_mode={opts.optimize_mode} jpeg_quality={opts.jpeg_quality}{extra}"
    )

    used_out_names: dict[str, int] = {}

    for folder in folders:
        base_stem = sanitize_filename(folder.name)
        stem_key = base_stem.lower()
        if stem_key in used_out_names:
            used_out_names[stem_key] += 1
            out_name = f"{base_stem}__{used_out_names[stem_key]}.pdf"
        else:
            used_out_names[stem_key] = 1
            out_name = f"{base_stem}.pdf"
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

            convert_folder_to_pdf(folder, output_pdf=out_path, opts=opts, backend=str(args.backend))
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
