# TeaForge

TeaForge は、自動テストを日本式の単体テストドキュメント（PCL, Program Check List）へ変換し、Mermaid フローチャート付きのカバレッジレポートを生成します。

このプロジェクトは、単に人間が手動で使うためのコマンドラインツールではありません。主な利用シナリオは AI エージェントとの協調です。`skill/SKILL.md` には、TeaForge の機能、CLI インターフェース、利用境界、フローチャート生成ルールなどの知識がまとめられています。GitHub Copilot や Claude Code のようなエージェントは、この skill を読み込むことで、TeaForge をいつ呼び出すべきか、どの引数を渡すべきか、失敗した呼び出しをどう修正すべきかを理解できます。これにより、テスト生成、ドキュメント生成、カバレッジレポート生成の信頼性が向上します。

現在実装済みの機能:

- `pytest` テスト解析
- `jest` / `TypeScript` テスト解析
- `JSON + HTML` での PCL 生成
- HTML の PDF 出力（WeasyPrint）
- 個別テストケース説明の CLI 参照
- ファイル単位の複数ページ対応カバレッジレポート（C0 / C1 + Mermaid SVG）

## ディレクトリ構成

```text
TeaForge/
  src/teaforge/            # コア実装と CLI
  templates/               # PCL HTML テンプレート
  demo/fastapi_crud/       # 内部用 FastAPI + SQLite + pytest デモ
  tests/fixtures/jest_sample/ # 最小構成の Jest / TypeScript フィクスチャ
  output/                  # ローカル HTML / JSON / PDF 出力先
  tests/                   # TeaForge 自身のテストスイート
  skill/                   # Skill ファイル
  project.md               # プロジェクト目標の説明
  Step1.md                 # フェーズ 1 要件
```

## インストール

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,pdf]"
```

### Windows

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,pdf]"
```

## Node / Jest の前提条件

`jest` / `TypeScript` の PCL またはカバレッジ機能を使う場合は、ローカルの Node.js 環境も必要です。

### 必要ツール

- `node`
- `npx`
- プロジェクトローカルの `jest` 実行ファイル

### カバレッジ要件

`teaforge coverage generate --framework jest` は、Jest が生成する Istanbul 形式の `coverage-final.json` に依存します。

TeaForge は現在、次のコマンドを呼び出します:

```bash
npx jest --coverage --coverageReporters=json --coverageDirectory <temp-dir> --runInBand <test-path>
```

### Mermaid 要件

カバレッジレポートを `pytest` から生成する場合でも `jest` から生成する場合でも、Mermaid フローチャートにはローカルの `mmdc` インストールが必要です:

```bash
npm install -g @mermaid-js/mermaid-cli
```

## PDF 出力依存関係（WeasyPrint）

TeaForge の HTML 生成は Python パッケージのみに依存します。PDF 出力はそれに加えて WeasyPrint のシステムライブラリが必要です。  
`teaforge export` 実行時に `libgobject`、`Pango`、`Cairo`、または DLL / 共有ライブラリ不足が報告された場合は、利用しているプラットフォーム向けの必要パッケージをインストールしてください。

### macOS

WeasyPrint 公式ドキュメントによると、最も簡単な方法はまず Homebrew で WeasyPrint と依存関係をインストールすることです:

```bash
brew install weasyprint
```

そのうえで、プロジェクトの仮想環境内で TeaForge を使う場合は、次の手順も実行してください:

```bash
source .venv/bin/activate
pip install -e ".[dev,pdf]"
```

共有ライブラリがまだ見つからない場合は、次を設定できます:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

通常のプレフィックスは、Apple Silicon Mac では `/opt/homebrew`、Intel Mac では `/usr/local` です。

### Windows

TeaForge は Windows でも動作する可能性があります。PDF 出力には、事前に Pango とその依存関係をインストールする必要があります。  
WeasyPrint 公式ドキュメントに基づく推奨手順は次のとおりです:

1. Python をインストールします。
2. [MSYS2](https://www.msys2.org/) をインストールします。
3. MSYS2 シェルで次を実行します:

```bash
pacman -S mingw-w64-x86_64-pango
```

4. PowerShell または `cmd` に戻って、プロジェクトをインストールします:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,pdf]"
```

DLL がまだ不足する場合は、現在のターミナルで次を設定します:

```powershell
$env:WEASYPRINT_DLL_DIRECTORIES="C:\msys64\mingw64\bin"
```

`cmd.exe` での等価な設定は次のとおりです:

```cmd
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
```

### 出力コマンド例

```bash
teaforge export --path output/test_items/demo-pcl-test-create-item-normal.html --output output/test_items/demo-pcl-test-create-item-normal.pdf
```

## CLI の使い方

TeaForge の主要な CLI 利用者は、人間のターミナルユーザーではなくエージェントです。つまり、設計目標は「人間が最短で打てるコマンドは何か」ではなく、次の点にあります:

- エージェントが `help` 出力からパラメータと制約を理解できるか
- 失敗メッセージから明確な修正経路を取得できるか
- PCL / カバレッジ / Mermaid のワークフローを自動的につなげられるか

このため、TeaForge CLI は読みやすいヘルプ、明示的なエラーメッセージ、依存関係や入力不足時の実行可能な修正ヒントを提供することを重視しています。これらのフィードバックはエージェントが読み取り、修正したパラメータで再実行することを想定しています。

TeaForge は現在、`--framework` でテストフレームワークを選択します:

- `pytest`: デフォルト
- `jest`: Node.js / TypeScript の Jest テスト向け

PCL を生成する:

```bash
teaforge pcl generate --path demo/fastapi_crud/tests --output output/pcl.html
```

補足:

- デフォルトでは、TeaForge はテスト対象関数ごとに 1 つの PCL ファイルを生成します。同じ関数を対象にする複数テストケースは同じ PCL に統合されます。
- 生成された PCL では、`file` と `method` は実際のテスト対象ソースファイルと実装関数を優先します。デモでは `main.py` / `create_item` になります。
- マトリクスは常に 25 個のテストケース列を確保します。
- 1 つの関数に 25 件を超えるテストケースがある場合、TeaForge は自動的に複数のシートファイルへ分割します。
- 入力パスに複数のテスト対象関数が含まれる場合、TeaForge はテスト対象ファイル名ごとにサブディレクトリを作成し、それぞれの HTML/JSON を出力します。

Jest / TypeScript PCL を生成する:

```bash
teaforge pcl generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest-pcl.html
```

現在主にサポートしている Jest 構文:

- `test(...)`
- `it(...)`
- `test.only(...)` / `it.only(...)`
- `test.each([...])(...)`
- 相対パス `import`
- 直接 import された関数呼び出し
- `expect(...).toBe(...)`
- `expect(...).toEqual(...)`
- `expect(...).toStrictEqual(...)`
- `expect(...).toContain(...)`
- `expect(() => fn(...)).toThrow(...)`

現在の Jest 制限事項:

- 相対 `TypeScript` / `JavaScript` import が主なサポート対象です。
- `test.each` は現在、配列リテラルの行データをサポートしています。
- すべての Jest / ts-jest / Babel 構文バリエーションをまだ網羅していません。
- 完全な Node.js デモプロジェクトはまだありません。現状の検証は主に `tests/fixtures/jest_sample` に依存しています。

PDF を出力する:

```bash
teaforge export --path output/pcl.html --output output/pcl.pdf
```

テストケースを参照する:

```bash
teaforge get --path output/pcl.html --testcase TC-001
```

補足:

- `generate` は各 HTML ファイルに対応する `.json` ファイルも同時に出力します。
- `get` は JSON を優先して読み込みます。埋め込みデータを含む HTML を渡した場合も、そこから直接読み取れます。
- エージェントは `teaforge help`、`teaforge help pcl generate`、`teaforge help coverage generate` の説明を読み、エラーフィードバックに応じてパラメータを調整できます。

Mermaid を検証する:

```bash
teaforge mermaid validate --code "flowchart TD
  A[Start] --> B[End]"
```

関数単位の Mermaid ファイルを生成する:

```bash
teaforge mermaid generate \
  --source demo/fastapi_crud/app/main.py \
  --function create_item \
  --code "flowchart TD
    A[Start] --> B[Create item]
    B --> C[Return response]" \
  --output-dir output/files
```

カバレッジレポートを生成する:

```bash
teaforge coverage generate \
  --path demo/fastapi_crud/tests \
  --output output/main_coverage_report.html \
  --function create_item \
  --function update_item \
  --diagram-dir output/files
```

Jest / TypeScript カバレッジレポートを生成する:

```bash
teaforge coverage generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest_coverage_report.html \
  --function createUser \
  --diagram-dir output/files
```

補足:

- カバレッジレポートはテスト対象ソースファイル単位で生成されます。サマリーページにはすべての関数が含まれますが、`--function` で指定した関数だけが専用フローチャートページを持ちます。
- `_db_path` のような単純なヘルパー関数にはフローチャートは不要です。条件分岐やエラーパスを持つ実際の業務関数を優先してください。
- 要求された業務関数については、対応する Mermaid の `.mmd` ファイルが事前に用意されている必要があります。存在しない場合、CLI は先に `teaforge mermaid generate` を呼ぶよう案内します。
- Mermaid の内容には、`if/else`、バリデーション失敗、例外返却パス、主要な業務分岐を含めるべきです。意味のない「start -> call function -> end」のような図は生成しないでください。
- `teaforge mermaid validate` と `teaforge mermaid generate` は、実際の構文検証のためにローカルの `mmdc` を使用します。未導入の場合、TeaForge はインストールヒントを直接出力します。
- レポート生成時、TeaForge は Mermaid を SVG にレンダリングし、自己完結型の画像として HTML に埋め込みます。これにより、生の Mermaid SVG スタイルがページ CSS エラーと誤認される問題を避けます。
- Mermaid から SVG への変換はローカルの `mmdc` に依存し、`npm install -g @mermaid-js/mermaid-cli` でインストールできます。
- `jest` カバレッジは現在、Istanbul 形式の `coverage-final.json` を読み込み、テストファイルが実際の業務ソースファイルへ対応付けられていることを必要とします。TeaForge がソースを証明できない場合は即時に失敗します。
- `jest` のソース関数解析は現在、トップレベル関数、アロー関数、クラスメソッドを対象にしています。
- コマンドが失敗した場合、TeaForge は `mmdc` 不足、Mermaid ファイル不足、ソースファイル未解決、不正な framework パラメータなど、実行可能な修正ヒントを返すようにしています。これらのメッセージはエージェントが読み取り、次の呼び出しを修正することを想定しています。