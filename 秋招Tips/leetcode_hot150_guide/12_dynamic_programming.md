# 12. 动态规划 [深入]

这是你最薄弱的地方。DP 题看起来每道都需要一个巧妙技巧，但其实都可以归结为**八种反复出现的状态设计**。掌握了它们，DP 就变成了一道分类题。

---

## 0. 打开所有 DP 题的思维模型

每个 DP 题都是下面**四个问题**的答案：

1. **状态是什么？** —— 一个由下标（可能还有其他少量状态）组成的元组，它完整地标识了一个子问题。
2. **`dp[状态]` 表示什么？** —— 一个计数、一个最大值、一个最小值、一个布尔值（"是否能达到 X？"）。
3. **递推式是什么？** —— `dp[状态]` 如何由更小的子问题组合而成？
4. **基准情况是什么？** —— 空输入、单个元素、边界条件。

**DP 的本质：** 最优子结构 + 重叠子问题。同一个 `dp[状态]` 会在不同的大问题里被反复使用。记忆化（自顶向下）或迭代（自底向上）能避免重复计算。

### 最有用的一问

> "如果我有一个神谕，能解决*所有更小输入*的问题，那么对当前输入，我该如何组合这些答案？"

能回答这个问题，你就有了递推式。然后加上记忆化 / 递推。

### 自顶向下 vs 自底向上

- **自顶向下（记忆化）：** 用 `@lru_cache` 把递推式写成递归。写起来简单；空间优化比较难。
- **自底向上（递推）：** 从小到大遍历 `状态`，填充 `dp[状态]`。容易把空间优化到 O(1) 或 O(n)；但思考过程比较费劲。

**经验法则：** 先用自顶向下写对递推式，如果在意内存或常数，再改成自底向上。

```python
# 自顶向下模板
from functools import lru_cache

@lru_cache(None)
def dp(i: int, j: int) -> int:
    if base_condition: return base_value
    return combine(dp(i - 1, j), dp(i, j - 1), ...)   # 取决于具体问题

# 自底向上模板（同样的递推式，改成迭代）
dp = [[0] * (n + 1) for _ in range(m + 1)]
for i in range(1, m + 1):
    for j in range(1, n + 1):
        dp[i][j] = combine(dp[i - 1][j], dp[i][j - 1], ...)
return dp[m][n]
```

---

## 1. 一维 DP —— 入门组

最简单的 DP。状态就是一个下标 `i`。

### 1.1 爬楼梯

```python
def climb_stairs(n: int) -> int:
    if n <= 2: return n
    a, b = 1, 2                                    # f(1), f(2)
    for _ in range(3, n + 1):
        a, b = b, a + b
    return b
```

**状态：** `dp[i]` = 到达第 `i` 阶的方式数。**递推式：** `dp[i] = dp[i-1] + dp[i-2]`。**基准：** `dp[1] = 1, dp[2] = 2`。

### 1.2 打家劫舍 —— 抢或不抢

```python
def rob(nums: list[int]) -> int:
    prev, cur = 0, 0                              # dp[i-2], dp[i-1]
    for x in nums:
        prev, cur = cur, max(cur, prev + x)
    return cur
```

**状态：** `dp[i]` = 抢劫房子 `0..i` 的最大金额。**递推式：** `dp[i] = max(dp[i-1], dp[i-2] + nums[i])`（不抢第 i 家 OR 抢第 i 家）。

### 1.3 打家劫舍 II（环形）—— 拆成两次

分别求解房子 `0..n-2`（去掉最后一家）和 `1..n-1`（去掉第一家），取较大值。这样把环形问题分解成两个线性问题。

### 1.4 解码方法 —— "这个子串能否解析？"

```python
def num_decodings(s: str) -> int:
    n = len(s)
    dp = [0] * (n + 1)
    dp[0] = 1                                     # 空串有一种解码方式
    dp[1] = 1 if s[0] != '0' else 0
    for i in range(2, n + 1):
        if s[i - 1] != '0': dp[i] += dp[i - 1]    # 单数字解码
        two = int(s[i - 2:i])
        if 10 <= two <= 26: dp[i] += dp[i - 2]    # 双数字解码
    return dp[n]
```

