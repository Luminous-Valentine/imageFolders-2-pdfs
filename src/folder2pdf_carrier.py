
import io
import shutil
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pikepdf
from PIL import Image

# Local import from the same directory
try:
    import ref_paths
except ImportError:
    # Fallback if running from a different CWD
    sys.path.append(str(Path(__file__).parent))
    import ref_paths


# Config Keys
KEY_INPUT_DIR = "INPUT_DIR"
KEY_OUTPUT_DIR = "OUTPUT_DIR"
KEY_BASE_PDF = "BASE_PDF_PATH"

# Image Extensions
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


def format_hms(seconds: float) -> str:
    """Formats seconds to HH:MM:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def make_progress_bar(current: int, total: int, width: int = 30) -> str:
    """Creates a text-based progress bar."""
    if total <= 0:
        return "[" + "-" * width + "]"
    ratio = current / total
    filled = int(width * ratio)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def create_letterbox_jpeg(image_path: Path, target_w: int, target_h: int) -> bytes:
    """
    Resizes image to fit within (target_w, target_h) preserving aspect ratio (letterbox),
    on a white background, and returns JPEG bytes.
    DOES NOT change the target_w/target_h values of the PDF XObject.
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        wi, hi = img.size
        
        # Calculate scale to fit
        if wi == 0 or hi == 0:
            s = 1.0
        else:
            s = min(target_w / wi, target_h / hi)
            
        new_wi = int(wi * s)
        new_hi = int(hi * s)
        
        # Resize
        resized_img = img.resize((new_wi, new_hi), Image.Resampling.LANCZOS)
        
        # Create canvas
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        
        # Center image
        paste_x = (target_w - new_wi) // 2
        paste_y = (target_h - new_hi) // 2
        
        canvas.paste(resized_img, (paste_x, paste_y))
        
        # Encode to JPEG
        out_bio = io.BytesIO()
        canvas.save(out_bio, format="JPEG", quality=90)
        return out_bio.getvalue()


def find_main_image_xobject_key(page):
    """
    Finds the key of the main image XObject in the page's resources.
    Heuristic: /Subtype /Image with the largest stream length.
    """
    if '/Resources' not in page or '/XObject' not in page.Resources:
        return None
        
    xobjects = page.Resources.XObject
    max_len = -1
    best_key = None
    
    for key, xobj in xobjects.items():
        if xobj.get('/Subtype') == '/Image':
            try:
                length = 0
                if '/Length' in xobj:
                    length = int(xobj['/Length'])
                else:
                    # Expensive fallback: read stream
                    length = len(xobj.read_raw_bytes())
                
                if length > max_len:
                    max_len = length
                    best_key = key
            except Exception:
                continue
                
    return best_key


