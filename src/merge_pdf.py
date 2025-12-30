"""Merge multiple PDFs into one PDF.

Usage:
  - Interactive (recommended via .bat): python merge_pdf.py
  - One-liner:
      python merge_pdf.py "a.pdf" "b.pdf" --output-name merged --overwrite
  - You can also pass directories (all PDFs under them are merged):
      python merge_pdf.py "some_folder" --output-name merged --overwrite

Output directory can be configured in tool_settings.txt (legacy: reference_paths.txt) with MERGE_OUTPUT_DIR.
"""

from __future__ import annotations

import argparse
import locale
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import fitz  # PyMuPDF

from ref_paths import (
    default_ref_path,
    read_reference_text_best_effort,
    resolve_configured_path,
    resolve_ref_value,
)


DEFAULT_OUTPUT_DIRNAME = "04_merged_pdfs"
REF_KEY_MERGE_OUTPUT_DIR = "MERGE_OUTPUT_DIR"


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


def format_size(bytes_size: int) -> str:
    if bytes_size < 0:
        return f"{bytes_size} B"
    units = [("B", 1), ("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)]
    chosen_unit = units[0]
    for unit, factor in units:
        if bytes_size >= factor:
            chosen_unit = (unit, factor)
    unit, factor = chosen_unit
    if unit == "B":
        return f"{bytes_size} {unit}"
    return f"{bytes_size / factor:.1f} {unit}"


@dataclass(frozen=True)
class PdfStat:
    path: Path
    pages: int
    size_bytes: int


def read_pdf_stat(path: Path) -> PdfStat:
    size_bytes = path.stat().st_size
    doc = fitz.open(path)
    try:
        pages = doc.page_count
    finally:
        doc.close()
    return PdfStat(path=path, pages=pages, size_bytes=size_bytes)


def suggest_output_stem(paths: Sequence[Path]) -> str:
    stems = [p.stem for p in paths if p.stem]
    if not stems:
        return "merged"

    stripped = [re.sub(r"_\d+$", "", s) for s in stems]
    if stripped and all(s == stripped[0] for s in stripped):
        return stripped[0] or "merged"

    return f"{stems[0]}_merged"


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
                found.extend([p for p in path.rglob(pattern) if p.is_file()])
            found = sorted(found, key=lambda p: str(p).lower())
            if not found:
                warnings.append(f"no PDFs found under: {path}")
                continue
            for p in found:
                add_pdf(p)
            continue

        if path.suffix.lower() != ".pdf":
            errors.append(f"not a .pdf: {path}")
            continue

        add_pdf(path)

    return pdf_paths, errors, warnings


def ensure_pdf_files(paths: Sequence[Path]) -> List[Path]:
    pdf_paths, errors, warnings = expand_input_paths(list(paths))
    for msg in warnings:
        print(f"[WARN] {msg}")
    if errors:
        raise ValueError("無効な入力パスがあります:\n  - " + "\n  - ".join(errors))
    resolved = [p.resolve() for p in pdf_paths]
    if len(resolved) < 2:
        raise ValueError("結合するには2つ以上のPDFが必要です。")
    return resolved


def choose_order(paths: List[Path], order: str) -> List[Path]:
    if order == "input":
        return list(paths)
    return sorted(paths, key=lambda p: p.name.lower())


def prompt_pdfs() -> List[Path]:
    while True:
        raw = input("結合したいPDF/フォルダを複数まとめてドラッグ＆ドロップして Enter: ").strip()
        paths = parse_dropped_paths(raw)
        if not paths:
            continue
        try:
            return ensure_pdf_files(paths)
        except Exception as exc:
            print(f"[ERROR] {exc}")


def prompt_order() -> str:
    while True:
        print("並び順を選んでください:")
        print("  1) ファイル名順（推奨：_01, _02... の結合向け）")
        print("  2) 入力順（ドラッグ＆ドロップ順）")
        raw = input("選択 (1/2, default=1): ").strip()
        if not raw or raw == "1":
            return "name"
        if raw == "2":
            return "input"
        print("[ERROR] 1 または 2 を入力してください。")


def prompt_output_name(default_stem: str) -> str:
    while True:
        raw = input(f"出力ファイル名 (default={default_stem}.pdf): ").strip()
        stem = raw if raw else default_stem
        stem = stem.strip().strip('"').strip()
        stem = stem.replace("/", "_").replace("\\", "_")
        if not stem:
            continue
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        if not stem:
            continue
        return stem


def prompt_overwrite_if_needed(output_path: Path) -> bool:
    if not output_path.exists():
        return True
    raw = input(f"既に存在します。上書きしますか？ (y/N): {output_path.name} ").strip().lower()
    return raw in ("y", "yes")


def merge_pdfs(
    input_paths: Sequence[Path],
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()
    try:
        for pdf_path in input_paths:
            doc = fitz.open(pdf_path)
            try:
                out_doc.insert_pdf(doc)
            finally:
                doc.close()

        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        out_doc.save(tmp_path)
        tmp_path.replace(output_path)
    finally:
        out_doc.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge multiple PDFs into one PDF.")
    parser.add_argument(
        "pdf_paths",
        nargs="*",
        type=Path,
        help="Input paths to merge (PDF files and/or directories).",
    )
    parser.add_argument(
        "--paths-file",
        type=Path,
        default=None,
        help="Optional text file containing input paths (one per line). Each line may be a PDF file path or a directory path.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive prompts even if input paths are provided (recommended for .bat drag-and-drop).",
    )
    parser.add_argument(
        "--order",
        choices=("name", "input"),
        default=None,
        help='Merge order: "name" (sort by filename) or "input" (as provided).',
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Output file name without extension (default: auto).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Output directory (default: {DEFAULT_OUTPUT_DIRNAME} or MERGE_OUTPUT_DIR "
            "in tool_settings.txt / reference_paths.txt)."
        ),
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
        help="Overwrite output file if it already exists (no prompt).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    ref_path = (args.ref or default_ref_path(repo_root=repo_root)).resolve()
    config = read_reference_text_best_effort(ref_path)

    configured_output_dir = None
    if config:
        try:
            output_value = resolve_ref_value(
                config,
                REF_KEY_MERGE_OUTPUT_DIR,
                default=DEFAULT_OUTPUT_DIRNAME,
                required=False,
            )
            if output_value:
                configured_output_dir = resolve_configured_path(ref_path, output_value)
        except Exception:
            configured_output_dir = None

    output_dir = (args.output_dir or configured_output_dir or (repo_root / DEFAULT_OUTPUT_DIRNAME)).resolve()

    if args.paths_file and args.pdf_paths:
        print("[ERROR] use either --paths-file or positional paths, not both.")
        return 1

    interactive = args.interactive or (len(args.pdf_paths) == 0 and args.paths_file is None)
    try:
        if args.paths_file:
            raw_inputs = read_paths_file(args.paths_file)
            pdf_paths = ensure_pdf_files(raw_inputs)
        else:
            pdf_paths = ensure_pdf_files(args.pdf_paths) if not interactive else prompt_pdfs()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if interactive:
        order = prompt_order()
    else:
        order = args.order or "name"

    ordered_paths = choose_order(pdf_paths, order)

    try:
        stats = [read_pdf_stat(p) for p in ordered_paths]
    except Exception as exc:
        print(f"[ERROR] PDF情報の取得に失敗しました: {exc}")
        return 1

    total_pages = sum(s.pages for s in stats)
    total_size = sum(s.size_bytes for s in stats)

    print("")
    print(f"[INFO] 入力ファイル数: {len(stats)}")
    print(f"[INFO] 合計サイズ: {format_size(total_size)} ({total_size} bytes)")
    print(f"[INFO] 合計ページ数: {total_pages}")
    print(f"[INFO] 並び順: {'ファイル名順' if order == 'name' else '入力順'}")
    for s in stats:
        print(f"  - {s.path.name} | {format_size(s.size_bytes)} | {s.pages} pages")

    default_stem = suggest_output_stem(ordered_paths)
    output_stem = args.output_name or (prompt_output_name(default_stem) if interactive else default_stem)
    output_path = (output_dir / f"{output_stem}.pdf").resolve()

    if output_path.exists() and not args.overwrite:
        if interactive:
            if not prompt_overwrite_if_needed(output_path):
                print("[CANCEL] 上書きをキャンセルしました。")
                return 0
        else:
            print(f"[ERROR] 出力ファイルが既に存在します: {output_path} (use --overwrite)")
            return 1

    try:
        merge_pdfs(ordered_paths, output_path=output_path)
    except Exception as exc:
        print(f"[ERROR] 結合に失敗しました: {exc}")
        return 1

    print("")
    print(f"[OK] 出力: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
