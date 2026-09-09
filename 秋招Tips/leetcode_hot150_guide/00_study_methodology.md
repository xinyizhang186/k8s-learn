# 00. 学习方法论 —— 如何思考、如何练习

你已经通关 Hot 150 一轮。接下来的飞跃来自 **模式识别速度** 和 **压力下干净利落的编码**，而不是刷更多的题。本文件给出本指南其他所有文件所默认的心智模型。

---

## 1. 四秒钟测试

读题时，你的第一要务 **不是** 解决它，而是对它进行分类。在四秒内，你应该有一个候选模式。示例信号表：

| 题面里的信号词 | 优先尝试的模式 |
|--------------------------|----------------------|
| "sorted"、"two-sum"、"triplet"、"palindrome pairs" | 双指针 / 哈希 |
| "longest subarray/substring with constraint"、"at most K distinct" | 滑动窗口 |
| "next greater/smaller"、"largest rectangle in histogram" | 单调栈 |
| "all paths"、"all combinations"、"all permutations"、"N-Queens" | 回溯 |
| "minimum/maximum of X over Y"、"is it possible to achieve K?" | 答案二分 |
| "from `s` to `t`"、"shortest path"、"fewest steps" | BFS / Dijkstra |
| "course schedule"、"dependency"、"task order" | 拓扑排序 |
| "connected components"、"are X and Y connected"、"redundant" | 并查集 |
| "max/min/count ways"、"longest common subsequence"、"knapsack" | 动态规划 |
| "top K"、"K-th largest/smallest"、"merge K sorted" | 堆 / 快选 |
| "inorder"、"BST"、"level order"、"LCA"、"diameter" | 二叉树递归 |
| "prefix matching"、"dictionary of words"、"word search II" | Trie |

如果在四秒内你无法触发一个模式，那对该题类你仍处于 **死记硬背** 阶段。不断练习该类别，直到信号词能瞬间触发模式。

## 2. 15 分钟时间预算

针对面试风格的练习：

- **0–3 分钟：** 仔细读题。明确输入/输出。用一个例子验证。触发模式（第 1 节）。
- **3–8 分钟：** 在纸上勾画算法。写出状态转移 / 数据结构。识别边界情况（空输入、单元素、重复元素、负数、溢出）。
- **8–25 分钟：** 编码。先写 **骨架**（函数签名、辅助函数、主循环），再填充细节。
- **25–30 分钟：** 用一个最小例子手动跑一遍。运行代码。修复问题。

如果 3 分钟后仍然没有候选模式，**只读题解的第一段**（分类提示部分），然后关闭它，重新尝试。克制住读完整篇题解的冲动。

## 3. 以模式为中心，而非以题目为中心

多数人按题目来组织练习（"我要刷第 200 题"）。这是错的。应该按模式来组织：

1. 选一个模式（例如单调栈）。
2. 集中做该模式的 **4–6 道题**，难度逐级递增。
3. 一组刷完后，写一份能覆盖 80% 变体的 **Python 模板**。归档保存。
4. 下次遇到同家族的题目时，先打开你的模板。

本指南的结构正是如此：每个文件末尾都附有按子模式分组的 **练习清单**，覆盖 Hot 150 对应题目。

## 4. 做题时真正应该如何思考

三句话，反复大声念出来（面试中）或在脑中默念（比赛中）：

1. **"为了回答位置 i 的问题，我需要追踪什么状态？"**
   这是 DP 的核心问题。它同样回答滑动窗口和大多数树的问题。
2. **"最小的子问题是什么？当我把它扩大一个单位时，答案如何组合？"**
   这是归纳步骤。如果你能把它写成递推式，你就得到了一个 DP。如果你能把它写成图上的边，你就得到了 BFS/DFS。
3. **"如果我有一个神谕能解决规模为 N-1 的问题，我该如何利用这个答案？"**
   这是递归的信仰之跃。它是树和分治问题中最有用的一句话。

## 5. 必须内化的 Python 工具箱

你应该能不查文档凭记忆写下这些代码：

