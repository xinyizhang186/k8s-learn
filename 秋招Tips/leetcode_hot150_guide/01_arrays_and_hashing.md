# 01. 数组与哈希

## 核心概念

- **哈希表（dict）** —— 平均 O(1) 的插入/查找。用于频率统计、两数之和、去重、分组。
- **Counter** —— `collections.Counter` 是 dict 的子类，提供 `.most_common(k)`，支持算术运算（`+`、`-`、`&`、`|`）。
- **前缀和** —— 在 O(n) 内预计算 `P[i] = a[0] + ... + a[i-1]`，区间和 `a[l..r] = P[r+1] - P[l]` 可在 O(1) 时间内得到。
- **差分数组** —— 批量区间更新：`d[l] += x; d[r+1] -= x`，再求前缀和即可恢复原数组。

## 模式与模板

### 1. 两数之和系列 —— 哈希表记录所需补数

```python
def two_sum(nums: list[int], target: int) -> list[int]:
    seen: dict[int, int] = {}                    # value -> index
    for i, x in enumerate(nums):
        if (need := target - x) in seen:
            return [seen[need], i]
        seen[x] = i
    return []                                      # 假设一定存在一个解
```

### 2. 频率统计 —— 异位词分组、查找重复项

```python
from collections import Counter, defaultdict

def group_anagrams(strs: list[str]) -> list[list[str]]:
    groups: dict[tuple[int, ...], list[str]] = defaultdict(list)
    for s in strs:
        key = tuple(Counter(s).items())            # 也可以用 tuple(sorted(s))
        groups[key].append(s)
    return list(groups.values())
```

### 3. 前缀和 —— 和为 k 的子数组

```python
def subarray_sum(nums: list[int], k: int) -> int:
    count = 0
    prefix = 0
    seen: dict[int, int] = {0: 1}                  # 前缀和 0 出现一次（空前缀）
    for x in nums:
        prefix += x
        count += seen.get(prefix - k, 0)           # 以当前位置结尾、和为 k 的子数组个数
        seen[prefix] = seen.get(prefix, 0) + 1
    return count
```

### 4. 差分数组 —— 区间加，然后点查询

```python
def range_add(n: int, updates: list[tuple[int, int, int]]) -> list[int]:
    d = [0] * (n + 1)
    for l, r, val in updates:
        d[l] += val
        d[r + 1] -= val
    out = [0] * n
    cur = 0
    for i in range(n):
        cur += d[i]
        out[i] = cur
    return out
```

### 5. 把多键状态编码成元组

当你需要"两种字符计数首次相等的最早位置"时，可以把累计差值编码：

```python
def find_longest_substring_with_equal(s: str, a: str, b: str) -> int:
    bal = 0
    seen: dict[int, int] = {0: -1}
    best = 0
    for i, c in enumerate(s):
        if c == a: bal += 1
        elif c == b: bal -= 1
        if bal in seen:
            best = max(best, i - seen[bal])
        else:
            seen[bal] = i
    return best
```

## 识别信号

- "两个元素加起来等于 target" → 哈希表（上面）或在有序数组上用双指针（见文件 02）。
- "和为 K 的子数组" → 前缀和 + 哈希。
- "anagram of"、"permutation of"、"isomorphic" → 频率统计或签名键分组。
- "consecutive sequence"、"longest streak" → 哈希集合 + 只从序列起点开始计数。
- "contains duplicate within K indices" → 滑动窗口配合哈希集合（见文件 03）。
- "first non-repeating"、"first unique" → Counter + 第二遍扫描。

## 思考框架

1. **自然的查询是什么？** —— "这个元素是否存在？"、"上一次出现的位置在哪里？"、"有多少个子数组的和为 K？"
2. **需要保留什么状态？** —— 一个值、一个下标、一个计数器、一个累计差值。
3. **迭代过程中必须保持哪些不变量？** —— 把它们写成循环上方的注释。
4. **时间/空间？** —— 哈希增加 O(n) 空间，前缀和也增加 O(n) 空间。通常两者都可以接受。

## Hot 150 例题

- **1. Two Sum** —— 模式 1。
- **49. Group Anagrams** —— 模式 2。
- **217. Contains Duplicate** —— `len(set(nums)) != len(nums)`。
- **128. Longest Consecutive Sequence** —— 模式：构造集合，只从序列起点开始遍历。
  ```python
  def longest_consecutive(nums: list[int]) -> int:
      s = set(nums); best = 0
      for x in s:
          if x - 1 not in s:                       # 只在序列头部开始计数
              y = x
              while y in s: y += 1
              best = max(best, y - x)
      return best
  ```
- **1. Two Sum** 的变体 → 15（3Sum）、18（4Sum）—— 改用 **有序数组上的双指针**，复杂度分别为 O(n²) 和 O(n³)，优于 O(n³)/O(n⁴)。
- **347. Top K Frequent Elements** —— Counter + 按频率分桶（见文件 08）。
- **238. Product of Array Except Self** —— 两遍：先左到右前缀积，再右到左后缀积。
- **271. Encode and Decode Strings** —— 长度前缀编码。
- **36. Valid Sudoku** —— 27 个哈希集合（9 行 + 9 列 + 9 宫格）；单元格 `(r,c)` 属于第 `r//3*3 + c//3` 个宫格。

## 易错点

- **`Counter` 减法** 可能产生零或负数，这些键仍然会保留下来。用 `+` 来丢弃非正计数，或在剪枝后再调用 `.items()`。
- **前缀和 `seen` 的初始化：** 务必把 `seen[0] = 1`（或下标场景下 `seen[0] = -1`）作为种子，以便正确捕获从下标 0 开始的子数组。
- **异位词分组键的选择：** `tuple(sorted(s))` 是 O(k log k) 但写法简单；`tuple(Counter(s).items())` 是 O(k)，无需排序，对很长字符串更优。
- **`hashlib` 处理大键** 是杀鸡用牛刀；用 `tuple(sorted(...))` 或 frozenset(items) 即可。
- **差分数组的边界：** 分配 `n+1` 大小，保证 `d[r+1]` 始终在合法范围内。