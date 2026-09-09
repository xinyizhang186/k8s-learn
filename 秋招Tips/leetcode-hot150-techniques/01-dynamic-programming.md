# 01 · 动态规划(DP)实战与避坑

> 你已经刷过一遍 Hot 150,但 DP"非常薄弱"。本文**不讲"什么是 DP"**,直接进入:识别信号 → 心智模型 → 子模式全家桶(每个带 Python 模板 + Hot 150 真题)→ 避坑 → 速记。
> 心法:**DP = 状态 + 转移 + 边界 + 答案位置。卡住 90% 是状态定义不清。**

---

## 一、识别信号

看到这些关键词 + 对应数据范围 → 大概率 DP:

| 关键词 | 数据范围 | 候选 DP 类型 |
|---|---|---|
| "最大/最小值"、"方案数"、"是否可行" | `n ≤ 20` | **状态压缩 DP** |
| 同上 | `n ≤ 250~500` | **区间 DP** |
| 同上 | `n ≤ 1000` | 二维 DP / `O(n²)` |
| 同上 | `n ≤ 1e5` | 一维 DP / 线性 / 单调优化 |
| "子序列"、"子数组" | 任意 | 序列 DP / LIS / LCS |
| "选/不选"、"前 i 个" | 任意 | 0/1 背包思想 |
| "无限次使用某物品" | 任意 | 完全背包 |
| "股票/买卖/冷却" | 任意 | **状态机 DP** |
| "树上的最大/方案数" | 任意 | **树形 DP**(见 04) |
| "数位/数字组合 ≤ N" | — | 数位 DP |

> ⚠️ 反向也成立:`n ≤ 20` 配上"最值/方案数",**几乎一定是状态压缩 DP**(TSP / 子集划分 / 847 访问所有节点)。

---

## 二、心智模型(为什么这么设计)

### 2.1 四要素

1. **状态 `f[...]`**:用若干维度刻画"原问题的子问题"。**状态定义必须自洽**:相同状态 → 相同答案。
2. **转移**:`f[i]` 由哪些更小的 `f[j]` 推出。
3. **边界**:`f[0]` / `f[1]` 等基础情况。
4. **答案位置**:`f[n]`?`max(f)`?`f[n-1][m-1]`?**容易算错。**

### 2.2 从暴力到 DP 的三步走(CRITICAL)

> 这是**学新题时**的标准动作,不要跳:

```
1. 写暴力递归 dfs(...)      ← 正确性基准,不管复杂度
2. 加 @lru_cache / 备忘录    ← 记忆化搜索 = 自顶向下 DP
3. 改成递推 f[...] = ...    ← 自底向上 DP,省递归栈
```

**为什么先写递归?** 因为递归只关心"我这一步怎么由子问题来",不用想计算顺序。状态定义错了,改递归比改循环容易得多。

### 2.3 "最后一步"思想

定义状态时,问自己:**"这个问题的最后一步决策是什么?"**

- 打家劫舍:最后一个房子"偷/不偷" → 状态 `f[i]` = 前 i 个的最大金额
- 0/1 背包:第 i 件物品"选/不选" → 状态 `f[i][j]` = 前 i 件、容量 j 的最值
- 编辑距离:`s1[i] == s2[j]` 还是增/删/改 → 状态 `f[i][j]` = 前 i 和前 j 的最小编辑距离

**最后一步清楚了,状态定义和转移就同时清楚了。**这是 DP 最值钱的一招。

---

## 三、子模式全家桶

每个子模式:**识别信号 → 模板 → 复杂度 → Hot 150 真题**。

### 3.1 一维 DP

**识别**:线性序列,每步只与前 1~2 步相关。

**模板 — 打家劫舍(198)**:
```python
def rob(nums):
    # f[i] = 前 i 个房子能偷的最大金额
    # 转移:f[i] = max(f[i-1], f[i-2] + nums[i-1])
    #       不偷 i-1      偷 i-1(则不能偷 i-2)
    if not nums: return 0
    if len(nums) == 1: return nums[0]
    prev2, prev1 = 0, nums[0]     # f[-1]=0, f[0]=nums[0]
    for i in range(2, len(nums) + 1):
        cur = max(prev1, prev2 + nums[i - 1])
        prev2, prev1 = prev1, cur
    return prev1
```
复杂度 `O(n)` / `O(1)`。

**Hot 150 真题**:
- 70 爬楼梯:`f[i] = f[i-1] + f[i-2]`(模板一致)
- 198 打家劫舍、213 打家劫舍 II(环 → 两次取 max)
- 91 解码方法:`f[i] = (f[i-1] if 1≤s[i-1]≤9) + (f[i-2] if 10≤s[i-2:i]≤26)`
  ⚠️ 边界:`f[0]=1`(空串算一种),前导 '0' 必须返回 0。

