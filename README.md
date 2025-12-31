# imageFolders-2-pdfs

画像フォルダ→PDF生成、OCR結果との照合移動、PDFの分割/結合、PDFの文字抽出（テキストレイヤー抽出）などをまとめた作業用リポジトリです。

---

## 目次

- 事前準備（共通）
- 設定ファイル（tool_settings.txt）
- 機能01：画像フォルダ → PDF（img2pdf方式）
  - 拡張：Carrier方式（テンプレ差し替え）
- 機能02：OCR済みPDFと照合して移動（ファイル名一致）
- 機能03：PDF分割（1PDF → 複数PDF）
- 機能04：PDF結合（複数PDF → 1PDF）
- 機能05：PDF文字抽出（PDF → TXT）
- よくあるトラブル

---

## 事前準備（共通）

### 必要環境

- Windows（`.bat` / `.ps1` を利用）
- Python 3.x
- Pythonスクリプトは `src/` 配下にあります（`.bat` / `.ps1` から呼び出します）

### 依存ライブラリのインストール

リポジトリ直下で以下を実行します。

```bat
pip install -r requirements.txt
```

※ Carrier方式（テンプレPDF差し替え）を使う場合は `pikepdf` も必要です（`src\\folder2pdf_carrier.py` が使用します）。

---

## 設定ファイル（tool_settings.txt）

各ツールは `tool_settings.txt` の `KEY=VALUE` を参照して動作します（互換のため `reference_paths.txt` も読み取り可）。

- 空行、`#` で始まる行は無視されます
- 値は「絶対パス」または「このリポジトリ直下からの相対パス」を指定できます
- 変数展開に対応しています
  - `${KEY}` 形式（例: `EXTRACT_INPUT_DIR=${OCR_DIR}`）
  - 値に別キー名を指定する形式（例: `EXTRACT_OUTPUT_DIR=OUTPUT_DIR`）

### 主なキー一覧

- `INPUT_DIR`: 画像フォルダ（サブフォルダ）を置く親フォルダ（画像→PDFの入力）
- `OUTPUT_DIR`: 画像→PDFの出力フォルダ
- `FOLDER2PDF_DEFAULT_METHOD`: `01_images_to_pdf.bat` のデフォルト方式（`img2pdf` / `carrier`）
- `FOLDER2PDF_BACKEND`: img2pdf方式のPDF生成バックエンド（`img2pdf` / `pikepdf`）
- `FOLDER2PDF_PIKEPDF_INTERPOLATE`: pikepdf時に `/Interpolate true` を付けて表示補間を滑らかにする（`true/false`）
- `FOLDER2PDF_PIKEPDF_FORCE_PNG`: pikepdf時に JPEG も可逆(PNG相当)で埋め込む（`true/false`、サイズ増加）
- `FOLDER2PDF_OVERWRITE`: 画像→PDFで既存PDFを上書きするか（`true/false`）
- `FOLDER2PDF_DPI`: img2pdf方式のデフォルトDPI（PDF上の物理サイズ計算用）
- `FOLDER2PDF_OPTIMIZE_MODE`: img2pdf方式のデフォルト（`lossless/auto/size`）
- `FOLDER2PDF_JPEG_QUALITY`: 再エンコード時のJPEG品質（1〜100）
- `FOLDER2PDF_MAX_LONG_EDGE`: 再エンコード時の最大長辺px（0=自動）
- `FOLDER2PDF_AUTO_REENCODE_THRESHOLD_MB`: `auto` 時にPNGを再エンコードするサイズ閾値（MB）
- `OCR_DIR`: OCR済みPDFの置き場（照合/抽出で利用）
- `MATCHED_DIR`: OCR済みと一致したPDFの移動先
- `SPLIT_OUTPUT_DIR`: PDF分割結果の出力先（`src\\split_pdf.py`）
- `SPLIT_OCR_FOLDER_ROOT`: 分割完了後に `<元PDF名>/` フォルダを作成する親フォルダ（空欄ならスキップ、`${OCR_DIR}` 等の参照も可）
- `MERGE_OUTPUT_DIR`: PDF結合結果の出力先（`src\\merge_pdf.py`）
- `EXTRACT_INPUT_DIR`: 文字抽出（PDF→TXT）の入力フォルダ
- `EXTRACT_OUTPUT_DIR`: 文字抽出（PDF→TXT）の出力フォルダ
- `BASE_PDF_PATH`: Carrier方式で使うテンプレPDF（任意：Carrier方式を使う場合のみ）