```python
# Counter 和 defaultdict
from collections import Counter, defaultdict
cnt = Counter(nums)
cnt[x] += 1
del cnt[x]                                    # 完全删除该键
g = defaultdict(list); g[u].append(v)

# Deque 用于 O(1) 的 popleft
from collections import deque
q = deque([start]); q.popleft(); q.append(x)

# Heap —— 默认为最小堆；取最大堆要取负数
import heapq
heapq.heapify(a); heapq.heappush(a, x); heapq.heappop(a)
heapq.nsmallest(k, a)                          # 或者 nlargest

# bisect —— 在有序列表上做二分
import bisect
i = bisect.bisect_left(a, x)                   # 第一个 a[i] >= x 的下标
i = bisect.bisect_right(a, x)                  # 第一个 a[i] >  x 的下标

# functools.lru_cache —— 把递归变成带记忆化的 DP
from functools import lru_cache
@lru_cache(None)
def f(i, j): ...

# itertools —— 组合/排列/笛卡尔积
from itertools import combinations, permutations, product, accumulate
list(combinations(range(n), k))

# 整数位运算
x.bit_count()                                  # Python 3.10+：popcount
x.bit_length()                                # ceil(log2(x))
```

## 6. 面试中常见的 Python 陷阱

1. **`list.pop(0)` 是 O(n)。** 使用 `collections.deque.popleft()`。
2. **`x in list` 是 O(n)。** 用 `set` 做成员判断。
3. **`sorted(a, key=lambda x: ...)`** —— 多关键字排序时用元组 key：`key=lambda x: (x.start, -x.end)`。
4. **`functools.lru_cache` 在树递归上** —— 需要 `None` 参数，缓存以参数的元组为键，因此参数必须可哈希。
5. **可变默认参数：** `def f(acc=[]): ...` —— acc 在多次调用间共享。改为 `acc=None`，然后 `acc = [] if acc is None else acc`。
6. **在 10^5 节点的图上深度递归** —— Python 默认递归深度为 1000。要么 `sys.setrecursionlimit(10**6)`，要么改成迭代。
7. **`0.1 + 0.2 != 0.3`** —— 使用 `math.isclose` 或换算成整数。
8. **`heapq` 配合自定义比较** —— 存 `(priority_key, tiebreaker, item)`，让 tie 时按确定顺序排，且 `item` 不需要支持 `<`（字典就不支持）。

## 7. 如何在纸上验证你的解法

在跑代码之前，手动走一遍：

1. **空输入** —— `[]`、`""`、`None`、单节点。
2. **单元素** —— `[1]`、`"a"`、只有根节点。
3. **两个元素** —— 重复与非重复。
4. **一般情况** —— 长度混合奇偶、数字混合正负。
5. **题目特有的边界** —— 已经有序、逆序、全部重复、全部同号。

如果你的解法能处理以上五种情况，你就有大约 80% 的把握。剩下 20% 来自 `INT_MIN`、乘法溢出、答案空间二分的差一错误等极端边界。

## 8. 遗忘曲线

如果你不复盘，大约一周会忘掉某个模式的 60%。对抗方法：

1. 刷完一个分类后，3 天后冷启动重做 **2 道题**。
2. 两周后，冷启动重做该分类中 **最难的一道题**。
3. 维护一份 **错题日志**：每次踩坑时写一行笔记，每月回顾一次。

## 9. 模拟面试流程

把"给我足够的时间我能解出来"转化为"我能在 30 分钟内解出来"：

1. 随机抽一道 Hot 150 题。启动 30 分钟计时器。
2. 全程大声说出思路（或者以注释流的形式写下）。
3. 计时期间 **不能查题解、不能用 AI、不能看提示**。
4. 如果失败，把这道题标记为 **未完成**，回到本指南对应的文件重温，第二天再尝试。
5. 按分类统计成功率。薄弱的分类获得更多练习。

## 10. "完成"的含义

当且仅当你能做到下面五点时，一道题才是"完成"的：

1. 读题后 4 秒内识别模式。
2. 用一句话讲出递推式 / 算法。
3. 15 分钟内写出无 bug 的 Python 代码。
4. 解释时间与空间复杂度。
5. 列出一种替代方案并说明其权衡。

如果任何一项缺失，这道题就 **没有完成**。再做一遍。