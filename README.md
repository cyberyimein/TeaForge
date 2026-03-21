# TeaForge

TeaForge 用于把自动化测试转换为日本式单元测试说明文档（PCL, Program Check List），并生成带 Mermaid 流程图的覆盖率报告。

当前已实现：

- `pytest` 测试解析
- `jest` / `TypeScript` 测试解析
- 生成 PCL `JSON + HTML`
- 将 HTML 导出为 PDF（`WeasyPrint`）
- 通过 CLI 查询单个测试用例说明
- 生成文件级、多页的覆盖率报告（C0 / C1 + Mermaid SVG）

## 目录结构

```text
TeaForge/
  src/teaforge/            # 核心实现与 CLI
  templates/               # PCL HTML 模板
  demo/fastapi_crud/       # 内部 FastAPI + SQLite + pytest 示例
  tests/fixtures/jest_sample/ # Jest / TypeScript 最小 fixture
  output/                  # 本地生成的 HTML / JSON / PDF 输出目录
  tests/                   # TeaForge 自身测试
  skill/                   # skill 文件
  project.md               # 项目目标说明
  Step1.md                 # 第一阶段需求
```

## 安装

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

## Node / Jest 前置条件

如果你要使用 `jest` / `TypeScript` 的 PCL 或覆盖率功能，还需要本地 Node.js 环境。

### 必需工具

- `node`
- `npx`
- 项目内可执行的 `jest`

### 覆盖率相关

`teaforge coverage generate --framework jest` 依赖 Jest 输出 Istanbul `coverage-final.json`。

TeaForge 当前会调用：

```bash
npx jest --coverage --coverageReporters=json --coverageDirectory <temp-dir> --runInBand <test-path>
```

### Mermaid 相关

无论是 `pytest` 还是 `jest` 覆盖率报告，只要要插入流程图，都仍然依赖本地 `mmdc`：

```bash
npm install -g @mermaid-js/mermaid-cli
```

## PDF 导出依赖（WeasyPrint）

TeaForge 的 HTML 生成功能只依赖 Python 包；PDF 导出额外依赖 WeasyPrint 的系统库。  
如果 `teaforge export` 报缺少 `libgobject`、`Pango`、`Cairo` 或 DLL/动态库找不到，请按对应系统补装。

### macOS

参考 WeasyPrint 官方文档，最简单的方式是先通过 Homebrew 安装 WeasyPrint 及其依赖：

```bash
brew install weasyprint
```

如果你仍然使用项目自己的虚拟环境来运行 TeaForge，保留下面这步即可：

```bash
source .venv/bin/activate
pip install -e ".[dev,pdf]"
```

如果仍提示找不到动态库，可设置：

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

Apple Silicon 默认前缀通常是 `/opt/homebrew`，Intel Mac 常见前缀是 `/usr/local`。

### Windows

TeaForge 很可能运行在 Windows 环境，PDF 导出时需要提前安装 Pango 及其依赖。  
根据 WeasyPrint 官方文档，推荐流程如下：

