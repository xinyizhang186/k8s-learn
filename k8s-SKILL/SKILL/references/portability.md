# 可迁移设计

## 约束

- 仅要求 Python 3.10+ 标准库。
- 命令示例使用 `python`；仅提供 `python3` 的宿主替换启动器即可，不修改脚本或 Skill 内容。
- 所有命令以 Skill 根目录为当前目录，或显式使用脚本路径。
- 运行数据写入用户指定的 `<run-dir>`，最终使用标准库脚本打包到 `<output-dir>`，不写 Agent 私有目录。
- 不引用 Codex、Claude、OpenCode、MCP、浏览器插件或产品专属 Agent 类型。
- 联网研究能力由宿主 Agent 提供；文件格式和字段契约保持不变。
- 生成流程不依赖当前仓库、已有 XLSX 或人工样表；人工样表仅用于离线评估与回归，不作为事实来源。

## 跨产品使用

复制整个 `SKILL/` 文件夹并保持内部相对路径。不要只复制 `SKILL.md`，也不要把宿主产品的安装路径写回 Skill。宿主产品只需能：

1. 读取 `SKILL.md`；
2. 运行 Python；
3. 打开网页或下载 URL；
4. 读写 JSON、Markdown、Go 源码和 XLSX 文件。

如果宿主支持 Skill 搜索目录，把整个文件夹放入该目录；否则在任务中指定 Skill 文件夹并让 Agent 读取 `SKILL.md`。所有命令从 Skill 根目录执行，脚本接口和运行目录契约无需修改。

首次复制后运行 `python scripts/validate_skill.py .` 和 `python scripts/self_test.py`。这只是迁移校验，不是每次生成报告都要执行的步骤。

## Token 节约

- 主文件只保留流程和停止条件，专业细节按需读取。
- 按 `SKILL.md` 的阶段路由读取 references，不在开始时预加载全部资料。
- 原网页落盘后只把相关章节摘要放进上下文。
- `machine-facts.json` 由脚本生成，避免模型重复解析 Go。
- 验证输出问题 ID 和字段名，下一轮只加载失败项。
- XLSX 由脚本构建，Agent 不需要在上下文中维护样式代码。