**状态：** `dp[i]` = 解码 `s[:i]` 的方式数。**递推式：** 若 `s[i-1]` 是合法的单个数字，加上 `dp[i-1]`；若 `s[i-2:i]` 是合法的两位数字，加上 `dp[i-2]`。

### 1.5 单词拆分 —— "s 能否被字典里的单词切分？"

```python
def word_break(s: str, word_dict: list[str]) -> bool:
    words = set(word_dict)
    dp = [False] * (len(s) + 1)
    dp[0] = True
    for i in range(1, len(s) + 1):
        for j in range(i):
            if dp[j] and s[j:i] in words:
                dp[i] = True; break
    return dp[len(s)]
```

**状态：** `dp[i]` = 若 `s[:i]` 能被切分则为 `True`。**递推式：** `dp[i] = OR(j < i 的所有情况) of (dp[j] and s[j:i] in dict)`。

**优化：** 遍历 `j` 时按字典单词的长度，而不是所有下标。或者预算最大单词长度以限制内层循环的范围。

### 1.6 零钱兑换 —— 凑出金额的最少硬币数

```python
def coin_change(coins: list[int], amount: int) -> int:
    dp = [float('inf')] * (amount + 1)
    dp[0] = 0
    for x in range(1, amount + 1):
        for c in coins:
            if c <= x: dp[x] = min(dp[x], dp[x - c] + 1)
    return dp[amount] if dp[amount] != float('inf') else -1
```

**状态：** `dp[x]` = 凑出金额 `x` 的最少硬币数。**递推式：** `dp[x] = min(dp[x - c] + 1 for c in coins if c ≤ x)`。

**完全背包风格** —— 每种硬币可以用多次。

### 1.7 最长递增子序列 —— O(n²) 和 O(n log n)

```python
# O(n^2) DP
def length_of_lis(nums: list[int]) -> int:
    n = len(nums)
    dp = [1] * n                                   # dp[i] = 以 i 结尾的 LIS 长度
    for i in range(n):
        for j in range(i):
            if nums[j] < nums[i]:
                dp[i] = max(dp[i], dp[j] + 1)
    return max(dp, default=0)

# O(n log n) 借助耐心排序
import bisect

def length_of_lis_fast(nums: list[int]) -> int:
    tails: list[int] = []                          # tails[i] = 长度为 i+1 的 LIS 的最小尾元素
    for x in nums:
        i = bisect.bisect_left(tails, x)          # 严格递增 -> bisect_left
        if i == len(tails): tails.append(x)
        else: tails[i] = x
    return len(tails)
```

对于**非严格**递增 LIS（允许相等），用 `bisect_right`。

---

## 2. 二维 DP —— 网格路径问题

### 2.1 不同路径

```python
def unique_paths(m: int, n: int) -> int:
    dp = [1] * n
    for _ in range(1, m):
        for j in range(1, n):
            dp[j] += dp[j - 1]
    return dp[-1] if n else 0
```

**状态：** `dp[i][j]` = 到单元格 `(i, j)` 的路径数。**递推式：** `dp[i][j] = dp[i-1][j] + dp[i][j-1]`。**空间优化：** 用一维，因为每一行只依赖上一行。

### 2.2 最小路径和

```python
def min_path_sum(grid: list[list[int]]) -> int:
    m, n = len(grid), len(grid[0])
    dp = [0] * n
    dp[0] = grid[0][0]
    for j in range(1, n): dp[j] = dp[j - 1] + grid[0][j]
    for i in range(1, m):
        dp[0] += grid[i][0]
        for j in range(1, n):
            dp[j] = min(dp[j], dp[j - 1]) + grid[i][j]
    return dp[-1]
```

### 2.3 最长公共子序列

```python
def longest_common_subsequence(text1: str, text2: str) -> int:
    m, n = len(text1), len(text2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if text1[i - 1] == text2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]
```

**状态：** `dp[i][j]` = `text1[:i]` 与 `text2[:j]` 的 LCS。**递推式：** 字符相等时，在 `dp[i-1][j-1]` 的基础上 +1；否则取"去掉一个字符"两种情况的较大值。

### 2.4 编辑距离（Levenshtein）

