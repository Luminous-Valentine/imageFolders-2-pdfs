"""Extract embedded text from searchable PDFs into machine-friendly .txt files.

Reads input/output directories from a reference text file (KEY=VALUE; # comments).
Writes one UTF-8 .txt per input PDF, inserting a page marker for every page.
"""

from __future__ import annotations

import argparse
import locale
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import fitz  # PyMuPDF


PAGE_MARKER_TEMPLATE = "[[PAGE={page}/{total}]]"

REF_KEY_INPUT_DIR = "EXTRACT_INPUT_DIR"
REF_KEY_OUTPUT_DIR = "EXTRACT_OUTPUT_DIR"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract embedded text from PDFs and write one UTF-8 .txt per PDF.",
    )
    parser.add_argument(
        "--ref",
        type=Path,
        required=True,
        help="Reference text file (.txt) that defines input/output directories (KEY=VALUE).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .txt outputs (default: do not overwrite).",
    )
    parser.add_argument(
        "--mode",
        choices=("blocks", "text"),
        default="blocks",
        help='Extraction mode: "blocks" (default) or "text".',
    )
    parser.add_argument(
        "--y-tol",
        type=float,
        default=3.0,
        help="Y tolerance for considering blocks on the same line (blocks mode). Default: 3.0",
    )
    parser.add_argument(
        "--drop-header-footer",
        action="store_true",
        help="Drop header/footer regions (blocks mode).",
    )
    parser.add_argument(
        "--header-ratio",
        type=float,
        default=0.07,
        help="Top ratio to drop when --drop-header-footer is set. Default: 0.07",
    )
    parser.add_argument(
        "--footer-ratio",
        type=float,
        default=0.07,
        help="Bottom ratio to drop when --drop-header-footer is set. Default: 0.07",
    )
    parser.add_argument(
        "--paths-file",
        type=Path,
        help=(
            "Optional text file containing input paths (one per line). "
            "Each line may be a PDF file path or a directory path."
        ),
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        help=(
            "Optional input paths. Each path may be a PDF file or a directory. "
            "If provided, only these inputs are processed (EXTRACT_INPUT_DIR is ignored)."
        ),
    )
    return parser.parse_args()


def read_reference_text(path: Path) -> Dict[str, str]:
    if path.suffix.lower() != ".txt":
        raise ValueError(f"--ref must be a .txt file: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Reference text file not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"Reference text file path is a directory: {path}")

    config: Dict[str, str] = {}
    content = path.read_text(encoding="utf-8-sig")
    for raw_line in re.split(r"\r?\n", content):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip().upper()] = value.strip()
    return config


def resolve_configured_dir(ref_path: Path, value: str) -> Path:
    trimmed = value.strip().strip('"')
    configured = Path(trimmed)
    if configured.is_absolute():
        return configured
    return (ref_path.parent / configured).resolve()

def resolve_ref_value(
    config: Dict[str, str],
    key: str,
    *,
    default: Optional[str] = None,
    required: bool = False,
    _stack: Optional[List[str]] = None,
) -> str:
    stack = [] if _stack is None else _stack
    key_upper = key.strip().upper()

    raw = config.get(key_upper, "")
    raw = raw.strip()
    if not raw and default is not None:
        raw = default

    if not raw:
        if required:
            raise ValueError(f"Missing required key in reference text: {key_upper}")
        return ""

    if key_upper in stack:
        chain = " -> ".join([*stack, key_upper])
        raise ValueError(f"Detected cyclic reference in reference text: {chain}")

    stack.append(key_upper)

    def replace_var(match: re.Match[str]) -> str:
        var = match.group(1).strip().upper()
        return resolve_ref_value(config, var, default=None, required=True, _stack=stack)

    expanded = re.sub(r"\$\{([^}]+)\}", replace_var, raw)

    expanded_key = expanded.strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", expanded_key or ""):
        maybe_key = expanded_key.upper()
        if maybe_key in config and maybe_key != key_upper:
            expanded = resolve_ref_value(config, maybe_key, default=None, required=True, _stack=stack)

    stack.pop()
    return expanded.strip()


def resolve_io_dirs(ref_path: Path, config: Dict[str, str]) -> Tuple[Path, Path]:
    input_value = resolve_ref_value(config, REF_KEY_INPUT_DIR, required=True)
    output_value = resolve_ref_value(config, REF_KEY_OUTPUT_DIR, default="05_extracted_texts", required=False)

    input_dir = resolve_configured_dir(ref_path, input_value)
    output_dir = resolve_configured_dir(ref_path, output_value)
    return input_dir, output_dir


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


def expand_input_paths(inputs: Iterable[Path]) -> Tuple[List[Path], List[str], List[str]]:
    items, errors, warnings = expand_input_items(inputs)
    return [i.pdf_path for i in items], errors, warnings


INVALID_WINDOWS_FILENAME_CHARS = '<>:"/\\|?*'


