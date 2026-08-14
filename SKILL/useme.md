# 直接输入

在包含 `SKILL` 文件夹的目录中，直接向 Agent 输入：

```text
请读取 ./SKILL/SKILL.md，生成 Kubernetes v1.35-v1.36 的“版本分析/特性变更”双 Sheet XLSX，输出到 ./output/k8s-v1.34-v1.34.xlsx。
```

# 修改版本

生成其他版本时只需替换三处：起始版本、目标版本、输出文件名。

```text
请读取 ./SKILL/SKILL.md，生成 Kubernetes v<起始版本>-v<目标版本> 的“版本分析/特性变更”双 Sheet XLSX，输出到 ./output/k8s-v<起始版本>-v<目标版本>.xlsx。
```

预发布版本才需额外写明固定 ref，例如：`目标版本 ref=v1.37.0-beta.0`。其余证据、写作、验证和清理规则由 `SKILL.md` 自动处理，无需重复输入。