```python
def min_distance(word1: str, word2: str) -> int:
    m, n = len(word1), len(word2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if word1[i - 1] == word2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1],   # 替换
                                   dp[i - 1][j],         # 从 word1 删除
                                   dp[i][j - 1])         # 在 word1 中插入
    return dp[m][n]
```

三种转移分别对应**替换、删除、插入**。记清楚哪个维度对应什么。

### 2.5 最长回文子串

```python
def longest_palindrome(s: str) -> str:
    n = len(s)
    dp = [[False] * n for _ in range(n)]
    start, best = 0, 1
    for i in range(n): dp[i][i] = True
    for length in range(2, n + 1):                 # 按长度遍历，而不是按 i
        for i in range(n - length + 1):
            j = i + length - 1
            if s[i] == s[j] and (length == 2 or dp[i + 1][j - 1]):
                dp[i][j] = True
                if length > best: start, best = i, length
    return s[start:start + best]
```

**按长度遍历**是区间 DP 的硬性要求——递推式 `dp[i][j]` 依赖 `dp[i+1][j-1]`，即一个更短的区间。

还有 O(n) 的 Manacher 算法（第 18 章）——对大多数面试来说属于过度优化。

### 2.6 计数回文子串

```python
def count_substrings(s: str) -> int:
    n = len(s)
    dp = [[False] * n for _ in range(n)]
    ans = 0
    for i in range(n):
        dp[i][i] = True; ans += 1
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            if s[i] == s[j] and (length == 2 or dp[i + 1][j - 1]):
                dp[i][j] = True; ans += 1
    return ans
```

### 2.7 最长回文子序列

```python
def longest_palindrome_subseq(s: str) -> int:
    n = len(s)
    dp = [[0] * n for _ in range(n)]
    for i in range(n): dp[i][i] = 1
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            if s[i] == s[j]:
                dp[i][j] = dp[i + 1][j - 1] + 2
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j - 1])
    return dp[0][n - 1]
```

另一种思路：`s` 与 `s[::-1]` 的 LCS。

---

## 3. 区间 DP

状态是数组上的一个**区间** `[i, j]`。递推式在 `i` 和 `j` 之间的某个 `k` 处切分区间。

**通用模板：**

```python
# 先按长度遍历，再按左端点 i 遍历，再按切分点 k 遍历
for length in range(2, n + 1):
    for i in range(n - length + 1):
        j = i + length - 1
        for k in range(i, j):
            dp[i][j] = combine(dp[i][j], dp[i][k] + dp[k + 1][j] + cost(i, j, k))
```

### 3.1 戳气球

```python
def max_coins(nums: list[int]) -> int:
    nums = [1] + nums + [1]
    n = len(nums)
    dp = [[0] * n for _ in range(n)]
    for length in range(2, n):                     # 左右边界之间的间距
        for i in range(n - length):
            j = i + length
            for k in range(i + 1, j):              # k 是最后被戳破的气球
                dp[i][j] = max(dp[i][j],
                               dp[i][k] + dp[k][j] + nums[i] * nums[k] * nums[j])
    return dp[0][n - 1]
```

**核心思路：** 不要想"先戳哪个气球"，而是想"在 `[i+1, j-1]` 中**最后**戳破哪个气球"。最后一个气球的得分 = `nums[i] * nums[k] * nums[j]`，因为它的相邻气球就是边界那两个。

### 3.2 矩阵链乘法（结构相同）

`dp[i][j]` = 乘出矩阵 `i..j` 的最小代价。尝试 `i` 与 `j-1` 之间的每个切分点 `k`。

### 3.3 预测赢家（最小最大博弈）

```python
def predict_the_winner(nums: list[int]) -> bool:
    n = len(nums)
    dp = [[0] * n for _ in range(n)]
    for i in range(n): dp[i][i] = nums[i]
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            # 玩家拿 nums[i]，对手得到 dp[i+1][j] -> 得分 = nums[i] - dp[i+1][j]
            # 或者拿 nums[j]，得分 = nums[j] - dp[i][j-1]
            dp[i][j] = max(nums[i] - dp[i + 1][j], nums[j] - dp[i][j - 1])
    return dp[0][n - 1] >= 0
```

博弈 DP：保存**当前玩家的净得分差**。

### 3.4 安排工作日的最低难度