---

## 機能01：画像フォルダ → PDF（img2pdf方式）

### 目的

`INPUT_DIR` 配下の「各サブフォルダ」を 1つのPDFにします（フォルダ単位でPDF化）。

例:

```
01_images_input/
  本A/
    001.jpg
    002.jpg
  本B/
    001.png
```

→

```
01_pdf_output/
  本A.pdf
  本B.pdf
```

### 実行方法（推奨）

`01_images_to_pdf.bat` をダブルクリックして起動します。

起動後の画面で:

- Enterだけ: `tool_settings.txt` のデフォルト設定で実行
- `3` を選ぶ: オプションを指定して実行
  - img2pdf方式は backend（`img2pdf` / `pikepdf`）を選べます（`pikepdf` はJPEGフォルダ向け）
  - 最後に「対象の画像フォルダ」をドラッグ＆ドロップで指定できます（Enterだけなら `INPUT_DIR` 配下を全て処理）
- `2` を選ぶ: Carrier方式（テンプレPDF差し替え）で実行（デフォルトではありません）

内部的には PowerShell 経由で `src\\folder2pdf.py`（または `src\\folder2pdf_carrier.py`）を呼びます。

既に同名のPDFが存在する場合はスキップされます（上書きしたい場合は `src\\folder2pdf.py` に `--overwrite` を付けて実行してください）。

※ メニュー無しで実行したい場合は `01_run_folder2pdf.ps1` を右クリック → 「PowerShellで実行」でも同様に実行できます。

### 画像順序

- 画像はファイル名の自然順（例: `1, 2, 10` の順）で並べます。

### 品質/容量の考え方（自動調整）

基本方針:

- JPEGは「そのままPDFに埋め込み」できるため、再エンコードしない＝品質劣化しないのが基本です
- PNG/TIFF/BMPなどは、条件によっては自動でJPEG化＋必要なら縮小して、PDFが無駄に巨大化するのを抑えます

調整は `--optimize-mode` で行います:

- `lossless`:
  - 一切再エンコードしません（最優先で画質維持）
  - ただし、入力画像が巨大/非効率だとPDFサイズも巨大になりやすいです
- `auto`（デフォルト）:
  - JPEGはそのまま（劣化なし）
  - PNGは「大きすぎる場合のみ」再エンコード対象にします（閾値は `--auto-reencode-threshold-mb`）
  - それ以外の形式は必要に応じて再エンコードします
- `size`:
  - PDFサイズを抑える寄り（非JPEGは再エンコードされやすい）

ページサイズに関係する主な指定:

- `--dpi`（デフォルト300）: PDF上の物理サイズ（mm相当）を決めるために使います
- 画像を縮小する必要がある場合は `auto/size` の再エンコード設定の一部として行われます

pikepdfバックエンド専用の表示/可逆オプション:

- `--pikepdf-interpolate`: PDF上の画像に `/Interpolate true` を付け、ビューアの拡大縮小時に滑らかに描画するヒントを与えます（画像データは無変化）
- `--pikepdf-png`: JPEGも一度デコードして可逆(PNG相当)で埋め込みます（サイズは増えやすい）

### 拡張：Carrier方式（テンプレ差し替え）

※ img2pdf方式で十分な場合は、この機能は不要です（テンプレPDFが必要です）。

#### 目的

テンプレPDF（`BASE_PDF_PATH`）の「ページ枠/レイアウト」を保ったまま、画像だけ差し替える方式でPDFを生成します。

#### 実行方法

1. `tool_settings.txt` に `BASE_PDF_PATH` を追加
2. `01_images_to_pdf.bat` のメニューで `2` を選ぶ、または `01_run_folder2pdf_carrier.ps1` を右クリック → 「PowerShellで実行」

出力:

- `OUTPUT_DIR/{フォルダ名}.pdf`

---

## 機能02：OCR済みPDFと照合して移動（ファイル名一致）

### 目的

`OUTPUT_DIR` 内のPDFについて、`OCR_DIR` に同名PDFが存在するものを `MATCHED_DIR` に移動します（ファイル名一致）。

### 実行方法（推奨）

`02_ocr_move_matched_pdfs.bat` をダブルクリックして起動します。

