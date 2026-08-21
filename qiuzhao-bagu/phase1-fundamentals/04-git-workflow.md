# Git 工作流 - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / 大模型推理 / 框架集成方向）
> 使用方式：每节先记加粗结论。面试按"区域 → 提交流程 → 分支模型 → 历史 → 冲突"五段答。

---

## 一、Git 四区域与对象

### Q1. Git 的四大区域？
1. **工作区（Working Directory）**：磁盘上看到的文件，未 add。
2. **暂存区（Staging / Index）**：`git add` 后进入；下次 commit 的快照。
3. **本地仓库（Local Repository）**：`git commit` 后存入 `.git/objects`。
4. **远程仓库（Remote Repository）**：`git push` 后同步到 GitHub/GitLab。

### Q2. Git 对象模型四类？
| 对象 | 存什么 | 标识 |
|---|---|---|
| **blob** | 文件内容（不是文件名！） | sha1(content) |
| **tree** | 目录结构（文件名 + 模式 + blob/tree sha） | sha1(serialized) |
| **commit** | 指向根 tree + parent commit + author + message | sha1 |
| **tag**（annotated） | 指向某 commit + tag 信息 | sha1 |

**关键**：同名文件内容相同 → 同一 blob → 跨分支共享存储，节省空间。`.git/objects/` 是不可变对象库，所有命令本质是构造/读取对象图。

### Q3. 分支是什么？tag 是什么？
- 分支：**指向某 commit 的可变指针**（一个 41 字节的 ref 文件）。
- tag（轻量）：与分支相同，但通常不移动。
- tag（annotated）：独立的 tag 对象，包含 tagger/message + 指向 commit。
- HEAD：指向当前分支的"指针的指针"。

### Q4. `git config` 三级？
- `--system` `/etc/gitconfig`（最低优先级）
- `--global` `~/.gitconfig`（用户级，最常用）
- `--local` `.git/config`（仓库级，最高优先级）
- 必背：`user.name`/`user.email`、`pull.rebase`（默认 merge 还是 rebase）、`init.defaultBranch`、`core.autocrlf`。

---

## 二、日常提交

### Q5. add/commit/push 三步发生什么？
1. `git add file`：工作区 → 暂存区（index 写新条目）。
2. `git commit`：暂存区 → 本地仓库（创建 commit 对象，HEAD 前进）。
3. `git push origin branch`：本地仓库 → 远程仓库（更新 `refs/remotes/origin/branch`）。

### Q6. `git add -p`（partial add）用途？
- 交互式选择当前文件**部分 hunk** 加入暂存区。
- 适用：一个文件里有两类改动，想分两个 commit 提交。
- 流程：进入交互界面，`y` 接受、`n` 拒绝、`s` 拆更细、`q` 退出。

### Q7. `.gitignore` 生效与失效？
- 已被 git 跟踪的文件，加进 `.gitignore` **不会** 自动停止跟踪。
- 解决：`git rm --cached file`（保留工作区文件，只从 index 删）。
- `.gitignore` 空目录隐式忽略（git 只跟文件，不跟空目录）。
- 通配：`*.pyc`、`venv/`、`__pycache__/`、`/build/`（根目录限）。

### Q8. commit message 规范（Conventional Commits）？
```
<type>(<scope>): <subject>

<body>

<footer>
```
- type：`feat`/`fix`/`docs`/`refactor`/`perf`/`test`/`build`/`ci`/`chore`/`revert`。
- subject：祈使句、小写、≤50 字、结尾无句号。
- body：解释"为什么"而非"做了什么"。
- footer：`BREAKING CHANGE:` 或 `Closes #123`。
- 工具：commitlint + husky 强制。

---

## 三、分支与合并

### Q9. merge vs rebase 终极对比？
| 维度 | merge | rebase |
|---|---|---|
| 历史 | 保留分叉 + merge commit | 线性，原 commit 被重写 |
| commit sha | 不变 | **改变**（重写父链） |
| 冲突 | 一次 | 每次 commit 都可能冲突 |
| 适用 | 公共分支 | 私有分支（你的 feature 分支） |
| 风险 | 低 | **不要 rebase 已 push 的公共分支** |

**关键铁律**：**"绝不 rebase 已经被别人 fetch 走的 commit"**（否则历史发散，强制 push 会毁掉他人工作）。

### Q10. fast-forward merge vs --no-ff？
- 默认 fast-forward：目标分支指针直接前移到源分支 head，**无 merge commit**。
- `--no-ff`：强制创建 merge commit，保留"曾经存在分叉"的事实，便于追溯。
- `--squash`：把源分支多个 commit 压成一个新 commit 到目标分支，不保留分叉。