### 3.2 二维网格 DP

**识别**:在网格上从左上走到右下,求方案数或最小和。

**模板 — 不同路径 II(63)**:
```python
def uniquePathsWithObstacles(grid):
    m, n = len(grid), len(grid[0])
    f = [[0] * (n + 1) for _ in range(m + 1)]
    f[0][1] = 1                # 哨兵:让 f[1][1] 能从左/上得到 1
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if grid[i-1][j-1] == 1:
                f[i][j] = 0
            else:
                f[i][j] = f[i-1][j] + f[i][j-1]
    return f[m][n]
```
**Hot 150 真题**:62 不同路径、63 障碍物、64 最小路径和(`f[i][j] = min(f[i-1][j], f[i][j-1]) + grid[i][j]`)。

⚠️ **避坑**:开 `m+1` 行 `n+1` 列 + 哨兵,能省掉"第一行/第一列单独处理"的烦。这是网格 DP 的通用技巧。

### 3.3 背包家族(CRITICAL)

**0/1 背包**:每件物品最多选一次。
```python
def knapsack01(W, weights, values):
    # f[j] = 容量 j 的最大价值;滚动到 1 维
    f = [0] * (W + 1)
    for i in range(len(weights)):
        for j in range(W, weights[i] - 1, -1):   # 逆序!防同一物品被选多次
            f[j] = max(f[j], f[j - weights[i]] + values[i])
    return f[W]
```
⚠️ **0/1 背包内层必须逆序**,否则 `f[j]` 用到的 `f[j-w[i]]` 可能已经包含本轮的物品 i,变成"重复选"。

**完全背包**:每件物品无限次。
```python
def unbounded(W, weights, values):
    f = [0] * (W + 1)
    for i in range(len(weights)):
        for j in range(weights[i], W + 1):        # 顺序!允许重复选
            f[j] = max(f[j], f[j - weights[i]] + values[i])
    return f[W]
```
⚠️ **0/1 vs 完全的唯一区别就是内层循环方向**(逆序 vs 顺序)。这是面试高频追问点。

**Hot 150 真题**:
- 416 分割等和子集:总和 S,问能否选子集和为 S/2 → 0/1 背包"恰好装满"
- 322 零钱兑换:求最少硬币数 → 完全背包,`f[j] = min(f[j], f[j-c]+1)`
- 518 零钱兑换 II:求方案数 → 完全背包求"装满方案数",`f[j] += f[j-c]`
- 494 目标和:转化为"选子集和为 (sum+target)/2" → 0/1 背包方案数

### 3.4 区间 DP

**识别**:`n ≤ 250~500` + "合并/分割操作" + "两端/区间"。

**模板 — 戳气球(312)**:
```python
def maxCoins(nums):
    # 加哨兵 [1] + nums + [1],消除边界处理
    arr = [1] + nums + [1]
    n = len(arr)
    f = [[0] * n for _ in range(n)]
    # f[i][j] = 戳光开区间 (i, j) 内所有气球的最大收益
    # 枚举区间长度,从短到长(关键!)
    for length in range(2, n):           # 至少跨 1 个气球
        for i in range(n - length):
            j = i + length
            for k in range(i + 1, j):    # 最后戳 k
                f[i][j] = max(f[i][j],
                              arr[i] * arr[k] * arr[j] + f[i][k] + f[k][j])
    return f[0][n - 1]
```
复杂度 `O(n³)`。**区间 DP 通用三段**:`for length` → `for i, j=i+length` → `for k in (i, j)` 表示"最后一步在 k"。

**Hot 150 真题**:5 最长回文子串、312 戳气球、486 预测赢家、375 猜数字大小 II、1039 多边形三角剖分。

### 3.5 LIS / LCS 家族

**LIS O(n²)**:
```python
def lengthOfLIS_n2(nums):
    # f[i] = 以 nums[i] 结尾的最长上升子序列长度
    f = [1] * len(nums)
    for i in range(len(nums)):
        for j in range(i):
            if nums[j] < nums[i]:
                f[i] = max(f[i], f[j] + 1)
    return max(f, default=0)
```

**LIS O(n log n) — 贪心 + 二分**(面试必考的优化):
```python
from bisect import bisect_left
def lengthOfLIS(nums):
    tails = []              # tails[i] = 长度为 i+1 的所有 LIS 末尾元素的最小值
    for x in nums:
        pos = bisect_left(tails, x)   # 第一个 ≥ x 的位置
        if pos == len(tails):
            tails.append(x)           # x 能接长 LIS
        else:
            tails[pos] = x            # 替换,让以后更容易接长
    return len(tails)                 # 注意:tails 不一定是真实 LIS,但长度正确
```
**为什么对?** `tails` 单调不减,`tails[i]` 越小,后面越容易接。这是"贪心保留最优尾"思想。