### 挙動の詳細

- 比較対象:
  - 移動元: `OUTPUT_DIR`
  - 参照元: `OCR_DIR`（※ 現状は `OCR_DIR` 直下のPDFのみ。サブフォルダは見ません）
  - 移動先: `MATCHED_DIR`（未設定なら `02_matched_pdfs`）
- `02_run_move_matched_pdfs.ps1` は、必要に応じてOCRフォルダパスの入力を促し、その値を `tool_settings.txt` の `OCR_DIR` に書き戻します（旧: `reference_paths.txt`）。

---

## 機能03：PDF分割（1PDF → 複数PDF）

`src\\split_pdf.py` は、PDFをN分割します（ページをほぼ均等に連番で分割）。

### 実行方法（推奨）

`03_pdf_split.bat` をダブルクリックして起動します。

ドラッグ＆ドロップ対応:
- 単体/複数のPDF
- 単体/複数のフォルダ（直下にあるPDFを対象にします。再帰はしません）

ドラッグ＆ドロップ後の流れ:
1. 検出したPDFのサイズ/ページ数を一覧表示
2. 分割数を入力
3. 分割処理を実行（出力は `SPLIT_OUTPUT_DIR`）
4. 分割完了後、`SPLIT_OCR_FOLDER_ROOT\\<元PDF名(拡張子なし)>\\` を作成（`SPLIT_OCR_FOLDER_ROOT` が空欄ならスキップ）

### Pythonを直接実行する場合

対話形式:

```bat
python src\\split_pdf.py
```

ワンライナー:

```bat
python src\\split_pdf.py "C:\path\file.pdf" --parts 3
```

出力先:

- `SPLIT_OUTPUT_DIR`（未設定なら `03_split_pdfs`）
- 出力形式: `<output_root>/<pdf_stem>/<pdf_stem>_01.pdf, ...`

---

## 機能04：PDF結合（複数PDF → 1PDF）

### 実行方法（推奨）

`04_pdf_merge.bat` をダブルクリックして起動します。

### 入力の指定方法

- 画面の指示に従って、PDFやフォルダをドラッグ＆ドロップして Enter
- もしくは `04_pdf_merge.bat` にPDF/フォルダを直接ドラッグ＆ドロップ
  - フォルダを指定した場合は配下のPDFを再帰的に収集して結合対象にします

### 出力先

- `MERGE_OUTPUT_DIR`（未設定なら `04_merged_pdfs`）
- ファイル名は対話で指定（未入力なら自動提案）

---

## 機能05：PDF文字抽出（PDF → TXT）

### 実行方法（推奨）

`05_pdf_extract_text.bat` をダブルクリックして起動します。

### 入力の指定方法

- 起動したDOS画面で Enter だけ:
  - `EXTRACT_INPUT_DIR` 直下のPDFを対象にします
- 起動したDOS画面にPDF/フォルダを複数ドラッグ＆ドロップして Enter:
  - ドロップしたものだけを対象にします（フォルダの場合は配下のPDFを再帰的に全て処理します）
- `05_pdf_extract_text.bat` にPDF/フォルダを直接ドラッグ＆ドロップ:
  - ドロップしたものだけを対象に処理します

※ 既に同名のTXTが存在する場合はデフォルトでスキップされます（上書きしたい場合は `src\\extract_pdf_text.py` に `--overwrite` を付けて実行してください）。

#### 出力先のルール

- 入力が「PDFファイルのみ」の場合:
  - `EXTRACT_OUTPUT_DIR` 直下に `{pdf_stem}.txt`
- 入力が「フォルダ」の場合:
  - `EXTRACT_OUTPUT_DIR/<入力フォルダ名>/.../{pdf_stem}.txt`

### 結果表示（失敗一覧）

処理の最後に `[SUMMARY] total=... ok=... fail=...` を表示し、失敗が1件でもあれば直下に `[FAILED LIST]` としてファイル一覧（エラー理由付き）を表示します。

---

## よくあるトラブル

- `src\\folder2pdf_carrier.py` が `Missing required key ... BASE_PDF_PATH` で止まる
  - `tool_settings.txt` に `BASE_PDF_PATH=` が未設定です
- PowerShell実行ポリシーで `.ps1` が動かない
  - 右クリック実行、または `powershell -ExecutionPolicy Bypass -File ...` を利用してください
