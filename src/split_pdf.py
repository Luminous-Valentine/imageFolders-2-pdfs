"""Split PDFs into N nearly-equal parts (contiguous page ranges).

This tool supports drag-and-drop style usage via a .bat launcher:
- Drop one or more PDFs
- Or drop one or more folders (PDFs directly under them are used)

Outputs:
  <output_root>/<pdf_stem>/<pdf_stem>_01.pdf, ...

After splitting, this tool *optionally* creates:
  <OCR_DIR>/<pdf_stem>/
as a convenience for OCR workflows (best-effort; does not fail the run).
"""

from __future__ import annotations

import argparse
import locale
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF

from ref_paths import (
    default_ref_path,
    read_reference_text_best_effort,
    resolve_configured_path,
    resolve_ref_value,
)

DEFAULT_OUTPUT_DIRNAME = "03_split_pdfs"
REF_KEY_SPLIT_OUTPUT_DIR = "SPLIT_OUTPUT_DIR"
REF_KEY_OCR_DIR = "OCR_DIR"

INVALID_WINDOWS_FILENAME_CHARS = '<>:"/\\|?*'


def format_size(bytes_size: int) -> str:
    if bytes_size < 0:
        return f"{bytes_size} B"
    units = [("B", 1), ("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)]
    unit, factor = units[0]
    for u, f in units:
        if bytes_size >= f:
            unit, factor = u, f
    if unit == "B":
        return f"{bytes_size} {unit}"
    return f"{bytes_size / factor:.1f} {unit}"


def _read_text_with_fallback(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        return path.read_text(encoding=encoding)


def read_paths_file(path: Path) -> List[Path]:
    if not path.exists():
        raise FileNotFoundError(f"--paths-file not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"--paths-file is a directory: {path}")

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


def parse_dropped_paths(raw: str) -> List[Path]:
    text = raw.strip()
    if not text:
        return []

    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        return [Path(p.strip()) for p in quoted if p.strip()]

    return [Path(p.strip()) for p in text.split() if p.strip()]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split PDFs into N nearly-equal parts (contiguous page ranges).",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Input paths (PDF files and/or directories that contain PDFs directly under them).",
    )
    parser.add_argument(
        "--paths-file",
        type=Path,
        default=None,
        help="Optional text file containing input paths (one per line). Each line may be a PDF file path or a directory path.",
    )
    parser.add_argument(
        "--parts",
        type=int,
        default=None,
        help="Number of parts to split into (>= 2). If omitted, will prompt.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=f"Root output directory (default: ./{DEFAULT_OUTPUT_DIRNAME}).",
    )
    parser.add_argument(
        "--ref",
        type=Path,
        default=None,
        help="Settings file (.txt). Default: ./tool_settings.txt (fallback: ./reference_paths.txt).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing split PDFs if they already exist.",
    )
    parser.add_argument(
        "--no-ocr-folder",
        action="store_true",
        help="Do not create OCR_DIR/<pdf_stem>/ after splitting.",
    )
    return parser.parse_args(argv)


def prompt_inputs() -> List[Path]:
    while True:
        raw = input("分割したいPDF/フォルダをドラッグ＆ドロップして Enter: ").strip()
        if not raw:
            continue
        items = parse_dropped_paths(raw)
        if items:
            return items


def prompt_parts(*, max_parts: int) -> int:
    while True:
        raw = input(f"何分割しますか？ (2〜{max_parts}): ").strip()
        if not raw:
            continue
        try:
            parts = int(raw)
        except ValueError:
            print("[ERROR] 数字で入力してください。")
            continue
        if parts < 2:
            print("[ERROR] 2以上を指定してください。")
            continue
        if parts > max_parts:
            print(f"[ERROR] ページ数({max_parts})を超える分割数は指定できません。")
            continue
        return parts


def sanitize_dirname(name: str) -> str:
    cleaned = "".join("_" if ch in INVALID_WINDOWS_FILENAME_CHARS else ch for ch in name)
    cleaned = cleaned.strip().strip(".").strip()
    return cleaned or "output"


@dataclass(frozen=True)
class PdfInfo:
    pages: int
    size_bytes: int


def read_pdf_info(pdf_path: Path) -> PdfInfo:
    size_bytes = pdf_path.stat().st_size
    doc = fitz.open(pdf_path)
    try:
        pages = doc.page_count
    finally:
        doc.close()
    return PdfInfo(pages=pages, size_bytes=size_bytes)


def iter_equal_ranges(total_pages: int, parts: int) -> Iterable[Tuple[int, int]]:
    if total_pages <= 0:
        raise ValueError("PDF has no pages.")
    if parts < 1:
        raise ValueError("parts must be >= 1")
    if parts > total_pages:
        raise ValueError("parts must be <= total_pages")

    base = total_pages // parts
    remainder = total_pages % parts

    start = 0
    for i in range(parts):
        length = base + (1 if i < remainder else 0)
        end = start + length
        yield start, end
        start = end


def split_pdf(pdf_path: Path, *, parts: int, output_root: Path, overwrite: bool) -> Path:
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists() or pdf_path.is_dir():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Not a PDF: {pdf_path}")

    info = read_pdf_info(pdf_path)
    if parts < 2:
        raise ValueError("parts must be >= 2")
    if parts > info.pages:
        raise ValueError(f"parts must be <= pages ({info.pages})")

    out_dir = (output_root / sanitize_dirname(pdf_path.stem)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    src = fitz.open(pdf_path)
    try:
        ranges = list(iter_equal_ranges(src.page_count, parts))
        for i, (start, end) in enumerate(ranges, start=1):
            out_name = f"{sanitize_dirname(pdf_path.stem)}_{i:02d}.pdf"
            out_path = out_dir / out_name
            if out_path.exists() and not overwrite:
                raise FileExistsError(f"Output already exists: {out_path} (use --overwrite)")

            out_doc = fitz.open()
            try:
                out_doc.insert_pdf(src, from_page=start, to_page=end - 1)
                out_doc.save(out_path)
            finally:
                out_doc.close()
    finally:
        src.close()

    return out_dir


def expand_input_paths(inputs: Sequence[Path]) -> Tuple[List[Path], List[str], List[str]]:
    pdf_paths: List[Path] = []
    errors: List[str] = []
    warnings: List[str] = []

    seen: set[str] = set()

    def add_pdf(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = str(path)
        key = resolved.lower()
        if key in seen:
            return
        seen.add(key)
        pdf_paths.append(path)

    for raw in inputs:
        path = Path(str(raw)).expanduser()
        if not path.exists():
            errors.append(f"not found: {path}")
            continue

        if path.is_dir():
            found: List[Path] = []
            for pattern in ("*.pdf", "*.PDF"):
                found.extend([p for p in path.glob(pattern) if p.is_file()])
            found = sorted(found, key=lambda p: str(p).lower())
            if not found:
                warnings.append(f"no PDFs directly under: {path}")
                continue
            for p in found:
                add_pdf(p)
            continue

        if path.suffix.lower() != ".pdf":
            warnings.append(f"skipped (not a PDF): {path}")
            continue

        add_pdf(path)

    return pdf_paths, errors, warnings


def resolve_output_root_from_ref(ref_path: Path, repo_root: Path) -> Path:
    config = read_reference_text_best_effort(ref_path)
    configured_output_root: Optional[Path] = None
    if config:
        try:
            output_value = resolve_ref_value(
                config,
                REF_KEY_SPLIT_OUTPUT_DIR,
                default=DEFAULT_OUTPUT_DIRNAME,
                required=False,
            )
            if output_value:
                configured_output_root = resolve_configured_path(ref_path, output_value)
        except Exception:
            configured_output_root = None
    return (configured_output_root or (repo_root / DEFAULT_OUTPUT_DIRNAME)).resolve()


def resolve_ocr_dir_from_ref(ref_path: Path) -> Tuple[Optional[Path], str]:
    config = read_reference_text_best_effort(ref_path)
    if not config:
        return None, f"settings file not found or invalid: {ref_path}"

    try:
        ocr_value = resolve_ref_value(config, REF_KEY_OCR_DIR, default="", required=False)
    except Exception as exc:
        return None, f"OCR_DIR could not be resolved: {exc}"

    if not ocr_value.strip():
        return None, "OCR_DIR is empty."

    ocr_dir = resolve_configured_path(ref_path, ocr_value)
    if not ocr_dir.exists() or not ocr_dir.is_dir():
        return None, f"OCR_DIR does not exist or is not a directory: {ocr_dir}"

    return ocr_dir, ""


def ensure_ocr_folder(ocr_dir: Path, pdf_stem: str) -> Tuple[bool, str]:
    folder_name = sanitize_dirname(pdf_stem)
    target_dir = ocr_dir / folder_name
    try:
        if target_dir.exists():
            if target_dir.is_dir():
                return True, f"exists: {target_dir}"
            return False, f"exists but is not a directory: {target_dir}"
        target_dir.mkdir(parents=False, exist_ok=False)
        return True, f"created: {target_dir}"
    except Exception as exc:
        return False, f"failed: {target_dir} ({exc})"


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    ref_path = (args.ref or default_ref_path(repo_root=repo_root)).resolve()

    if args.paths_file and args.inputs:
        print("[ARGS] ERROR: use either --paths-file or positional inputs, not both.")
        return 1

    if args.paths_file:
        try:
            raw_inputs = read_paths_file(args.paths_file)
        except Exception as exc:
            print(f"[ARGS] ERROR: {exc}")
            return 1
    elif args.inputs:
        raw_inputs = list(args.inputs)
    else:
        raw_inputs = prompt_inputs()

    pdf_paths, errors, warnings = expand_input_paths(raw_inputs)
    for msg in warnings:
        print(f"[WARN] {msg}")
    if errors:
        print("[ERROR] invalid input paths")
        for msg in errors:
            print(f"  - {msg}")
        return 1
    if not pdf_paths:
        print("[ERROR] no PDFs found.")
        return 1

    output_root = (args.output_root or resolve_output_root_from_ref(ref_path, repo_root)).resolve()

    readable: List[Tuple[Path, PdfInfo]] = []
    for p in pdf_paths:
        try:
            readable.append((p, read_pdf_info(p)))
        except Exception as exc:
            print(f"[FAIL] {p} : {exc}")

    if not readable:
        print("[ERROR] no readable PDFs.")
        return 1

    print("")
    print(f"[REF] ref_path={ref_path}")
    print(f"[INFO] 出力先: {output_root}")
    print(f"[INFO] 入力PDF: {len(readable)} 件")
    for pdf_path, info in readable:
        print(f"  - {pdf_path.name} | {format_size(info.size_bytes)} | {info.pages} pages")

    min_pages = min(info.pages for _, info in readable)
    if min_pages < 2:
        print("[ERROR] 2ページ未満のPDFが含まれています。")
        return 1

    parts = args.parts
    if parts is None:
        print("")
        parts = prompt_parts(max_parts=min_pages)

    ok_paths: List[Path] = []
    failed: List[str] = []
    for pdf_path, info in readable:
        if info.pages < parts:
            failed.append(f"{pdf_path.name} : pages={info.pages} is less than parts={parts}")
            continue
        try:
            out_dir = split_pdf(
                pdf_path,
                parts=parts,
                output_root=output_root,
                overwrite=bool(args.overwrite),
            )
            print(f"[OK] {pdf_path.name} -> {out_dir}")
            ok_paths.append(pdf_path)
        except Exception as exc:
            print(f"[FAIL] {pdf_path.name} : {exc}")
            failed.append(f"{pdf_path.name} : {exc}")

    if not args.no_ocr_folder:
        ocr_dir, reason = resolve_ocr_dir_from_ref(ref_path)
        print("")
        if ocr_dir is None:
            print(f"[OCR] SKIP: {reason}")
        else:
            print(f"[OCR] OCR_DIR={ocr_dir}")
            for pdf_path in ok_paths:
                ok2, msg = ensure_ocr_folder(ocr_dir, pdf_path.stem)
                print(("[OCR] OK " if ok2 else "[OCR] FAIL ") + f"{pdf_path.stem} : {msg}")

    print("")
    print(f"[SUMMARY] total={len(readable)} ok={len(ok_paths)} fail={len(failed)} parts={parts}")
    if failed:
        print("[FAILED LIST]")
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
