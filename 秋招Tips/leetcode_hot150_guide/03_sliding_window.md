# 03. 滑动窗口

## 核心概念

滑动窗口把"对每个端点回扫寻找合法子数组"这种 O(n²) 的做法降到 O(n)，方法是维护一个 **窗口** `[l, r]`，扩张 `r`、收缩 `l` 来恢复不变量。两种形态：

1. **定长窗口** —— 窗口大小恰好为 `k`。读完前 `k` 个元素后，两个指针同步向前滑动。
2. **变长窗口** —— `r` 一直扩张；只有当不变量被破坏时 `l` 才前进。用于"满足某约束的最长子数组"或"和 ≥ K 的最短子数组"。

**单调队列**是第三种变体，用于"在当前窗口内 O(1) 摊还时间取最大值/最小值"。

## 模式与模板

### 1. 定长窗口 —— 滚动求和 / 滚动哈希

```python
def fixed_window_sum(nums: list[int], k: int) -> int:
    cur = sum(nums[:k])
    best = cur
    for i in range(k, len(nums)):
        cur += nums[i] - nums[i - k]
        best = max(best, cur)
    return best
```

### 2. 变长窗口 —— 最多 K 种不同字符的最长子串

```python
def length_of_longest_substring_k_distinct(s: str, k: int) -> int:
    from collections import defaultdict
    cnt: dict[str, int] = defaultdict(int)
    l = 0
    best = 0
    for r, c in enumerate(s):
        cnt[c] += 1
        while len(cnt) > k:                       # 不变量：不同字符数 ≤ k
            cnt[s[l]] -= 1
            if cnt[s[l]] == 0: del cnt[s[l]]
            l += 1
        best = max(best, r - l + 1)
    return best
```

**关键不变量：** 在每次迭代顶部，`[l, r-1]` 满足约束；`while` 循环收缩后，`[l, r]` 满足约束。所以 `best = max(best, r - l + 1)` 是正确的。

### 3. 变长窗口 —— 和 ≥ target 的最短子数组

```python
def min_subarray_len(target: int, nums: list[int]) -> int:
    l = cur = 0
    best = float('inf')
    for r, x in enumerate(nums):
        cur += x
        while cur >= target:                     # 在仍然合法时尽量收缩
            best = min(best, r - l + 1)
            cur -= nums[l]; l += 1
    return best if best != float('inf') else 0
```

### 4. 变长窗口 —— 无重复字符的最长子串

```python
def length_of_longest_substring(s: str) -> int:
    last: dict[str, int] = {}                    # 每个字符最近一次出现的下标
    l = 0
    best = 0
    for r, c in enumerate(s):
        if c in last and last[c] >= l:           # 把 l 跳过冲突位置
            l = last[c] + 1
        last[c] = r
        best = max(best, r - l + 1)
    return best
```

### 5. 单调队列 —— 滑动窗口最大值

```python
from collections import deque

def max_sliding_window(nums: list[int], k: int) -> list[int]:
    dq: deque[int] = deque()                     # 存下标，对应的值单调递减
    out: list[int] = []
    for i, x in enumerate(nums):
        while dq and dq[0] <= i - k: dq.popleft()        # 弹出已过期的下标
        while dq and nums[dq[-1]] <= x: dq.pop()        # 维护递减
        dq.append(i)
        if i >= k - 1: out.append(nums[dq[0]])
    return out
```

队列存的是下标，这些下标对应的值 **严格递减**。队首永远是当前窗口的最大值。当新值 `x` 到来时，所有更小且更老的元素永远不会成为窗口最大值，把它们弹出即可。

### 6. 把约束表达成计数差的最长子数组

对于"最长子数组满足 count(1) - count(0) == target"，维护一个累计差值 `bal`，记录每个 `bal` 值最早出现的位置，然后 `bal == target` 在 `r` 处与最早出现 `bal == 0` 的位置配对。

## 识别信号

- "longest/shortest subarray (substring) with [property]" → 变长窗口。
- "every subarray of size K" → 定长窗口。
- "at most K distinct"、"at most K replacements"、"K occurrences" → 带计数器的变长窗口。
- "maximum of every window of size K" → 单调队列。
- "subarray sum equals K" → 前缀和 + 哈希（文件 01），不是滑动窗口。
- "minimum window substring containing all of T" → 变长窗口扩张 + 计数器判定。

## 思考框架

1. **窗口必须满足什么性质？** 把不变量写出来。
2. **需要追踪什么状态？** 不同字符的计数？当前和？每个字符最近一次出现的下标？
3. **`l` 何时前进、前进多少？** while 循环收缩（变长），或者固定步长（定长）。
4. **在哪里更新答案？** 在每轮迭代恢复不变量之后（最长），或者在收缩过程中（最短）。
5. **时间复杂度？** 每个元素入窗口一次、出窗口一次 → O(n)，即使有两层循环。

## Hot 150 例题

- **3. Longest Substring Without Repeating Characters** —— 模式 4。
- **121. Best Time to Buy and Sell Stock** —— 单遍维护迄今为止的最小值；也可以理解为变长窗口，`l` 跳到新的最小值。
- **209. Minimum Size Subarray Sum** —— 模式 3。
- **219. Contains Duplicate II** —— 大小为 `k` 的滑动哈希集合（或使用 `last_seen` 字典）。
- **424. Longest Repeating Character Replacement** —— 变长窗口：只要 `(window_len - max_count_in_window) ≤ k` 窗口就合法。用 `cnt` 与 `max_freq`（注意 `max_freq` 只需追踪历史最大值——见常见陷阱）。
- **76. Minimum Window Substring** —— 变长窗口配合两个计数：需要的字符数和已匹配的字符数。

## 易错点

- **变长窗口求"最长"**：在收缩之后更新 `best = max(best, r - l + 1)`（不变量恢复后才更新）。
- **变长窗口求"最短"**：在 while 循环内部、`best = min(best, r - l + 1)`，因为合法窗口只在收缩过程中出现。
- **424 字符替换常见 bug：** 严格维护 `max_freq` 需要重新扫描，每步 O(26) 是可以接受的。许多"优化"做法会保留一个偏大的 `max_freq`，因为答案只会变大，但这是细枝末节；如果拿不准，就每步重新计算 `max(cnt.values())`。
- **`while` vs `if`：** 收缩时用 `while` —— 窗口可能需要收缩多次才能恢复不变量。
- **单调队列：** 队列中存的是 **下标**（方便判断过期），不是值。队首是最大值，不一定是最近进入的。
- **空窗口 bug：** 如果题目允许 `l > r`（空窗口），小心 `r - l + 1` 出现负数。
- **字符串键 vs `chr` 码：** 仅含 ASCII 的题目，可以用长度为 128 的数组代替字典，获得 O(1) 的更新；这只有在非常紧凑的内层循环里才有意义。