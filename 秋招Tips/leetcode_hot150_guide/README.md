# LeetCode Hot 150 — 模式学习指南（Python）

一份以模式为主线的 Hot 150 题单复习伴侣。你已经刷过一遍题，本指南将 **重复出现的套路**、**如何识别它**、**如何思考它**、**如何在 Python 中写出干净的代码** 全部整合在一起。

## 本指南的组织方式

文件按类别编号，与官方 LeetCode Hot 150 的分类一致。有四个类别获得 **深入** 讲解，因为你认为这些是你的薄弱点：

- `06_binary_tree.md` — 递归心智模型、遍历模板、序列化
- `09_graph.md` — BFS/DFS、并查集、拓扑排序、最短路径、网络流
- `12_dynamic_programming.md` — 完整的 DP 分类法 + 状态设计模板
- `18_strings_advanced.md` — KMP、Rabin-Karp、Z 函数、Manacher、基于 Trie 的字符串技巧

其余类别提供紧凑的模式速查。

## 文件索引

| # | 文件 | 主题 | 深度 |
|---|------|-------|-------|
| 00 | `00_study_methodology.md` | 如何思考、如何练习、面试模拟 | 标准 |
| 01 | `01_arrays_and_hashing.md` | 哈希表、前缀和、计数 | 标准 |
| 02 | `02_two_pointers.md` | 对撞 / 快慢 / 有序数组双指针 | 标准 |
| 03 | `03_sliding_window.md` | 定长 & 变长窗口、单调队列 | 标准 |
| 04 | `04_stack.md` | 单调栈、表达式求值、最小栈 | 标准 |
| 05 | `05_linked_list.md` | 虚拟头节点、慢/快指针、反转、合并 | 标准 |
| 06 | `06_binary_tree.md` | **递归模型、遍历、LCA、路径、序列化** | **深入** |
| 07 | `07_binary_search_tree.md` | BST 操作、中序遍历、LCA、范围和 | 标准 |
| 08 | `08_heap_priority_queue.md` | Top-K、合并多个有序流、懒删除 | 标准 |
| 09 | `09_graph.md` | **BFS/DFS、并查集、拓扑、最短路径、网络流** | **深入** |
| 10 | `10_binary_search.md` | 答案二分、bisect 模板 | 标准 |
| 11 | `11_backtracking.md` | 排列、组合、子集、棋盘搜索 | 标准 |
| 12 | `12_dynamic_programming.md` | **完整 DP 分类法 + 状态设计** | **深入** |
| 13 | `13_bit_manipulation.md` | XOR 技巧、位运算 DP、掩码 | 标准 |
| 14 | `14_trie.md` | 插入/搜索、自动补全、异或配对 | 标准 |
| 15 | `15_intervals.md` | 区间合并、插入、会议室、扫描线 | 标准 |
| 16 | `16_math_and_geometry.md` | GCD/LCM、素数、向量叉乘、旋转 | 标准 |
| 17 | `17_matrix.md` | 螺旋、旋转、置零、网格 BFS | 标准 |
| 18 | `18_strings_advanced.md` | **KMP、Rabin-Karp、Z 函数、Manacher、后缀技巧** | **深入** |

## 推荐阅读顺序

1. **第一遍（重建心智模型）：** `00` → `01..05` → `06` → `12` → `09` → `18`。这些文件确立了你后面所有内容都将使用的语言。
2. **针对薄弱项强化：** 把大部分复习时间花在 `06`、`09`、`12`、`18` 上。每篇深入讲解的文件末尾都附有 **练习清单**，将 Hot 150 的每道题映射到具体模式。
3. **模式扫荡：** 快速浏览 `02`、`03`、`04`、`10`、`11`，这些文件较短，能强化在 DP / 图 / 字符串题目里反复出现的模式。

## 全书统一的 Python 编码规范

- 全程使用类型提示（`List[int]`、`Optional[TreeNode]`）。
- 在树/链表代码中使用 `from __future__ import annotations` 以支持前向引用。
- 使用 `collections.deque`、`heapq`、`itertools`、`functools.lru_cache`、`bisect`。
- 不写 `as any`，不写 `# type: ignore`。代码必须能通过 `mypy --strict` 的类型检查。
- 在可能出现 `RecursionError` 的图/树题目中，递归上限要显式调高：`sys.setrecursionlimit(10**6)`。

## 如何使用每个文件

每个主题文件都采用统一的五段式结构：

1. **核心概念（Core concepts）** — 数据结构/技术的本质是什么。
2. **模式与模板（Patterns & templates）** — 可直接复制粘贴的起始代码，附注释。
3. **识别信号（Identification signals）** — 题面中暗示该模式的关键词。
4. **思考框架（Thinking framework）** — 面对新题时的逐步分析方法。
5. **Hot 150 例题（Hot 150 examples）** — 用上述模板讲解的代表性题目，以及易错点。

深入讲解的文件额外包含：

6. **常见失败模式（Common failure modes）** — 大多数候选人浪费时间的地方。
7. **练习清单（Drill list）** — 该类别下 Hot 150 所有题目按子模式分组，并按难度从易到难排列。

---

祝你好运。重新推导优于死记硬背——在看解答之前，尝试冷启动做完练习题。