把工作分成 K 天完成，最小化最大难度。`dp[k][i]` = 前 `i` 份工作用 `k` 天完成的最小难度。见题目 1335。

---

## 4. 背包族

### 4.1 0/1 背包 —— 每件物品最多取一次

```python
def knapsack(weights: list[int], values: list[int], W: int) -> int:
    n = len(weights)
    dp = [0] * (W + 1)
    for i in range(n):
        # 倒序遍历，避免重复使用同一件物品
        for w in range(W, weights[i] - 1, -1):
            dp[w] = max(dp[w], dp[w - weights[i]] + values[i])
    return dp[W]
```

**倒序遍历是关键** —— 它保证每件物品最多被用一次。

### 4.2 完全背包 —— 物品可重复使用

```python
def unbounded(weights: list[int], values: list[int], W: int) -> int:
    dp = [0] * (W + 1)
    for w in range(1, W + 1):
        for i in range(len(weights)):
            if weights[i] <= w:
                dp[w] = max(dp[w], dp[w - weights[i]] + values[i])
    return dp[W]
```

**正序遍历**允许重复使用同一件物品。

### 4.3 分割等和子集

`nums` 能否被分成和相等的两份？等价于 0/1 背包，其中 target = `sum / 2`，weights = values = nums。

```python
def can_partition(nums: list[int]) -> bool:
    s = sum(nums)
    if s % 2: return False
    target = s // 2
    dp = [False] * (target + 1)
    dp[0] = True
    for x in nums:
        for w in range(target, x - 1, -1):        # 倒序！
            dp[w] = dp[w] or dp[w - x]
    return dp[target]
```

### 4.4 目标和（给元素赋 +/- 使总和为 S）

```python
def find_target_sum_ways(nums: list[int], target: int) -> int:
    # 设 P 是被赋 '+' 的子集，N 被赋 '-'：P - N = target, P + N = sum
    # => 2*P = target + sum => P = (target + sum) / 2 必须是非负整数
    total = sum(nums)
    if (total + target) % 2 or total + target < 0: return 0
    P = (total + target) // 2
    dp = [0] * (P + 1)
    dp[0] = 1
    for x in nums:
        for w in range(P, x - 1, -1):
            dp[w] += dp[w - x]
    return dp[P]
```

规约为"数出和为 P 的子集数"——带计数的 0/1 背包。

### 4.5 划分为 K 个等和子集

用**带记忆化的回溯 + 位掩码**：

```python
def can_partition_k_subsets(nums: list[int], k: int) -> bool:
    total = sum(nums)
    if total % k: return False
    target = total // k
    nums.sort(reverse=True)                        # 大的优先——失败更快
    if nums[0] > target: return False
    n = len(nums)
    used = [False] * n

    @lru_cache(None)
    def search(remaining_k: int, current_sum: int, start: int) -> bool:
        if remaining_k == 0: return True
        if current_sum == target:
            return search(remaining_k - 1, 0, 0)
        for i in range(start, n):
            if not used[i] and current_sum + nums[i] <= target:
                used[i] = True
                if search(remaining_k, current_sum + nums[i], i + 1):
                    used[i] = False                # 在返回前清理
                    return True
                used[i] = False
                # 剪枝：如果这个数开不了新一组，尝试别的数也没意义
                if current_sum == 0: return False
        return False
    return search(k, 0, 0)
```

---

## 5. 状态机 DP —— 买卖股票族

诀窍：用**上一步做了什么**来定义状态，并在状态之间转移。

### 5.1 买卖股票的最佳时机（单次交易）

```python
def max_profit(prices: list[int]) -> int:
    min_so_far = float('inf')
    ans = 0
    for p in prices:
        ans = max(ans, p - min_so_far)
        min_so_far = min(min_so_far, p)
    return ans
```

### 5.2 含冷冻期 —— 完整状态机

```python
def max_profit_cooldown(prices: list[int]) -> int:
    # 三种状态：持有、今日刚卖出、冷却（可买入）
    held = float('-inf')                            # 手里有股票时的最大利润
    sold = float('-inf')                            # 今日刚卖出时的最大利润
    reset = 0                                       # 没有股票、且今日不是刚卖出时的最大利润
    for p in prices:
        prev_held, prev_sold, prev_reset = held, sold, reset
        held = max(prev_held, prev_reset - p)      # 继续持有 或 今日买入（必须处于 reset）
        sold = prev_held + p                        # 今日卖出 -> 明日冷却
        reset = max(prev_reset, prev_sold)          # 冷却中，或从冷却恢复
    return max(sold, reset)
```