1. 安装 Python。
2. 安装 [MSYS2](https://www.msys2.org/)。
3. 在 MSYS2 shell 中执行：

```bash
pacman -S mingw-w64-x86_64-pango
```

4. 回到 PowerShell 或 `cmd`，安装项目：

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,pdf]"
```

如果仍提示找不到 DLL，可在当前终端设置：

```powershell
$env:WEASYPRINT_DLL_DIRECTORIES="C:\msys64\mingw64\bin"
```

在 `cmd.exe` 中对应写法为：

```cmd
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
```

### 导出命令示例

```bash
teaforge export --path output/test_items/demo-pcl-test-create-item-normal.html --output output/test_items/demo-pcl-test-create-item-normal.pdf
```

## CLI 用法

TeaForge 当前的测试框架入口是通过 `--framework` 选择：

- `pytest`：默认值
- `jest`：用于 Node.js / TypeScript Jest 测试

生成 PCL：

```bash
teaforge pcl generate --path demo/fastapi_crud/tests --output output/pcl.html
```

说明：

- 默认按“一个被测试函数一个 PCL 文件”生成；同一函数相关的多个测试用例会聚合到同一个 PCL
- PCL 中的 `file` / `method` 会优先显示被测试代码的文件与实现函数；例如 demo 会显示 `main.py` / `create_item`
- 判定表固定预留 25 个测试用例列
- 单个函数超过 25 个测试用例时，会自动拆分为多个 sheet 文件
- 当输入路径下存在多个被测试函数时，会按被测试文件名创建子目录，并在其中输出各函数的 HTML/JSON 文件

生成 Jest / TypeScript PCL：

```bash
teaforge pcl generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest-pcl.html
```

Jest 目前支持的主要语法范围：

- `test(...)`
- `it(...)`
- `test.only(...)` / `it.only(...)`
- `test.each([...])(...)`
- 相对路径 `import`
- 直接导入函数调用
- `expect(...).toBe(...)`
- `expect(...).toEqual(...)`
- `expect(...).toStrictEqual(...)`
- `expect(...).toContain(...)`
- `expect(() => fn(...)).toThrow(...)`

Jest 当前的已知边界：

- 优先支持 `TypeScript` / `JavaScript` 的相对路径 import
- `test.each` 当前支持数组字面量行数据
- 还没有覆盖所有 Jest / ts-jest / Babel 变体语法
- 还没有提供完整的 Node.js demo 项目，目前主要通过 `tests/fixtures/jest_sample` 验证

导出 PDF：

```bash
teaforge export --path output/pcl.html --output output/pcl.pdf
```

查询测试用例：

```bash
teaforge get --path output/pcl.html --testcase TC-001
```

说明：

- `generate` 会同时为每个 HTML 生成同名 `.json`
- `get` 会优先读 JSON；若传入 HTML 且存在内嵌数据，也能直接读取

验证 Mermaid：

```bash
teaforge mermaid validate --code "flowchart TD
  A[Start] --> B[End]"
```

生成函数级 Mermaid 文件：

```bash
teaforge mermaid generate \
  --source demo/fastapi_crud/app/main.py \
  --function create_item \
  --code "flowchart TD
    A[Start] --> B[Create item]
    B --> C[Return response]" \
  --output-dir output/files
```

生成覆盖率报告：

```bash
teaforge coverage generate \
  --path demo/fastapi_crud/tests \
  --output output/main_coverage_report.html \
  --function create_item \
  --function update_item \
  --diagram-dir output/files
```

生成 Jest / TypeScript 覆盖率报告：

```bash
teaforge coverage generate \
  --framework jest \
  --path tests/fixtures/test_sample_jest.test.ts \
  --output output/jest_coverage_report.html \
  --function createUser \
  --diagram-dir output/files
```

说明：

- 覆盖率报告按“被测文件”输出一份 HTML；摘要页覆盖全部函数，只有你通过 `--function` 指定的业务函数才会生成流程图详情页
- 不需要为 `_db_path` 之类的简单辅助函数绘制流程图；优先选择真正有业务价值、存在条件分支或错误路径的函数
- 被指定的业务函数需要先准备对应的 Mermaid `.mmd` 文件；若缺失，CLI 会提示先调用 `teaforge mermaid generate`
- Mermaid 内容应尽量画出 `if/else`、校验失败、异常返回、主要业务分支，而不是只画“开始 -> 调用函数 -> 结束”
- `teaforge mermaid validate` / `teaforge mermaid generate` 会使用本地 `mmdc` 做真实语法校验；若缺失会直接提示安装命令
- 生成报告时会把 Mermaid 渲染为 SVG，并以自包含图片的方式嵌入 HTML，避免编辑器把 Mermaid 生成的原始 SVG 样式误判为页面 CSS 错误
- Mermaid 转 SVG 依赖本地 `mmdc`，可通过 `npm install -g @mermaid-js/mermaid-cli` 安装
- `jest` 覆盖率当前读取 Istanbul `coverage-final.json`，并要求测试文件能被可靠映射到真实业务 source file；无法证明 source 时会直接失败
- `jest` source function 解析当前覆盖：顶层 function、arrow function、class method