### Q11. cherry-pick 是什么？
- 把指定 commit "搬到"当前分支，**生成新 commit（sha 变）**。
- 适用：bugfix 在 feature 分支提交，需要同步到 main；release 分支打回 hotfix。
- 多个：`git cherry-pick A^..B`（不含 A，含 B）；`git cherry-pick A..B`（不含 A 不含 B？ 实际是开区间）。
- 冲突解决后 `git cherry-pick --continue` 或 `--abort`。

### Q12. 分支模型（GitFlow / GitHub Flow / Trunk-based）？
| 模型 | 长期分支 | 适合 |
|---|---|---|
| **GitFlow** | main/develop/feature/release/hotfix | 大型版本发布 |
| **GitHub Flow** | main + feature/PR | 持续部署 |
| **Trunk-based** | 只 main + 短期 feature branch | 高频 CI/CD、google 单仓库 |

- 现代云原生推荐 **Trunk-based + 短期 feature branch + feature flag**：所有改动都通过 PR 合 main，集成早，问题暴露快。

### Q13. PR vs MR？
- GitHub 叫 Pull Request；GitLab 叫 Merge Request。
- 语义相同：请求把 source branch 合并到 target branch，附带 diff、CI、review。
- squash merge：把多个 commit 压成一个，保留干净 main 历史。

---

## 四、历史与撤销

### Q14. `git reset` 三种模式？
| 模式 | HEAD 移动 | Index | 工作区 |
|---|---|---|---|
| `--soft` | 是 | 不变 | 不变（仅"撤回 commit"） |
| `--mixed`（默认） | 是 | 复位到 HEAD | 不变（撤回 commit + unstage） |
| `--hard` | 是 | 复位 | **复位**（丢弃所有改动，不可逆） |

- `--keep`：保留工作区已 commit 过的改动，撤销未提交。
- **危险**：`reset --hard` 会丢未提交工作；恢复需 `git reflog` 找回 HEAD 历史。

### Q15. `git revert` vs `git reset`？
- revert：**新建一个 commit** 来抵消指定 commit 的改动，历史保留。
- reset：移动 HEAD 指针，**重写历史**。
- 公共分支永远用 revert；私有分支可用 reset。

### Q16. `git reflog` 是什么？
- 记录 HEAD/分支的所有移动（commit/reset/checkout/pull 等都算）。
- 默认保留 90 天，是**找回"丢失" commit** 的最后手段。
- 流程：
  1. `git reflog` 找到旧 HEAD 位置，例如 `HEAD@{5}`。
  2. `git reset --hard HEAD@{5}` 或 `git cherry-pick <sha>`。

### Q17. `git stash` 用法？
- 暂存当前未提交改动，让工作区干净，便于切分支。
- `git stash push -m "wip"`（推荐带消息）。
- `git stash list` / `git stash apply`（保留 stash）/ `git stash pop`（应用并删）。
- 注意：stash 不是 commit，不要依赖它做长期备份；分支多 stash 易混乱。

### Q18. 修改最近一次 commit？
- 改 message：`git commit --amend -m "new msg"`。
- 加文件：`git add file && git commit --amend --no-edit`。
- **注意**：amend 会重写 commit sha，已 push 的不要 amend（除非 force push）。

### Q19. `git checkout` `git switch` `git restore` 区别？
- `git switch branch`（2.23+）：切分支专用，语义清晰。
- `git restore file`：撤销工作区改动（默认不动暂存区）。
- `git restore --staged file`：撤销 `git add`，把改动从 index 撤回工作区。
- `git checkout` 老牌命令，三种用途兼容，但易混淆 → 拆分新命令。

---

## 五、远程协作

### Q20. fetch / pull / push 流程？
- `git fetch`：拉远程 refs 更新到 `refs/remotes/origin/*`，**不动工作区**。
- `git pull` = `git fetch` + `git merge origin/branch`（或 rebase，看 `pull.rebase`）。
- `git push origin branch`：把本地 commit 推到远程，更新 `refs/heads/branch` on remote。
- `git push -u origin branch`：设置 upstream tracking，下次直接 `git push`/`git pull`。

### Q21. force push 与 `--force-with-lease`？
- `git push --force`：覆盖远程历史，**危险**，可能毁掉他人 PR。
- `git push --force-with-lease`：仅当远程分支没有新 commit（自我 fetch 后无变化）才允许强推，**安全推荐**。
- CI 误删 PR 分支：永远用 `--force-with-lease`。

### Q22. fork vs clone？
- clone：把仓库 copy 到本地，仍指向原 remote。
- fork：GitHub/GitLab 服务器端 copy 一份到自己账号下，**便于发起 PR**（无主仓写权限时）。
- fork 后 clone 自己的 fork，再 `git remote add upstream <原仓>`。

