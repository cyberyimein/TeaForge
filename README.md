# TeaForge

TeaForge 用于把 `pytest` 自动化测试转换为日本式单元测试说明文档（PCL, Program Check List）。

Step1 当前支持：

- `pytest` 测试解析
- 生成 PCL `JSON + HTML`
- 将 HTML 导出为 PDF（`WeasyPrint`）
- 通过 CLI 查询单个测试用例说明

## 目录结构

```text
TeaForge/
  src/teaforge/            # 核心实现与 CLI
  templates/               # PCL HTML 模板
  demo/fastapi_crud/       # 内部 FastAPI + SQLite + pytest 示例
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
