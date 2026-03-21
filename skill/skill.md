# TeaForge Skill (Draft)

## Purpose

TeaForge 提供 CLI 能力，把 pytest 自动化测试转成可阅读、可导出、可查询的 PCL 文档，并生成带 Mermaid 流程图的覆盖率报告。

## CLI

- `teaforge pcl generate --path <pytest path> --output <html path>`
- `teaforge export --path <html path> --output <pdf path>`
- `teaforge get --path <json|html path> --testcase <code|name>`
- `teaforge mermaid validate --code <mermaid>`
- `teaforge mermaid generate --source <source file> --function <function> --code <mermaid> --output-dir <dir>`
- `teaforge coverage generate --path <pytest path> --output <html path> --function <business function> --diagram-dir <dir>`

## Guidance for AI

- 不要给所有函数都生成流程图；优先为真正的业务函数生成，例如控制器、服务层、包含条件分支/异常路径的核心函数。
- 像 `_db_path`、简单 getter、薄封装 helper 一般不需要流程图，除非它们本身包含重要业务判断。
- Mermaid 图不要只写“Start -> Run function -> End”；至少应体现 `if/else`、参数校验失败、异常返回、主成功路径等关键分支。
- 生成覆盖率报告时，只把需要展示流程图的业务函数通过 `--function` 传给 `teaforge coverage generate`。