### Q23. Submodule vs Subtree？
| | Submodule | Subtree |
|---|---|---|
| 存储 | 子仓作为独立 .git 引用 | 子仓内容嵌入主仓历史 |
| clone | 需 `--recursive` | 自动 |
| 切换分支 | 子仓独立 | 主仓 commit 含子仓 snapshot |
| 改子仓 | 需进子仓 push 再主仓 commit | 直接在主仓改 |
| 适合 | 大型独立组件 | 共享代码、工具 |

### Q24. detached HEAD 状态？
- HEAD 直接指向某 commit 而非分支 → detached。
- 触发：`git checkout <sha>`、`git checkout origin/branch`。
- 此时新建 commit 不在任何分支上，**易丢失**（除非记下 sha 或 `git branch tmp <sha>`）。
- 退出：`git switch -` 或 `git branch tmp && git switch tmp`。

---

## 六、Diff 与日志

### Q25. `git diff` 各区域？
- `git diff`：工作区 vs 暂存区。
- `git diff --staged`（或 `--cached`）：暂存区 vs HEAD。
- `git diff HEAD`：工作区 vs HEAD（含暂存与未暂存）。
- `git diff branch1..branch2`：两分支差异。
- `git diff branch1...branch2`：自共同祖先以来 branch2 的改动（三点语义）。

### Q26. `git log` 高级用法？
```bash
git log --oneline --graph --all           # 一页看全分支拓扑
git log -p <file>                          # 看某文件每次改动 diff
git log -L 10,20:file.py                   # 看某文件第 10-20 行的演变
git log --author=zhangsan --since=2.weeks  # 按作者 + 时间过滤
git log --grep='fix' -i                    # 在 message 中搜索
git log --numstat                          # 增删行数统计
git log --format='%H %an %ad %s' --date=short  # 自定义格式
```

### Q27. `git blame` / `git bisect`？
- `git blame file`：看每行最后一次改的 commit + 作者。
- `git bisect start`：二分查找 bug 引入点。
  - 标好：`git bisect good <old>` / `git bisect bad <new>`。
  - git 自动 checkout 中间 commit，你测试 → `git bisect good/bad`。
  - 收敛后 `git bisect reset`。
- 比 `git log` 手动逐个 checkout 快 N 倍（O(log N)）。

### Q28. `git show` / `git cat-file`？
- `git show <sha>`：显示 commit 元数据 + diff（对 merge 默认只显示合并本身差异，加 -m 看 vs 各 parent）。
- `git show <sha>:<path>`：查看某 commit 时该文件内容。
- `git cat-file -p <sha>`：直接看对象内容（blob/tree/commit）。
- `git cat-file -t <sha>`：看对象类型。

---

## 七、Tag 与发布

### Q29. lightweight tag vs annotated tag？
- lightweight：仅 ref 指向 commit，无 tagger/message。
- annotated：独立 tag 对象，含 tagger/email/date/message + 可 GPG 签名。
- **正式发布永远用 annotated**：`git tag -a v1.0.0 -m "release 1.0.0"`。
- 推 tag：`git push origin v1.0.0` 或 `git push origin --tags`。
- 删除 tag：本地 `git tag -d v1.0.0`，远程 `git push origin :refs/tags/v1.0.0`。

### Q30. Semantic Versioning（SemVer）？
- 格式 `MAJOR.MINOR.PATCH`：
  - MAJOR：不兼容 API 变更。
  - MINOR：向下兼容的新功能。
  - PATCH：向下兼容的 bug 修复。
- 预发布：`1.0.0-alpha.1` / `1.0.0-rc.1`。
- 构建元数据：`1.0.0+20240101`。
- 模型版本常见：`qwen2.5-7b-instruct-v1.0`（自带产品 + 大版本 + 参数 + 微调版本）。

---

## 八、AI Infra 实战

### Q31. 大模型权重仓库典型结构？
```
qwen2.5-7b-instruct/
├── config.json               # 模型结构配置
├── generation_config.json
├── model-00001-of-00004.safetensors  # 分片权重（每个 ~5GB）
├── model-00002-of-00004.safetensors
├── model.safetensors.index.json     # 分片索引
├── tokenizer.json
├── tokenizer_config.json
└── README.md
```
- 分片原因：Git LFS 单文件限制、便于断点续传、并行下载。
- `safetensors` 取代 `pytorch_model.bin`：加载更快（mmap）、防任意代码执行（pickle 漏洞）。