def main():
    print(f"Script: {Path(__file__).name}")
    
    # 1. Load Configuration
    repo_root = Path(__file__).resolve().parent.parent
    ref_txt_path = ref_paths.default_ref_path(repo_root=repo_root)
    
    print(f"Reading configuration from: {ref_txt_path}")
    config = ref_paths.read_reference_text_best_effort(ref_txt_path)
    
    # Resolve Paths
    try:
        # INPUT_DIR
        raw_input = ref_paths.resolve_ref_value(config, KEY_INPUT_DIR, required=True)
        input_root = ref_paths.resolve_configured_path(ref_txt_path, raw_input)
        
        # OUTPUT_DIR
        raw_output = ref_paths.resolve_ref_value(config, KEY_OUTPUT_DIR, required=True)
        output_root = ref_paths.resolve_configured_path(ref_txt_path, raw_output)

        # BASE_PDF_PATH
        raw_base = ref_paths.resolve_ref_value(config, KEY_BASE_PDF, required=True)
        base_pdf_path = ref_paths.resolve_configured_path(ref_txt_path, raw_base)
        
    except ValueError as e:
        print(f"Configuration Error: {e}")
        print(
            f"Please ensure {KEY_INPUT_DIR}, {KEY_OUTPUT_DIR}, and {KEY_BASE_PDF} are set in {ref_txt_path.name}"
        )
        return

    # Check Existence
    if not input_root.exists():
        print(f"Error: Input directory not found: {input_root}")
        return
    if not base_pdf_path.exists():
        print(f"Error: Base PDF not found: {base_pdf_path}")
        return

    # Ensure Output Directory
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"Input:    {input_root}")
    print(f"Output:   {output_root}")
    print(f"Base PDF: {base_pdf_path}")
    print("-" * 60)

    # 2. Gather Folders
    folders = sorted([p for p in input_root.iterdir() if p.is_dir()])
    total = len(folders)
    
    if total == 0:
        print(f"No subfolders found in {input_root}")
        return

    # 3. Load Base PDF Reference
    try:
        base_pdf_doc = pikepdf.open(base_pdf_path)
        if len(base_pdf_doc.pages) < 1:
            print("Error: Base PDF has no pages.")
            return
        ref_page = base_pdf_doc.pages[0]
        
        # Verify Ref Image existence
        if not find_main_image_xobject_key(ref_page):
            print("Warning: No image found in Base PDF page 1. Replacement might fail.")
            
    except Exception as e:
        print(f"Error opening Base PDF: {e}")
        return

    # 4. Process Folders
    start_time = time.time()
    
    for idx, folder in enumerate(folders, start=1):
        folder_name = folder.name
        
        # Gather Images
        images = sorted(
            [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS],
            key=lambda x: x.name
        )
        
        if not images:
            print(f"[SKIP] No images: {folder_name}")
            continue
            
        output_pdf_path = output_root / f"{folder_name}.pdf"
        
        try:
            # Create new PDF in memory (to act as carrier)
            new_pdf = pikepdf.new()
            
            # Duplicate Base Page N times
            for _ in images:
                new_pdf.pages.append(ref_page)
                
            # Replace Images
            for i, img_path in enumerate(images):
                page = new_pdf.pages[i]
                
                # Shallow copy Resources/XObject dictionaries for this page
                # to ensure we don't modify the shared reference for other pages
                if '/Resources' in page:
                    page.Resources = pikepdf.Dictionary(page.Resources)
                    if '/XObject' in page.Resources:
                        page.Resources.XObject = pikepdf.Dictionary(page.Resources.XObject)
                
                target_key = find_main_image_xobject_key(page)
                
                if target_key:
                    xobj = page.Resources.XObject[target_key]
                    
                    try:
                        w = int(xobj.Width)
                        h = int(xobj.Height)
                    except AttributeError:
                        print(f"Warning: {folder_name} Page {i+1} has no Width/Height")
                        continue
                        
                    # Create Letterbox JPEG
                    jpeg_bytes = create_letterbox_jpeg(img_path, w, h)
                    
                    # Create New Stream Object
                    new_xobj = pikepdf.Stream(
                        new_pdf,
                        jpeg_bytes,
                        **xobj # Inherit Dictionary items (Width, Height, Subtype, etc.)
                    )
                    new_xobj['/Filter'] = '/DCTDecode' # Force JPEG filter
                    
                    # Replace
                    page.Resources.XObject[target_key] = new_xobj
                else:
                    print(f"Warning: {folder_name} Page {i+1} - No target image XObject found")
            
            # Save
            new_pdf.save(output_pdf_path)
            
        except Exception as e:
            print(f"Error processing {folder_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

        # Progress
        elapsed = time.time() - start_time
        percent = idx / total * 100.0
        bar = make_progress_bar(idx, total, width=30)
        
        avg_per_folder = elapsed / idx
        estimate_total = avg_per_folder * total
        remain = max(0.0, estimate_total - elapsed)

        print(
            f"{bar} {percent:5.1f}%  "
            f"({idx}/{total}) Folder '{folder_name}' Done  "
            f"Elapsed {format_hms(elapsed)}  ETA {format_hms(remain)}"
        )
        
    if base_pdf_doc:
        base_pdf_doc.close()

    print("-" * 60)
    total_elapsed = time.time() - start_time
    print(f"Completed. Total Time: {format_hms(total_elapsed)}")


if __name__ == "__main__":
    main()
