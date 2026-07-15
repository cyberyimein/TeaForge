# TeaForge

[![CI](https://github.com/cyberyimein/TeaForge/actions/workflows/ci.yml/badge.svg)](https://github.com/cyberyimein/TeaForge/actions/workflows/ci.yml)

TeaForge turns automated tests into auditable Japanese-style unit-test specifications (PCL, Program Check List) and file-level coverage reports with Mermaid flowcharts and sequence diagrams.

It is designed for both engineers and coding agents. The bundled [`skill/SKILL.md`](skill/SKILL.md) describes the supported workflows, command boundaries, and diagram rules so an agent can invoke TeaForge consistently.

## Capabilities

- Parse `pytest`, Jest/TypeScript, Angular/Jest, and Playwright tests into PCL documents.
- Capture observed Jest matcher evidence: expected value, actual value, matcher, pass/fail, `.not`, Promise, and thrown-error behavior.
- Generate versioned PCL artifacts as sibling JSON and HTML files.
- Measure file-level C0/C1 coverage from Python coverage data or Jest/Istanbul `coverage-final.json`.
- Add typed Mermaid flowchart and sequence-diagram pages to coverage reports.
- Export generated HTML to PDF with the optional WeasyPrint dependency.
- Inspect the installed package and target project with a machine-readable `doctor` command.

## Installation

TeaForge requires Python 3.11 or newer.

### Use from a checkout

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

Install PDF support only when it is needed:

```bash
python -m pip install ".[pdf]"
```

For development and the repository demos:

```bash
python -m pip install -e ".[dev,pdf]"
```

Confirm the installed CLI and packaged resources:

```bash
teaforge --version
teaforge doctor --framework pytest --path demo/fastapi_crud/tests
```

## External tools

### Jest

Jest runtime evidence and Jest coverage require `node` and an already-installed project-local Jest. TeaForge discovers the nearest `node_modules/.bin/jest`, including a Jest hoisted above a workspace package, runs it from the target project root, and passes exact test paths.

TeaForge never invokes `npx` and never downloads Jest implicitly. Install the target project's locked dependencies first, for example:

```bash
npm ci
teaforge doctor --framework jest --path tests/user.test.js --json
```

### Mermaid

Syntax validation and SVG rendering require `mmdc`:

```bash
npm install -g @mermaid-js/mermaid-cli
teaforge doctor --framework pytest --require-mermaid
```

Environments that require explicit Chromium launch settings may point `TEAFORGE_MERMAID_PUPPETEER_CONFIG` to an `mmdc` Puppeteer JSON file. The repository uses `--no-sandbox` only inside its isolated CI runner; do not copy that setting into a general-purpose workstation.

### PDF

PDF export uses the optional `weasyprint` package and its native Pango/Cairo dependencies. Run this check before depending on PDF output:

```bash
teaforge doctor --framework pytest --require-pdf
```

On macOS, `brew install weasyprint` is the simplest way to install native dependencies. On Windows, follow the WeasyPrint/MSYS2 instructions and make the Pango DLL directory available through `WEASYPRINT_DLL_DIRECTORIES`.

## Quick start

### Generate a pytest PCL

```bash
teaforge pcl generate \
  --path demo/fastapi_crud/tests \
  --output output/pcl.html
```

TeaForge groups test cases by proven test subject. It emits one HTML/JSON pair per subject, reserves 25 matrix columns per sheet, and splits larger groups into numbered sheets. Every JSON artifact contains a `schema_version` field.

### Generate a runtime-backed Jest PCL

```bash
teaforge pcl generate \
  --framework jest \
  --evidence-mode runtime \
  --path demo/jest_runtime/tests/user.test.js \
  --output output/jest-pcl.html
```

Evidence modes:

- `static`: parse design-time expectations without executing Jest.
- `runtime`: require Jest and record observed matcher evidence.
- `auto`: try runtime evidence and fall back only when the project-local runner or assertion hook is unavailable. Timeouts and Jest configuration/execution errors remain failures instead of being hidden by a static report.

If Jest executes and tests fail, TeaForge still writes the evidence-bearing report and exits with code `2`. Use `--allow-test-failures` only when that result is intentionally acceptable. `--runtime-timeout` bounds the whole execution; on expiry TeaForge terminates the runner process tree and preserves only bounded diagnostics.

The structural parser uses TeaForge-packaged Tree-sitter JavaScript, TypeScript, and TSX grammars. It supports common `test`/`it` forms, nested `describe`, array-literal `test.each`/`describe.each`, ESM relative imports, CommonJS destructured/aliased/namespace `require`, direct calls, and common matchers. It never installs anything into the target project. Dynamic imports, computed test construction, and runtime-built values may still require runtime evidence.

### Query and export a PCL

```bash
teaforge get --path output/pcl.json --testcase TC-001
teaforge export --path output/pcl.html --output output/pcl.pdf
```

### Prepare diagrams

Flowchart:

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

Sequence diagram:

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

`mermaid generate` validates and stores the typed `.mmd` source. Unsupported diagram types fail instead of being mislabeled.

### Generate coverage reports

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

When the tested project uses a different virtual environment, run coverage with that environment's interpreter:

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

Coverage reports are grouped by proven business source file. TeaForge fails fast when it cannot map a Jest test to a real source file. `--function` adds a flowchart page and `--sequence` adds a sequence page; both options are repeatable and may target the same function. A metric with no measurable statements or branches is shown as `N/A` and is excluded from that metric's threshold gate.

## CLI help and exit behavior

```bash
teaforge help
teaforge help pcl generate
teaforge help coverage generate
```

- Exit `0`: command completed and its required result is acceptable.
- Exit `1`: invalid input, missing capability, execution failure, or generation failure.
- Exit `2`: Jest ran, reports were written, but at least one test failed.
- Exit `3`: coverage reports were written, but `--min-c0` or `--min-c1` was not met.

Writes use same-directory temporary files and atomic replacement so an interrupted single-file write does not destroy the previous artifact. Multi-file generation validates and renders all documents before replacement, but concurrent writers to the same output path are not supported.

## Project layout

```text
TeaForge/
  src/teaforge/            # CLI and service modules
  src/teaforge/templates/  # Packaged PCL and coverage templates
  src/teaforge/jest/assets # Packaged runtime listener
  demo/fastapi_crud/       # Executable pytest demo
  demo/jest_runtime/       # Locked executable Jest demo
  tests/                   # Unit and CLI integration tests
  docs/adr/                # Durable architecture decisions
  CHANGELOG.md             # Release-level behavior changes
  skill/SKILL.md           # Agent-facing workflow instructions
  .github/workflows/ci.yml # Tests, package checks, and real Jest smoke tests
```

The shared domain language is documented in [`CONTEXT.md`](CONTEXT.md). Execution and artifact decisions are recorded in [`docs/adr/`](docs/adr/).

## Development and release checks

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

Recreate `.venv` after copying the repository to another computer; virtual environments contain machine-specific interpreter paths and should not be moved with the source tree.

CI runs Python 3.11 and 3.14 on Linux plus Python 3.12 on Windows, enforces Ruff and an 80% branch-coverage baseline, builds wheel/sdist packages, runs real pytest coverage from an isolated wheel install, and executes the locked Jest demo on Node 20 and 22 from outside the project directory.

## Known boundaries

- JavaScript/TypeScript source discovery is structural and ignores import/test-shaped text in comments and strings. It is not a TypeScript type checker and does not evaluate dynamic or heavily transformed suites; those suites should use runtime evidence and verify the resolved source identity.
- Directory discovery prunes generated dependency and environment trees such as `node_modules`, `.venv`, `dist`, and `build`; pass an exact file path when one of those trees is intentionally the test subject.
- Runtime assertion evidence applies default sensitive-key and common credential-pattern redaction, value truncation, and bounded record/file limits. Projects with stricter confidentiality requirements must still review whether that default policy is sufficient before retaining reports.
- C0/C1 values retain their evidence provider and metric definitions in the artifact. Optional `--min-c0` and `--min-c1` gates apply to every generated source-file report.
- Mermaid and PDF are explicit optional capabilities and are checked independently by `teaforge doctor`.

These boundaries are kept explicit so automation can fail safely instead of silently producing a plausible but incorrect report.