**LCS(1143)**:
```python
def longestCommonSubsequence(s1, s2):
    m, n = len(s1), len(s2)
    f = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                f[i][j] = f[i-1][j-1] + 1
            else:
                f[i][j] = max(f[i-1][j], f[i][j-1])
    return f[m][n]
```

**编辑距离(72)** — LCS 的"加权版":
```python
def minDistance(s1, s2):
    m, n = len(s1), len(s2)
    f = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): f[i][0] = i    # 边界:删成空
    for j in range(n + 1): f[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                f[i][j] = f[i-1][j-1]
            else:
                f[i][j] = 1 + min(f[i-1][j],    # 删
                                   f[i][j-1],    # 增
                                   f[i-1][j-1])  # 改
    return f[m][n]
```

**Hot 150 真题**:300 LIS、1143 LCS、72 编辑距离、583 两个字符串的删除操作、718 最长重复子数组(连续版 LIS)。

### 3.6 状态机 DP — 买卖股票全家桶(CRITICAL)

**6 道股票题用统一状态机讲透**:

| 题 | 限制 | 状态设计 |
|---|---|---|
| 121 | 1 次交易 | `f[i][1]`(持有) / `f[i][0]`(空仓) |
| 122 | 无限次 | 同上 |
| 123 | 最多 2 次 | `f[i][k][0/1]`,k=0/1/2 |
| 188 | 最多 k 次 | `f[i][k][0/1]` |
| 309 | 无限次 + 冷却 | `f[i][0/1/2]`(2=冷却) |
| 714 | 无限次 + 手续费 | `f[i][0/1]` 卖时减 fee |

**通用转移**(以 188 为例):
```python
def maxProfit(k, prices):
    n = len(prices)
    if n < 2 or k == 0: return 0
    # 优化:k > n/2 时退化为无限次(同 122)
    if k > n // 2:
        # 122 题做法:贪心累加所有上升段
        return sum(max(prices[i] - prices[i-1], 0) for i in range(1, n))
    # f[i][j][h]: 第 i 天结束、已进行 j 次买入、当前持仓状态 h
    # 降维:f[j][h]
    buy = [-float('inf')] * (k + 1)     # buy[j] = 持仓、已买 j 次的最大现金
    sell = [0] * (k + 1)                # sell[j] = 空仓、已卖 j 次的最大现金
    for p in prices:
        for j in range(1, k + 1):
            # 注意用临时变量避免本轮互相污染(类似滚动数组逆序)
            buy[j] = max(buy[j], sell[j-1] - p)   # 继续持有 / 今天买入(消耗一次买)
            sell[j] = max(sell[j], buy[j] + p)   # 继续空仓 / 今天卖出
    return sell[k]
```

**为什么统一?** 所有股票题的核心都是"今天结束时的最大现金",区别只在"交易次数限制"和"附加约束(冷却/手续费)"。状态机一旦画对,代码就是套模板。

⚠️ **避坑**:`k > n//2` 时 3 维会 TLE/MLE,**必须退化为无限次**。

### 3.7 树形 DP(详见 04-binary-trees.md)

- 337 打家劫舍 III:`f(node) = max(偷本层=子层不偷, 不偷本层=子层可偷可不偷)`
- 124 二叉树最大路径和:后序返回"以该节点为端点的最大单链"

具体模板见 `04-binary-trees.md` 第 3 节。

### 3.8 状态压缩 DP

**识别**:`n ≤ 20` + "子集/排列/访问所有"。

**模板 — 访问所有节点的最短路径(847)**:
```python
from collections import deque
def shortestPathLength(graph):
    n = len(graph)
    target = (1 << n) - 1
    # 状态:(当前节点, 已访问集合 mask)
    dist = [[float('inf')] * (1 << n) for _ in range(n)]
    q = deque()
    for i in range(n):           # 起点任意,全入队(多源 BFS)
        dist[i][1 << i] = 0
        q.append((i, 1 << i))
    while q:
        u, mask = q.popleft()
        if mask == target:
            return dist[u][mask]
        for v in graph[u]:
            nmask = mask | (1 << v)
            if dist[v][nmask] > dist[u][mask] + 1:
                dist[v][nmask] = dist[u][mask] + 1
                q.append((v, nmask))
    return 0
```
复杂度 `O(n^2 · 2^n)`。**关键**:把"已访问集合"塞进状态 → `n ≤ 20` 才可行(`2^20 ≈ 1e6`)。

### 3.9 数位 DP(简述)

