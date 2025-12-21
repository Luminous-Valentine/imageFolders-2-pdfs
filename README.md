# 画像フォルダ群 → PDF群 変換ツール

img2pdf を利用して、入力ディレクトリ直下の各サブフォルダに含まれる画像をフォルダ単位で 1 本の PDF にまとめます。

## セットアップ
1. Python 3.9+ をインストールします。
2. 依存パッケージを導入します。
   ```bash
   pip install img2pdf
   ```

## ディレクトリ構成例
```
project_root/
├─ folder2pdf.py
├─ run.bat
├─ input/
│   ├─ AAA/
│   │   ├─ 1.jpg
│   │   ├─ 2.jpg
│   │   └─ 10.jpg
│   └─ BBB/
│       ├─ page1.png
│       └─ page2.png
└─ output/           ← 生成先 (存在しなくても自動作成)
```

## 使い方 (Windows)
1. `run.bat` 内の `INPUT_DIR` と `OUTPUT_DIR` を必要に応じて書き換えます。既定では `run.bat` と同じ階層の `input` と `output` を参照します。
2. `run.bat` をダブルクリックして実行します。
3. 各サブフォルダごとに `<サブフォルダ名>.pdf` が OUTPUT_DIR に生成されます。

## 仕様概要
- 対象: `INPUT_DIR` 直下のサブフォルダ (再帰しない)
- 対応拡張子: `.jpg .jpeg .png .tif .tiff`
- ページ順: ファイル名を自然順でソート (例: 1, 2, 10)
- 変換方式: `img2pdf.convert` を使用
- 既存の同名 PDF がある場合は上書き
- 子フォルダに対象画像が 0 枚の場合はスキップして警告
- フォルダ単位での失敗は記録し、処理は継続
- 実行後に 成功/失敗/スキップ 数を表示

## 実行ログ例
```
INFO: Input directory: C:\path\to\project\input
INFO: Output directory: C:\path\to\project\output
INFO: Converting 3 image(s) in 'AAA' -> C:\path\to\project\output\AAA.pdf
INFO: Completed 'C:\path\to\project\output\AAA.pdf'
WARNING: Skipping 'BBB': no target images found.
INFO: Summary: 1 succeeded, 0 failed, 1 skipped
```

## トラブルシュート
- `img2pdf` が見つからない: `pip install img2pdf` を実行してください。
- PDF が作成されない: 入力フォルダに画像があるか、拡張子がサポート対象か確認してください。
- 権限エラー: `OUTPUT_DIR` の書き込み権限を確認してください。