三种状态（持有 / 刚卖出 / 冷却）—— 每次转移对应一个动作。记牢状态转移图。

### 5.3 含手续费

```python
def max_profit_fee(prices: list[int], fee: int) -> int:
    cash, hold = 0, -prices[0]                     # cash = 没股票；hold = 持有股票
    for p in prices[1:]:
        cash = max(cash, hold + p - fee)
        hold = max(hold, cash - p)
    return cash
```

两个状态：`cash`（没有股票）和 `hold`（持有股票）。转移：`cash = max(cash, hold + p - fee)`（卖出），`hold = max(hold, cash - p)`（买入）。

### 5.4 最多 K 笔交易

```python
def max_profit_k(k: int, prices: list[int]) -> int:
    n = len(prices)
    if n <= 1 or k == 0: return 0
    # 若 k >= n//2，问题等价于无限制 -> 贪心
    if k >= n // 2:
        return sum(max(prices[i] - prices[i - 1], 0) for i in range(1, n))
    # dp[t][d] = 第 d 天、至多 t 笔交易、且不持有股票时的最大利润
    dp = [[0] * n for _ in range(k + 1)]
    for t in range(1, k + 1):
        max_diff = -prices[0]                       # 取所有 d'<d 中 (dp[t-1][d'] - prices[d']) 的最大值
        for d in range(1, n):
            dp[t][d] = max(dp[t][d - 1], prices[d] + max_diff)
            max_diff = max(max_diff, dp[t - 1][d] - prices[d])
    return dp[k][n - 1]
```

`max_diff` 这个优化维护着"目前为止最适合买入的那一天"，把每笔交易的 O(n²) 降到 O(n)。

---

## 6. 状态压缩 DP —— 小状态空间（n ≤ 20）

当问题涉及一个小集合的排列时，状态就是一个**位掩码**，表示哪些元素已被使用。

### 6.1 旅行商 —— 访问所有节点的最短路径

```python
def shortest_path_visiting_all(graph: list[list[int]]) -> int:
    n = len(graph)
    INF = float('inf')
    # dp[mask][u] = 已经访问过集合 mask、以 u 结尾的最短路径
    dp = [[INF] * n for _ in range(1 << n)]
    for u in range(n): dp[1 << u][u] = 0
    for mask in range(1 << n):
        for u in range(n):
            if not (mask & (1 << u)): continue
            for v in range(n):
                if mask & (1 << v): continue
                new_mask = mask | (1 << v)
                dp[new_mask][v] = min(dp[new_mask][v], dp[mask][u] + graph[u][v])
    return min(dp[(1 << n) - 1])
```

复杂度：O(2^n · n²)。n ≤ 15 时实际可用。

### 6.2 划分为 K 个等和子集 —— 位掩码记忆化

```python
def can_partition_k(nums: list[int], k: int) -> bool:
    total = sum(nums)
    if total % k: return False
    target = total // k
    n = len(nums)

    @lru_cache(None)
    def dp(mask: int, current: int) -> bool:
        if mask == (1 << n) - 1: return current == 0
        for i in range(n):
            if mask & (1 << i): continue
            if current + nums[i] > target: continue
            next_current = (current + nums[i]) % target
            if dp(mask | (1 << i), next_current): return True
        return False
    return dp(0, 0)
```

### 6.3 参加考试的最大学生数 —— 网格上的位掩码 DP

对每一行，状态是该行座位占用情况的位掩码。相邻行之间按可见性规则转移。见 LC 1349。

---

## 7. 树形 DP

树上的 DP：后序遍历，向上返回（或保存）子树的答案。常常需要返回**多个值**（"包含此节点"的情况一个，"不包含"的情况一个）。

### 7.1 打家劫舍 III