**识别**:求 `[1, N]` 中满足某条件的数的个数,`N ≤ 1e18`。

**通用框架**(记忆化):
```python
from functools import lru_cache
def countNumbers(s):           # s = str(N)
    @lru_cache(None)
    def dfs(pos, tight, prev_state):
        if pos == len(s):
            return 1            # 一个合法数走完
        limit = int(s[pos]) if tight else 9
        ans = 0
        for d in range(0, limit + 1):
            ans += dfs(pos + 1,
                      tight and d == limit,
                      update(prev_state, d))
        return ans
    return dfs(0, True, INIT)
```
关键参数:`tight`(是否顶到上界)、`prev_state`(题目相关,如"是否含 9""是否非递减"等)。

### 3.10 记忆化搜索 vs 递推

| 维度 | 记忆化(@lru_cache) | 递推(for) |
|---|---|---|
| 写法难度 | 易(只管当前) | 需想清楚顺序 |
| 状态压缩/多维 | 友好 | 多维循环繁琐 |
| 常数 | 大(递归+哈希) | 小(数组) |
| 子问题覆盖 | 用到才算 | 全部算一遍 |

**取舍**:面试先写记忆化保正确,再改递推提性能。`n ≤ 1e5` 必须递推;`n ≤ 1000` 记忆化没问题。

### 3.11 优化技巧(简述,知道何时需要即可)

- **滚动数组**:`f[i]` 只依赖 `f[i-1]` → 开两行交替,`O(n) → O(1)` 空间。
- **单调队列优化**:转移形如 `f[i] = min(f[j]) + w[i]`,`j ∈ [i-k, i-1]` → 滑窗最小值,`O(n²)→O(n)`(如 239)。
- **树状数组/线段树优化**:转移依赖"前缀最值且带修改"时使用。

---

## 四、高频避坑清单(逐条对照)

1. **状态定义不清**:写代码前用一句话说清 `f[i]` 是什么。说不清 → 别写。
2. **边界错位**:`f[0]` 是"空"还是"第一个元素"?下标 `i` 用"前 i 个"还是"第 i 个"?整篇统一。
3. **初始化遗漏**:编辑距离的 `f[i][0]=i`、`f[0][j]=j` 漏一行就全错。
4. **背包遍历顺序**:0/1 逆序、完全顺序 — 永远的坑。
5. **滚动数组错覆盖**:滚动后 `f[j-w[i]]` 可能已是本轮的值 → 0/1 背包必须逆序。
6. **负数状态需偏移**:和可能为负 → 全部 `+offset` 平移。
7. **字典序最小要倒推**:从 `f[n]` 倒推路径,每步选字典序小的方向。
8. **记忆化 vs 递推答案位置不同**:记忆化常返回 `dfs(n)`,递推常返回 `f[n]` 或 `max(f)`,别混。
9. **方案数取模**:每步 `% MOD`,减法 `+ MOD` 防负。
10. **二维状态维度顺序影响 cache**:外层循环是"阶段",先 i 后 j;搞反可能用到未计算的值。

---

## 五、速记口诀 + 对比表

**口诀**:"最后一步想清楚,状态转移自然有;背包逆序完全序,滚动数组别覆盖;区间三段长 i-k,状压塞进 mask 里。"

| 维度 | 0/1 背包 | 完全背包 | 多重背包 |
|---|---|---|---|
| 物品次数 | 0 / 1 | ∞ | 指定 c[i] 次 |
| 内层顺序 | **逆序** | **顺序** | 二进制拆分转 0/1 |
| "恰好装满" | f[0]=0,其余 -∞ | 同 | 同 |

| 维度 | 记忆化搜索 | 递推 |
|---|---|---|
| 实现 | @lru_cache | for 循环 |
| 顺序 | 不关心 | 必须拓扑序 |
| 性能 | 慢 | 快 |
| 推荐时机 | 多维/状压/树形 | 一维/网格/线性 |

---

## 六、自测清单

- [ ] 5 分钟内默写 0/1 背包 + 完全背包,**说清内层循环方向差异**
- [ ] 默写 LIS O(n log n) 的 `tails` 贪心,**解释为什么 tails 单调**
- [ ] 默写区间 DP 三段循环(长 → i,j → k)
- [ ] 用状态机写出股票 188,**说清 `k > n//2` 退化**
- [ ] 默写 847 状态压缩 BFS,`mask` 维度怎么进队
- [ ] 默写编辑距离的三选一转移(增/删/改)
- [ ] 解释"为什么记忆化搜索等价于递推"

> 任何一项卡壳 → 回到对应小节重读模板,**手抄一遍代码再默写**。DP 的薄弱只能靠"写过的模板数"补,没有捷径。