def sanitize_dirname(name: str) -> str:
    cleaned = "".join("_" if ch in INVALID_WINDOWS_FILENAME_CHARS else ch for ch in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "folder"


@dataclass(frozen=True)
class InputPdf:
    pdf_path: Path
    source_dir: Optional[Path] = None


def expand_input_items(inputs: Iterable[Path]) -> Tuple[List[InputPdf], List[str], List[str]]:
    items: List[InputPdf] = []
    errors: List[str] = []
    warnings: List[str] = []

    seen_dirs: set[str] = set()
    seen_files: set[str] = set()

    def key_for(path: Path) -> str:
        try:
            return str(path.resolve()).lower()
        except Exception:
            return str(path).lower()

    def add_file(path: Path) -> None:
        key = key_for(path)
        if key in seen_files:
            return
        seen_files.add(key)
        items.append(InputPdf(pdf_path=path))

    def add_dir_pdf(source_dir: Path, pdf_path: Path, *, seen_within_dir: set[str]) -> None:
        key = key_for(pdf_path)
        if key in seen_within_dir:
            return
        seen_within_dir.add(key)
        items.append(InputPdf(pdf_path=pdf_path, source_dir=source_dir))

    for raw in inputs:
        path = Path(str(raw))
        if not path.exists():
            errors.append(f"not found: {path}")
            continue

        if path.is_dir():
            dir_key = key_for(path)
            if dir_key in seen_dirs:
                continue
            seen_dirs.add(dir_key)

            found: List[Path] = []
            for pattern in ("*.pdf", "*.PDF"):
                found.extend([p for p in path.rglob(pattern) if p.is_file()])
            found = sorted(found, key=lambda p: str(p).lower())
            if not found:
                warnings.append(f"no PDFs found under: {path}")
                continue
            seen_within_dir: set[str] = set()
            for p in found:
                add_dir_pdf(path, p, seen_within_dir=seen_within_dir)
            continue

        if path.suffix.lower() != ".pdf":
            errors.append(f"not a .pdf: {path}")
            continue

        add_file(path)

    return items, errors, warnings


def normalize_space(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class TextBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def iter_blocks(page: fitz.Page) -> Iterable[TextBlock]:
    for item in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_rest = item
        yield TextBlock(float(x0), float(y0), float(x1), float(y1), str(text))


def filter_header_footer(
    blocks: Iterable[TextBlock],
    page_height: float,
    header_ratio: float,
    footer_ratio: float,
) -> List[TextBlock]:
    header_cut = page_height * header_ratio
    footer_cut = page_height * (1.0 - footer_ratio)
    kept: List[TextBlock] = []
    for block in blocks:
        if block.y0 < header_cut:
            continue
        if block.y1 > footer_cut:
            continue
        kept.append(block)
    return kept


def blocks_to_text(
    blocks: List[TextBlock],
    y_tol: float,
) -> str:
    blocks = sorted(blocks, key=lambda b: (b.y0, b.x0))
    lines: List[str] = []

    current_line: List[TextBlock] = []
    current_y: Optional[float] = None
    current_count = 0

    def flush() -> None:
        nonlocal current_line, current_y, current_count
        if not current_line:
            return
        current_line = sorted(current_line, key=lambda b: b.x0)
        parts = []
        for block in current_line:
            cleaned = normalize_space(block.text)
            if cleaned:
                parts.append(cleaned)
        if parts:
            lines.append(" ".join(parts))
        current_line = []
        current_y = None
        current_count = 0

    for block in blocks:
        cleaned = normalize_space(block.text)
        if not cleaned:
            continue

        if current_y is None:
            current_y = block.y0
            current_count = 1
            current_line = [TextBlock(block.x0, block.y0, block.x1, block.y1, cleaned)]
            continue

        if abs(block.y0 - current_y) <= y_tol:
            current_line.append(TextBlock(block.x0, block.y0, block.x1, block.y1, cleaned))
            current_count += 1
            current_y = (current_y * (current_count - 1) + block.y0) / current_count
            continue

        flush()
        current_y = block.y0
        current_count = 1
        current_line = [TextBlock(block.x0, block.y0, block.x1, block.y1, cleaned)]

    flush()
    return "\n".join(lines).rstrip()


def page_text_blocks_mode(
    page: fitz.Page,
    y_tol: float,
    drop_header_footer: bool,
    header_ratio: float,
    footer_ratio: float,
) -> str:
    blocks = list(iter_blocks(page))
    if drop_header_footer:
        blocks = filter_header_footer(
            blocks,
            page_height=float(page.rect.height),
            header_ratio=header_ratio,
            footer_ratio=footer_ratio,
        )
    return blocks_to_text(blocks, y_tol=y_tol)


def page_text_text_mode(page: fitz.Page) -> str:
    return page.get_text("text").rstrip()


def extract_pdf_to_text(
    pdf_path: Path,
    mode: str,
    y_tol: float,
    drop_header_footer: bool,
    header_ratio: float,
    footer_ratio: float,
) -> Tuple[int, str]:
    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        parts: List[str] = []
        for idx in range(total_pages):
            page = doc.load_page(idx)
            if mode == "text":
                text = page_text_text_mode(page)
            else:
                text = page_text_blocks_mode(
                    page,
                    y_tol=y_tol,
                    drop_header_footer=drop_header_footer,
                    header_ratio=header_ratio,
                    footer_ratio=footer_ratio,
                )

            marker = PAGE_MARKER_TEMPLATE.format(page=idx + 1, total=total_pages)
            parts.append(marker)
            parts.append(text)
            parts.append("")  # empty line at page end

        return total_pages, "\n".join(parts).rstrip() + "\n"
    finally:
        doc.close()


@dataclass
class RunSummary:
    total: int = 0
    ok: int = 0
    fail: int = 0
    failed_files: List[str] = None  # type: ignore[assignment]
    failed_details: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed_files is None:
            self.failed_files = []
        if self.failed_details is None:
            self.failed_details = []


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    args = parse_args()

    try:
        config = read_reference_text(args.ref)
        input_dir, output_dir = resolve_io_dirs(args.ref, config)
    except Exception as exc:
        print(f"[REF] ERROR: {exc}")
        return 1

    print(f"[REF] input_dir={input_dir}")
    print(f"[REF] output_dir={output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.paths_file and args.pdfs:
        print("[ARGS] ERROR: use either --paths-file or positional paths, not both.")
        return 1

    explicit_items: Optional[List[InputPdf]] = None
    if args.paths_file or args.pdfs:
        try:
            raw_inputs = read_paths_file(args.paths_file) if args.paths_file else list(args.pdfs)
            explicit_items, errors, warnings = expand_input_items(raw_inputs)
        except Exception as exc:
            print(f"[ARGS] ERROR: {exc}")
            return 1

        print("[ARGS] Using explicit inputs; EXTRACT_INPUT_DIR is ignored.")

        for msg in warnings:
            print(f"[ARGS] WARN: {msg}")

        if errors:
            print("[ARGS] ERROR: invalid input paths")
            for msg in errors:
                print(f"  - {msg}")
            return 1
    else:
        if not input_dir.exists() or not input_dir.is_dir():
            print(f"[REF] ERROR: input_dir does not exist or is not a directory: {input_dir}")
            return 1

        pdf_paths = sorted(
            [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
            key=lambda p: p.name.lower(),
        )

    if explicit_items is not None:
        work_items = explicit_items
    else:
        work_items = [InputPdf(pdf_path=p, source_dir=None) for p in pdf_paths]

    summary = RunSummary(total=len(work_items))

    out_dir_by_source: Dict[str, Path] = {}
    used_out_dirnames: Dict[str, int] = {}
    used_root_out_names: Dict[str, int] = {}

    def get_group_out_dir(source_dir: Path) -> Path:
        key = str(source_dir.resolve()).lower()
        if key in out_dir_by_source:
            return out_dir_by_source[key]

        base = sanitize_dirname(source_dir.name)
        base_key = base.lower()
        if base_key in used_out_dirnames:
            used_out_dirnames[base_key] += 1
            name = f"{base}__{used_out_dirnames[base_key]}"
        else:
            used_out_dirnames[base_key] = 1
            name = base

        out_dir = output_dir / name
        out_dir_by_source[key] = out_dir
        return out_dir

    def allocate_root_out_name(stem: str) -> str:
        base_name = f"{stem}.txt"
        name_key = base_name.lower()
        if name_key in used_root_out_names:
            used_root_out_names[name_key] += 1
            return f"{stem}__{used_root_out_names[name_key]}.txt"
        used_root_out_names[name_key] = 0
        return base_name

    for item in work_items:
        pdf_path = item.pdf_path
        if item.source_dir is not None:
            group_out_dir = get_group_out_dir(item.source_dir)
            try:
                rel = pdf_path.relative_to(item.source_dir)
                out_path = group_out_dir / rel.with_suffix(".txt")
                display_in = f"{item.source_dir.name}\\{rel}"
            except Exception:
                out_path = group_out_dir / f"{pdf_path.stem}.txt"
                display_in = str(pdf_path)
            out_display = str(out_path)
        else:
            out_path = output_dir / allocate_root_out_name(pdf_path.stem)
            display_in = str(pdf_path)
            out_display = str(out_path)

        print(f"[RUN] {display_in} -> {out_display}")

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.exists() and not args.overwrite:
                doc = fitz.open(pdf_path)
                try:
                    pages = doc.page_count
                finally:
                    doc.close()
                print(f"[OK] pages={pages}")
                summary.ok += 1
                continue

            pages, text = extract_pdf_to_text(
                pdf_path,
                mode=args.mode,
                y_tol=args.y_tol,
                drop_header_footer=args.drop_header_footer,
                header_ratio=args.header_ratio,
                footer_ratio=args.footer_ratio,
            )

            tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(out_path)

            print(f"[OK] pages={pages}")
            summary.ok += 1
        except Exception as exc:
            print(f"[FAIL] {pdf_path.name} : {exc}")
            summary.fail += 1
            summary.failed_files.append(display_in)
            summary.failed_details.append(f"{display_in} : {exc}")

    print(f"[SUMMARY] total={summary.total} ok={summary.ok} fail={summary.fail}")

    if summary.fail:
        print("[FAILED LIST]")
        for detail in summary.failed_details:
            print(f"  - {detail}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
