# TeaForge

[![CI](https://github.com/cyberyimein/TeaForge/actions/workflows/ci.yml/badge.svg)](https://github.com/cyberyimein/TeaForge/actions/workflows/ci.yml)

TeaForge は、自動テストから監査可能な日本式単体テスト仕様書（PCL, Program Check List）と、Mermaid のフローチャート／シーケンス図を含むファイル単位カバレッジレポートを生成します。

エンジニアとコーディングエージェントの両方を対象にしています。付属の [`skill/SKILL.md`](skill/SKILL.md) には、対応ワークフロー、コマンド境界、作図ルールを記載しています。

## 主な機能

- `pytest`、Jest/TypeScript、Angular/Jest、Playwright のテストを PCL に変換
- Jest の実行時 matcher 証拠（期待値、実際値、matcher、成否、`.not`、Promise、例外）を取得
- バージョン付き PCL を JSON と HTML の組として生成
- Python coverage または Jest/Istanbul `coverage-final.json` からファイル単位 C0/C1 レポートを生成
- カバレッジレポートに型付き Mermaid フローチャート／シーケンス図ページを追加
- 任意依存の WeasyPrint による PDF 出力
- `doctor` によるパッケージと対象プロジェクトの機械可読な事前診断

## インストール

Python 3.11 以降が必要です。

macOS / Linux:

```bash
git clone https://github.com/cyberyimein/TeaForge.git
cd TeaForge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Windows PowerShell:

```powershell
git clone https://github.com/cyberyimein/TeaForge.git
cd TeaForge
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
```

PDF が必要な場合だけ追加依存を入れます。

```bash
python -m pip install ".[pdf]"
```

開発とリポジトリ内デモには次を使用します。

```bash
python -m pip install -e ".[dev,pdf]"
```

インストール後に CLI と同梱リソースを確認します。

```bash
teaforge --version
teaforge doctor --framework pytest --path demo/fastapi_crud/tests
```

## 外部ツール

### Jest

Jest の実行時証拠とカバレッジには `node` と、対象プロジェクトへ導入済みの Jest が必要です。TeaForge は最寄りの `node_modules/.bin/jest`（ワークスペース上位へ hoist されたものを含む）を発見し、対象プロジェクトのルートから正確なテストパスを指定して実行します。

TeaForge は `npx` を呼ばず、Jest を暗黙にダウンロードしません。先に対象プロジェクトの lockfile に従って依存を導入してください。

```bash
npm ci
teaforge doctor --framework jest --path tests/user.test.js --json
```

### Mermaid

構文検証と SVG 描画には `mmdc` が必要です。

```bash
npm install -g @mermaid-js/mermaid-cli
teaforge doctor --framework pytest --require-mermaid
```

Chromium の起動設定が必要な環境では、`TEAFORGE_MERMAID_PUPPETEER_CONFIG` に `mmdc` 用 Puppeteer JSON ファイルを指定できます。このリポジトリの `--no-sandbox` は隔離された CI runner だけで使用します。一般的な開発端末へその設定をコピーしないでください。

### PDF

PDF 出力は任意依存の `weasyprint` と Pango/Cairo のネイティブ依存を使用します。利用前に確認してください。

```bash
teaforge doctor --framework pytest --require-pdf
```

macOS では `brew install weasyprint` が簡単です。Windows では WeasyPrint/MSYS2 の手順に従い、必要に応じて `WEASYPRINT_DLL_DIRECTORIES` で Pango DLL の場所を指定してください。

## クイックスタート

### pytest PCL

```bash
teaforge pcl generate \
  --path demo/fastapi_crud/tests \
  --output output/pcl.html
```

TeaForge は証明できたテスト対象ごとにケースをまとめ、HTML/JSON の組を出力します。1 シートは 25 ケース列で、超過分は複数シートに分割されます。JSON には `schema_version` が含まれます。

### 実行時証拠付き Jest PCL

```bash
teaforge pcl generate \
  --framework jest \
  --evidence-mode runtime \
  --path demo/jest_runtime/tests/user.test.js \
  --output output/jest-pcl.html
```

証拠モード:

- `static`: Jest を実行せず、設計時の期待値を静的解析
- `runtime`: Jest 実行を必須とし、観測した matcher 証拠を記録
- `auto`: 実行時証拠を試し、プロジェクトローカル runner または assertion hook が利用不能な場合だけ静的解析へフォールバック。タイムアウトや Jest 設定／実行エラーは静的レポートで隠さず失敗として扱います。

Jest が実行されテストが失敗した場合も、TeaForge は失敗証拠を含むレポートを書き、終了コード `2` を返します。失敗を意図的に受け入れる場合だけ `--allow-test-failures` を使ってください。`--runtime-timeout` はワークフロー全体の上限で、期限切れ時はランナーのプロセスツリーを終了し、診断出力も上限付きで保持します。

静的パーサーは一般的な `test`/`it`、配列リテラルの `test.each`、ESM 相対 import、CommonJS の分割代入／別名／名前空間 `require`、直接関数呼び出し、主要 matcher に対応します。複雑な変換構文、動的 import、計算で生成されるテストは実行時証拠が必要になる場合があります。

### PCL の参照と PDF 出力

```bash
teaforge get --path output/pcl.json --testcase TC-001
teaforge export --path output/pcl.html --output output/pcl.pdf
```

### 図を用意する

フローチャート:

```bash
teaforge mermaid generate \
  --source demo/fastapi_crud/app/main.py \
  --function create_item \
  --diagram-type flowchart \
  --code "flowchart TD
    A[Receive request] --> B{Valid?}
    B -- No --> C[Return validation error]
    B -- Yes --> D[Create item]
    D --> E[Return item]" \
  --output-dir output/files
```

シーケンス図:

```bash
teaforge mermaid generate \
  --source demo/fastapi_crud/app/main.py \
  --function create_item \
  --diagram-type sequence \
  --code "sequenceDiagram
    Client->>API: Create item
    API->>DB: Insert item
    DB-->>API: Stored row
    API-->>Client: Created response" \
  --output-dir output/files
```

`mermaid generate` は型を検証した `.mmd` ソースを保存します。未対応の図種は誤った型として保存せず、明示的に失敗します。

### カバレッジレポート

Python:

```bash
teaforge coverage generate \
  --path demo/fastapi_crud/tests \
  --output output/main-coverage.html \
  --min-c0 90 \
  --min-c1 100 \
  --function create_item \
  --sequence create_item \
  --diagram-dir output/files
```

対象プロジェクトが別の仮想環境を使う場合は、その Python を指定します。

```bash
teaforge doctor \
  --framework pytest \
  --path /project/tests \
  --python-executable /project/.venv/bin/python

teaforge coverage generate \
  --path /project/tests \
  --python-executable /project/.venv/bin/python \
  --runtime-timeout 180 \
  --output output/project-coverage.html
```

Jest:

```bash
teaforge coverage generate \
  --framework jest \
  --path demo/jest_runtime/tests/user.test.js \
  --output output/jest-coverage.html \
  --runtime-timeout 180
```

レポートは証明できた業務ソースファイル単位で生成されます。Jest テストを実ソースへ対応付けられない場合は即時に失敗します。`--function` はフローチャート、`--sequence` はシーケンス図を追加し、どちらも繰り返し指定できます。測定対象の文または分岐が存在しない指標は `N/A` と表示し、その指標の閾値判定から除外します。

## CLI ヘルプと終了コード

```bash
teaforge help
teaforge help pcl generate
teaforge help coverage generate
```

- `0`: コマンドが完了し、必須結果も許容可能
- `1`: 入力不正、能力不足、実行失敗、生成失敗
- `2`: Jest は実行されレポートも生成されたが、1 件以上のテストが失敗
- `3`: カバレッジレポートは生成されたが、`--min-c0` または `--min-c1` を未達

出力は同じディレクトリの一時ファイルへ書き、原子的に置換します。これにより単一ファイル書き込み中断時に以前の成果物を壊しません。複数成果物はすべての検証・描画後に置換しますが、同じ出力パスへの並行書き込みは未対応です。

## プロジェクト構成

```text
TeaForge/
  src/teaforge/            # CLI とサービスモジュール
  src/teaforge/templates/  # 同梱 PCL／カバレッジテンプレート
  src/teaforge/jest/assets # 同梱実行時 listener
  demo/fastapi_crud/       # 実行可能 pytest デモ
  demo/jest_runtime/       # lockfile 付き Jest デモ
  tests/                   # 単体・CLI 統合テスト
  docs/adr/                # 長期的なアーキテクチャ判断
  CHANGELOG.md             # リリース単位の変更履歴
  skill/SKILL.md           # エージェント向け手順
  .github/workflows/ci.yml # テスト、パッケージ、実 Jest 検証
```

共通のドメイン用語は [`CONTEXT.md`](CONTEXT.md)、実行／成果物の設計判断は [`docs/adr/`](docs/adr/) に記録しています。

## 開発・リリース確認

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ruff check src tests demo
python -m coverage run -m pytest -q
python -m coverage report
python -m compileall -q src tests
npm --prefix demo/jest_runtime ci
npm --prefix demo/jest_runtime test
python -m build
python -m twine check dist/*
```

別のコンピュータへリポジトリをコピーした後は `.venv` を作り直してください。仮想環境にはマシン固有の Python パスが含まれるため、ソースと一緒に移動する対象ではありません。

CI は Linux 上の Python 3.11／3.14 と Windows 上の Python 3.12 を検証し、Ruff と分岐カバレッジ 80% の基準を適用します。さらに wheel/sdist を構築し、隔離した wheel インストールから実 pytest カバレッジを実行し、Node 20／22 で lockfile 付き Jest デモをプロジェクト外から実行します。

## 現在の境界

- JavaScript/TypeScript のソース発見は、TeaForge に同梱された Tree-sitter の JavaScript／TypeScript／TSX 文法で構造的に解析し、コメントや文字列中の import／test 風テキストを無視します。ただし TypeScript の型検査や動的・大幅に変換されたテストの評価は行わないため、その場合は実行時証拠を使い、解決されたソース識別子を確認してください。
- ディレクトリ探索では `node_modules`、`.venv`、`dist`、`build` などの生成済み依存・環境ツリーを除外します。そこを意図的に解析する場合は正確なファイルパスを渡してください。
- 実行時証拠には、機密キーと一般的な認証情報パターンの既定マスキング、値の切り詰め、レコード／ファイル上限を適用します。より厳しい機密要件を持つプロジェクトでは、レポートを保管する前にこの既定方針で十分か確認してください。
- C0/C1 の成果物には証拠プロバイダーと指標定義を保持します。任意の `--min-c0`／`--min-c1` ゲートは、生成された全ソースファイルレポートへ適用されます。
- Mermaid と PDF は明示的な任意能力で、`teaforge doctor` が個別に確認します。

これらの境界を明示し、自動処理がもっともらしい誤レポートを黙って生成しないようにしています。
