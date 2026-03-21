# TeaForge

TeaForge converts automated tests into Japanese-style unit test documentation (PCL, Program Check List) and generates coverage reports with Mermaid flowcharts.

This project is not just a command-line tool for manual human use. Its primary use case is collaboration with AI agents. The `skill/SKILL.md` file provides agents with TeaForge knowledge such as capabilities, CLI interfaces, usage boundaries, and flowchart generation rules. Agents such as GitHub Copilot and Claude Code can load that skill to learn when TeaForge should be called, which arguments should be passed, and how to correct a failed invocation. That makes test generation, documentation generation, and coverage reporting more reliable.

Currently implemented:

- `pytest` test parsing
- `jest` / `TypeScript` test parsing
- PCL generation as `JSON + HTML`
- HTML export to PDF (`WeasyPrint`)
- CLI lookup for individual testcase descriptions
- File-level multi-page coverage reports (C0 / C1 + Mermaid SVG)

## Directory Structure

```text
TeaForge/
  src/teaforge/            # Core implementation and CLI
  templates/               # PCL HTML templates
  demo/fastapi_crud/       # Internal FastAPI + SQLite + pytest demo
  tests/fixtures/jest_sample/ # Minimal Jest / TypeScript fixture
  output/                  # Local HTML / JSON / PDF output directory
  tests/                   # TeaForge's own test suite
  skill/                   # Skill file
  project.md               # Project goal description
  Step1.md                 # Phase 1 requirements
```

## Installation

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

## Node / Jest Prerequisites

If you want to use the `jest` / `TypeScript` PCL or coverage features, you also need a local Node.js environment.

### Required Tools

- `node`
- `npx`
- A project-local `jest` executable

### Coverage Requirements

`teaforge coverage generate --framework jest` depends on Jest producing Istanbul `coverage-final.json`.

TeaForge currently invokes:

```bash
npx jest --coverage --coverageReporters=json --coverageDirectory <temp-dir> --runInBand <test-path>
```

### Mermaid Requirements

Whether you generate coverage reports from `pytest` or `jest`, Mermaid flowcharts still require a local `mmdc` installation:

```bash
npm install -g @mermaid-js/mermaid-cli
```

## PDF Export Dependencies (WeasyPrint)

TeaForge HTML generation only depends on Python packages. PDF export additionally depends on WeasyPrint system libraries.  
If `teaforge export` reports missing `libgobject`, `Pango`, `Cairo`, or missing DLL / shared libraries, install the required packages for your platform.

### macOS

According to the official WeasyPrint documentation, the simplest approach is to install WeasyPrint and its dependencies with Homebrew first:

```bash
brew install weasyprint
```

If you still run TeaForge inside the project's virtual environment, keep this step as well:

```bash
source .venv/bin/activate
pip install -e ".[dev,pdf]"
```

If shared libraries are still missing, you can set:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

The default prefix is usually `/opt/homebrew` on Apple Silicon and `/usr/local` on Intel Macs.

### Windows

TeaForge may also run on Windows. For PDF export you need to install Pango and its dependencies in advance.  
Based on the official WeasyPrint documentation, the recommended flow is:

1. Install Python.
2. Install [MSYS2](https://www.msys2.org/).
3. Run this in the MSYS2 shell:

```bash
pacman -S mingw-w64-x86_64-pango
```

4. Go back to PowerShell or `cmd` and install the project:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,pdf]"
```

If DLLs are still missing, set this in the current terminal:

```powershell
$env:WEASYPRINT_DLL_DIRECTORIES="C:\msys64\mingw64\bin"
```

The equivalent in `cmd.exe` is:

```cmd
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
```

### Export Command Example

```bash
teaforge export --path output/test_items/demo-pcl-test-create-item-normal.html --output output/test_items/demo-pcl-test-create-item-normal.pdf
```

## CLI Usage

TeaForge's primary CLI user is an agent, not a human terminal user. That means the design goal is not “what is the shortest command a human can type”, but rather:

- Can the agent understand parameters and constraints from `help` output?
- Can the agent get a clear correction path from failure messages?
- Can the agent chain together the PCL / coverage / Mermaid workflows automatically?

For that reason, TeaForge CLI tries to provide readable help, explicit error messages, and actionable correction hints when dependencies or inputs are missing. That feedback is meant to be consumed by agents so they can retry with corrected parameters.

TeaForge currently selects the test framework through `--framework`:

- `pytest`: default
- `jest`: for Node.js / TypeScript Jest tests

Generate PCL:

```bash
teaforge pcl generate --path demo/fastapi_crud/tests --output output/pcl.html
```

Notes:

- By default, TeaForge generates one PCL file per tested function. Multiple testcases targeting the same function are merged into the same PCL.
- In the generated PCL, `file` and `method` prefer the actual tested source file and implementation function. In the demo this becomes `main.py` / `create_item`.
- The matrix always reserves 25 testcase columns.
- If one function has more than 25 testcases, TeaForge automatically splits them into multiple sheet files.
- If the input path contains multiple tested functions, TeaForge creates subdirectories by tested file name and writes each function's HTML/JSON there.

Generate Jest / TypeScript PCL:

```bash
teaforge pcl generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest-pcl.html
```

Main Jest syntax currently supported:

- `test(...)`
- `it(...)`
- `test.only(...)` / `it.only(...)`
- `test.each([...])(...)`
- Relative-path `import`
- Direct imported function calls
- `expect(...).toBe(...)`
- `expect(...).toEqual(...)`
- `expect(...).toStrictEqual(...)`
- `expect(...).toContain(...)`
- `expect(() => fn(...)).toThrow(...)`

Current Jest limitations:

- Relative `TypeScript` / `JavaScript` imports are the primary supported path.
- `test.each` currently supports array-literal row data.
- Not all Jest / ts-jest / Babel syntax variants are covered yet.
- There is not yet a full Node.js demo project. Validation currently relies mainly on `tests/fixtures/jest_sample`.

Export PDF:

```bash
teaforge export --path output/pcl.html --output output/pcl.pdf
```

Query a testcase:

```bash
teaforge get --path output/pcl.html --testcase TC-001
```

Notes:

- `generate` also writes a sibling `.json` file for each HTML file.
- `get` prefers JSON. If you pass HTML with embedded data, it can read that directly as well.
- Agents can read command descriptions with `teaforge help`, `teaforge help pcl generate`, and `teaforge help coverage generate`, then adjust parameters based on error feedback.

Validate Mermaid:

```bash
teaforge mermaid validate --code "flowchart TD
  A[Start] --> B[End]"
```

Generate a function-level Mermaid file:

```bash
teaforge mermaid generate \
  --source demo/fastapi_crud/app/main.py \
  --function create_item \
  --code "flowchart TD
    A[Start] --> B[Create item]
    B --> C[Return response]" \
  --output-dir output/files
```

Generate a coverage report:

```bash
teaforge coverage generate \
  --path demo/fastapi_crud/tests \
  --output output/main_coverage_report.html \
  --function create_item \
  --function update_item \
  --diagram-dir output/files
```

Generate a Jest / TypeScript coverage report:

```bash
teaforge coverage generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest_coverage_report.html \
  --function createUser \
  --diagram-dir output/files
```

Notes:

- Coverage reports are generated per tested source file. The summary page includes all functions, but only functions specified with `--function` get dedicated flowchart pages.
- You do not need flowcharts for simple helper functions such as `_db_path`. Prefer real business functions with conditions or error paths.
- Requested business functions must already have Mermaid `.mmd` files prepared. If they are missing, the CLI tells you to call `teaforge mermaid generate` first.
- Mermaid content should show `if/else`, validation failure, exception return paths, and major business branches. Do not generate meaningless “start -> call function -> end” diagrams.
- `teaforge mermaid validate` and `teaforge mermaid generate` use local `mmdc` for real syntax validation. If it is missing, TeaForge prints the installation hint directly.
- When generating reports, TeaForge renders Mermaid to SVG and embeds it as a self-contained image in HTML. This avoids editor-side confusion where raw Mermaid SVG styles may be mistaken for page CSS errors.
- Mermaid-to-SVG conversion depends on local `mmdc`, which you can install with `npm install -g @mermaid-js/mermaid-cli`.
- `jest` coverage currently reads Istanbul `coverage-final.json` and requires the test file to be mapped to a real business source file. If TeaForge cannot prove the source, it fails fast.
- `jest` source function parsing currently covers top-level functions, arrow functions, and class methods.
- When a command fails, TeaForge tries to return actionable correction hints, such as missing `mmdc`, missing Mermaid files, unresolved source files, or an invalid framework parameter. Those messages are expected to be read by an agent and used to correct the next invocation.