```python
def rob(root: TreeNode | None) -> int:
    def dfs(node: TreeNode | None) -> tuple[int, int]:
        # 返回 (不抢根的最大值, 抢根的最大值)
        if not node: return (0, 0)
        l = dfs(node.left)
        r = dfs(node.right)
        # 抢根 => 子节点必须跳过
        rob = node.val + l[0] + r[0]
        # 不抢根 => 子节点可抢可不抢
        skip = max(l) + max(r)
        return (skip, rob)
    return max(dfs(root))
```

**要点：** 每个子树返回**两个值**——"不抢子树根"和"抢子树根"两种情况下的最优解。这是树形 DP 的通用模式。

### 7.2 二叉树的摄像头（LC 968）

每个子树三种状态：0 = 未覆盖，1 = 已覆盖但此处无摄像头，2 = 此处放了摄像头。后序遍历；父节点根据子节点的状态决定自己怎么选。

### 7.3 树中的最长路径（直径）—— 见第 06 章

同样的骨架：后序遍历，向上返回可延伸的长度，并更新全局的最大合并长度。

---

## 8. 字符串上的 DP —— 常见子模式

### 8.1 正则表达式匹配

```python
def is_match(s: str, p: str) -> bool:
    m, n = len(s), len(p)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True
    # 含星号的模式可以匹配空串（例如 "a*b*c*"）
    for j in range(2, n + 1):
        if p[j - 1] == '*': dp[0][j] = dp[0][j - 2]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if p[j - 1] == '*':
                # 前一个字符出现 0 次：dp[i][j-2]
                # 出现一次或多次：若前一个字符匹配 s[i-1]，则 dp[i-1][j]
                dp[i][j] = dp[i][j - 2] or (
                    dp[i - 1][j] and (p[j - 2] == s[i - 1] or p[j - 2] == '.'))
            else:
                dp[i][j] = dp[i - 1][j - 1] and (p[j - 1] == s[i - 1] or p[j - 1] == '.')
    return dp[m][n]
```

### 8.2 通配符匹配

类似：`?` 匹配任意单个字符，`*` 匹配任意序列。

### 8.3 交错字符串

```python
def is_interleave(s1: str, s2: str, s3: str) -> bool:
    if len(s1) + len(s2) != len(s3): return False
    m, n = len(s1), len(s2)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True
    for i in range(m + 1):
        for j in range(n + 1):
            if i > 0 and s1[i - 1] == s3[i + j - 1]:
                dp[i][j] = dp[i][j] or dp[i - 1][j]
            if j > 0 and s2[j - 1] == s3[i + j - 1]:
                dp[i][j] = dp[i][j] or dp[i][j - 1]
    return dp[m][n]
```

### 8.4 不同的子序列（数 s 组成 t 的方式数）

```python
def num_distinct(s: str, t: str) -> int:
    m, n = len(s), len(t)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = 1            # 任意 s 都能组成空串 t
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = dp[i - 1][j]                # 跳过 s[i-1]
            if s[i - 1] == t[j - 1]:
                dp[i][j] += dp[i - 1][j - 1]      # 匹配
    return dp[m][n]
```

### 8.5 两个字符串的最小 ASCII 删除和

LCS 变体：删除代价 = `sum(s) + sum(t) - 2 * sum(lcs)`。

---

## 9. 识别信号

| 提示语 | 模式 |
|---|---|
| "多少种方式"、"计数" | 返回计数的 DP |
| "最长"、"最短"、"最小" | 返回 max/min 的 DP |
| "能否达到"、"是否能做到" | 布尔型 DP |
| "子序列"、"子串"、"公共"、"编辑" | 字符串 DP（第 2 或 8 节） |
| "分成 K 段"、"最小化最大值" | 背包或区间 DP |
| "背包"、"子集和"、"目标和" | 背包族（第 4 节） |
| "买卖股票"、"K 笔交易"、"冷冻期"、"手续费" | 状态机 DP（第 5 节） |
| "戳气球"、"矩阵链"、"博弈最小最大" | 区间 DP（第 3 节） |
| "n ≤ 20"、"小集合的子集" | 位掩码 DP（第 6 节） |
| "树"、"抢劫"、"摄像头" | 树形 DP（第 7 节） |
| "爬 / 解码 / 拆分有多少种方式" | 一维 DP（第 1 节） |

## 10. 思考框架（卡壳时反复重读）