### Q32. Git LFS（Large File Storage）？
- 大文件不进 git 对象库，只存指针 + 元数据，真实文件存 LFS server。
- `.gitattributes` 声明：`*.safetensors filter=lfs diff=lfs merge=lfs -text`。
- 拉取：`git lfs install && git lfs pull`。
- 坑：免费配额（GitHub 1GB / 1GB/月），大模型仓库常用 HF Hub / 自建 OSS。

### Q33. 大型推理框架的 PR 提交流程（以 vLLM 为例）？
1. Fork vllm-project/vllm 到个人 GitHub。
2. `git clone <my-fork>` + `git remote add upstream https://github.com/vllm-project/vllm`。
3. `git fetch upstream && git checkout -b feat/ascend-kernel upstream/main`。
4. 改代码 + 加测试（pytest）+ 加文档（docs/source/）。
5. `pre-commit install && pre-commit run --all-files`（ruff/black/mypy）。
6. `git commit -s -m "feat(ascend): add xxx kernel"`（**-s 加 DCO 签名**）。
7. `git push origin feat/ascend-kernel` → GitHub 开 PR。
8. CI 通过、reviewer 通过 → squash merge。

### Q34. DCO（Developer Certificate of Origin）是什么？
- 通过 `-s` 给 commit 加 `Signed-off-by: Name <email>` 行。
- 声明：作者有权提交该代码，且同意按开源协议贡献。
- Linux 内核、vLLM、PyTorch 等大型项目都要求 DCO。

### Q35. `git blame` 在大模型代码上找 bug 的常用流程？
1. 复现 bug 的 commit。
2. `git bisect start && git bisect bad HEAD && git bisect good v0.5.0`。
3. 让 bisect 自动切中间 commit，每次跑测试脚本判断好坏。
4. 收敛到具体 commit，看 `git show <sha>` 找根因。
5. 写一个最小复现 test，revert + 修。

### Q36. 多人改同文件的合并冲突解决？
- 冲突标记：
```
<<<<<<< HEAD
我方版本
=======
对方版本
>>>>>>> feature
```
- 流程：
  1. `git status` 看冲突文件。
  2. 编辑器/IDE 工具（VS Code/Meld）解决。
  3. `git add <file>` 标记已解决。
  4. `git commit`（merge）或 `git rebase --continue`（rebase）。
- 大型冲突建议：与冲突对方**当面/语音**讨论，不要盲选一边。

---

## 九、CI/CD 与 GitOps

### Q37. GitHub Actions 基本结构？
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
      with: { lfs: true }
    - uses: actions/setup-python@v5
      with: { python-version: '3.11' }
    - run: pip install -r requirements.txt
    - run: pytest tests/
```
- 三个核心概念：`workflow`（YAML 文件） / `job`（一组串行/并行的 step） / `step`（一个动作）。
- runner：GitHub-hosted 或 self-hosted（GPU 节点常用 self-hosted）。

### Q38. GitOps 是什么？
- 把"基础设施配置"存 Git，CI/CD 工具根据 Git 状态自动同步到集群。
- k8s 上代表：ArgoCD、Flux。
- 流程：开发者 push 部署 YAML → ArgoCD watch → 与集群 diff → sync apply。
- 好处：可审计、可回滚（git revert）、单一可信源。

### Q39. Trunk-based 与 feature flag 配合？
- Trunk-based 鼓励频繁 merge main，但未完成功能不便 merge → 用 feature flag。
- 代码 merge 到 main 但 runtime 通过 flag 关闭，待稳定后开放。
- 风险：flag 累积成技术债，需定期清理。

---

## 十、一页速记卡

| 类别 | 必背 |
|---|---|
| 四区 | 工作区/暂存/本地/远程 |
| 对象 | blob（内容）/tree（目录）/commit/tag；同名同内容共享 blob |
| 流程 | add→commit→push；fetch 不动工作区；pull=fetch+merge/rebase |
| reset | --soft/--mixed/--hard；公共分支用 revert 不用 reset |
| reflog | 找回"丢失"的 HEAD；保留 90 天 |
| merge/rebase | merge 保留分叉；rebase 重写历史；**勿 rebase 公共分支** |
| cherry-pick | 搬 commit 到当前分支，sha 变 |
| tag | annotated tag 含 tagger+msg；正式发布用；`-a -m` |
| SemVer | MAJOR.MINOR.PATCH；预发布 `1.0.0-rc.1` |
| 工作流 | GitFlow/Trunk-based；现代推荐 Trunk+短分支+PR |
| 大模型 | LFS/分片 safetensors；HF Hub；DCO `-s` |
| GitOps | 配置在 Git，ArgoCD/Flux sync 到 k8s |