1. **状态是什么？** —— 写出下标和所有额外的少量状态（交易次数、是否持仓、已用元素的位掩码）。
2. **`dp[状态]` 是什么意思？** —— 计数？最大值？布尔值？（显式写出来）
3. **递推式是什么？** —— `dp[状态] = combine(更小的状态)`。试着用一句话表达。
4. **基准情况是什么？** —— 空输入、长度为 0、长度为 1、"第一行"、"第一列"。
5. **遍历顺序是什么？** —— 先填更小的状态。区间 DP 按长度遍历；二维 DP 按行或列遍历。
6. **答案在哪里？** —— 通常是 `dp[n][m]` 或 `max(dp[:])`。
7. **能否优化空间？** —— 如果 `dp[i]` 只依赖 `dp[i-1]`，可以用一维数组。若同时依赖 `dp[i-1][j-1]` 和 `dp[i-1][j]`，仍然能压成一维（用一个临时变量保存 `dp[i-1][j-1]`）。

## 11. 常见失败模式

1. **基准情况写错。** 特别是计数的 `dp[0] = 1`（"空有一种方式"）和求 max/min 的 `dp[0] = 0`（"空集的最大/最小值"）。根据含义选。
2. **下标越界一位。** 一开始就要确定：`dp[i]` 是"前 `i` 个元素"还是"以下标 `i` 结尾"？同一道题里只用一种约定。
3. **背包遍历顺序写错。** 0/1 背包**倒序**遍历（保证每件物品最多用一次）。完全背包**正序**遍历。
4. **区间 DP 遍历顺序错。** 必须先按长度，再按左端点遍历。若先按 `i` 遍历，会得到错误答案，因为 `dp[i+1][j-1]` 还没被算出来。
5. **忘记初始化基准行/列。** 例如 LCS 需要 `dp[i][0] = dp[0][j] = 0`。循环往往从 `i=1, j=1` 开始，导致第 0 行/列没被初始化。
6. **状态维度过小。** 例如"最多 K 笔交易的最大利润"，状态是 `(交易数, 天数)`，而不只是 `(天数)`——少了交易数就无法限制交易次数。
7. **树形 DP 只返回一个值。** 对于"包含/不包含此节点"的问题，必须两个值都返回，否则父节点无法做决策。
8. **`lru_cache` 套在可变参数上。** `lru_cache` 要求参数可哈希；list 不行。要用 tuple 或 string。
9. **位掩码 DP 没充分剪枝。** `2^n · n²` 只能支持 `n ≤ 15`。`n = 20` 时必须大幅剪枝或换思路。
10. **整数溢出** —— Python 没有这个问题；但如果移植到其他语言，要在计数 DP（答案指数级增长）里小心。
11. **计数题的取模。** 如果题目说"对 1e9+7 取模"，每次相加时就要取模：`(dp[i-1] + dp[i-2]) % MOD`。
12. **返回 `dp[n][m]` 还是 `max(dp[:])`。** 有些题需要所有状态取最大值，而不是角落那个格（例如 LIS）。

## 12. 练习清单 —— Hot 150 DP 题目

按以下顺序冷启动。目的是**每题掌握一种状态设计**，而不是死记硬背解法。

### 入门（一维）

| # | 题目 | 模式 |
|---|---------|---------|
| 1 | 70. Climbing Stairs | 1.1 —— 斐波那契 |
| 2 | 198. House Robber | 1.2 —— 抢或不抢 |
| 3 | 213. House Robber II | 1.3 —— 环形，拆两次 |
| 4 | 91. Decode Ways | 1.4 |
| 5 | 139. Word Break | 1.5 |
| 6 | 322. Coin Change | 1.6 —— 完全背包 |
| 7 | 300. Longest Increasing Subsequence | 1.7 —— O(n²) 和 O(n log n) |

### 二维 / 字符串 DP

| # | 题目 | 模式 |
|---|---------|---------|
| 8 | 62. Unique Paths | 2.1 |
| 9 | 64. Minimum Path Sum | 2.2 |
| 10 | 1143. Longest Common Subsequence | 2.3 |
| 11 | 72. Edit Distance | 2.4 —— 三种转移 |
| 12 | 5. Longest Palindromic Substring | 2.5 —— 区间 DP |
| 13 | 647. Palindromic Substrings | 2.6 |
| 14 | 516. Longest Palindromic Subsequence | 2.7 |
| 15 | 115. Distinct Subsequences | 8.4 |
| 16 | 97. Interleaving String | 8.3 |
| 17 | 10. Regular Expression Matching | 8.1 |
| 18 | 44. Wildcard Matching | 8.2 |

### 背包与位掩码

| # | 题目 | 模式 |
|---|---------|---------|
| 19 | 416. Partition Equal Subset Sum | 4.3 |
| 20 | 494. Target Sum | 4.4 |
| 21 | 474. Ones and Zeroes | 4.1 —— 二维背包 |
| 22 | 698. Partition to K Equal Sum Subsets | 4.5 / 6.2 —— 位掩码 |
| 23 | 1655. Distribute Repeating Integers | 6.x —— 位掩码子集 |

### 区间 DP

| # | 题目 | 模式 |
|---|---------|---------|
| 24 | 312. Burst Balloons | 3.1 |
| 25 | 486. Predict the Winner | 3.3 |
| 26 | 1335. Minimum Difficulty of a Job Schedule | 3.4 |

### 状态机

| # | 题目 | 模式 |
|---|---------|---------|
| 27 | 121. Best Time to Buy and Sell Stock | 5.1 |
| 28 | 122. Best Time II（多笔交易） | 贪心：累加所有正的相邻差 |
| 29 | 309. Best Time with Cooldown | 5.2 |
| 30 | 714. Best Time with Transaction Fee | 5.3 |
| 31 | 188. Best Time IV（最多 K 笔） | 5.4 |
| 32 | 123. Best Time III（最多 2 笔） | 5.4 取 k=2 |

### 树形 DP

| # | 题目 | 模式 |
|---|---------|---------|
| 33 | 337. House Robber III | 7.1 —— 返回两个值 |
| 34 | 968. Binary Tree Cameras | 7.2 —— 三种状态 |
| 35 | 124. Binary Tree Maximum Path Sum | （第 06 章）—— 全局 + 向上 |
| 36 | 543. Diameter of Binary Tree | （第 06 章）—— 同一骨架 |

**模式锁定计划：**
- **第 1-2 天：** 入门（1-7），直到一维递推式变成本能。
- **第 3 天：** 二维字符串 DP（8-14）—— 面试最爱考的类别之一。
- **第 4 天：** 区间 DP（24-26）—— 按长度遍历这个模式。
- **第 5 天：** 状态机（27-32）—— 买卖股票族性价比最高。
- **第 6 天：** 树形 DP（33-36）—— 后序遍历 + 返回多值。
- **第 7 天：** 背包与位掩码（19-23）—— 倒序遍历 + 位掩码记忆化。

之后重新冷做 11、14、24、31 这四题——它们代表了四种最难的 DP 模式。

---

## 最后的思维模型

每道 DP 题，先把下面的骨架写出来：

```python
def solve(input) -> Answer:
    # 1. 定义状态：dp[?] = ?（计数 / 最大 / 最小 / 布尔）
    # 2. 基准情况：dp[?] = ?
    # 3. 递推式：dp[i][j] = combine(dp[更小的状态])
    # 4. 遍历顺序：先填更小的状态（区间按长度、二维按行、背包按金额）
    # 5. 答案：dp[n][m] 或 max(dp[:]) —— 取决于题目
```

只要你能从题目里填出第 1-3 步，剩下的实现就是机械工作。难的部分是**把状态定义对**——一旦定义对了，递推式自然就出来了。

### DP 状态命名速查

- 一维下标 → "以下标 i 结尾"或"前 i 个元素"（LIS、打家劫舍、零钱兑换）。
- 二维下标 (i, j)，两个串 → "A 的前 i 个字符与 B 的前 j 个字符"（LCS、编辑距离）。
- 二维下标 (i, j)，一个串 → "区间 [i, j]"（回文、戳气球）。
- (i, 是否持仓) → "第 i 天结束，持仓/不持仓"（买卖股票）。
- (mask, 终点) → "已访问集合 = mask，终点在 last_position"（TSP）。
- (mask, 当前和) → "已用集合 = mask，当前桶的和"（K 划分）。
- 树上的后序 → "以该节点为根的子树，返回 (不取, 取) 元组"。

(End of file - total 819 lines)
