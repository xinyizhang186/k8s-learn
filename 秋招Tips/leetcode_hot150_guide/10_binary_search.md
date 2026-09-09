# 10. 二分查找

## 核心概念

二分查找可以在 **有序** 序列中以 O(log n) 时间定位目标。它还可以扩展到 **对答案空间做二分**：如果题目可以表达成「找到满足 f(X) 可行的最小 X」，并且 `f` 单调（在阈值之上为真，之下为假），就可以对 X 做二分。

两种子模式：

1. **在有序数组上二分**：`bisect_left` / `bisect_right`。
2. **对答案做二分**：在 `[lo, hi]` 范围内搜索，`lo, hi` 是答案的上下界；对每个 `mid` 做一次可行性检查。

## 模式与模板

### 1. 标准查找：`bisect`

```python
import bisect

# 找到第一个满足 a[i] >= x 的下标
i = bisect.bisect_left(a, x)

# 找到第一个满足 a[i] > x 的下标（即把 x 插到全部相等元素之后）
i = bisect.bisect_right(a, x)

# 自定义：以 ok(i) 为谓词二分，ok 单调（False, False, ..., True, True, ...）
def lower_bound(ok, lo, hi):
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid): hi = mid
        else: lo = mid + 1
    return lo
```

### 2. 在有序数组上搜索：手写模板

```python
def search(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target: return mid
        if nums[mid] < target: lo = mid + 1
        else: hi = mid - 1
    return -1
```

### 3. 在旋转有序数组中搜索

```python
def search_rotated(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target: return mid
        if nums[lo] <= nums[mid]:                  # 左半段有序
            if nums[lo] <= target < nums[mid]: hi = mid - 1
            else: lo = mid + 1
        else:                                      # 右半段有序
            if nums[mid] < target <= nums[hi]: lo = mid + 1
            else: hi = mid - 1
    return -1
```

每一步先 **判断哪半段有序**，再看目标是否落在有序半段的区间里。

### 4. 旋转有序数组中的最小值

```python
def find_min_rotated(nums: list[int]) -> int:
    lo, hi = 0, len(nums) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] > nums[hi]: lo = mid + 1      # 最小值在右半段
        else: hi = mid                              # 最小值可能是 mid 或在它左侧
    return nums[lo]
```

### 5. 对答案做二分 ：「找满足 f(X) 可行的最小 X」

```python
def min_eating_speed(piles: list[int], H: int) -> int:
    def can_finish(k: int) -> bool:
        return sum((p + k - 1) // k for p in piles) <= H   # 向上取整

    lo, hi = 1, max(piles)
    while lo < hi:
        mid = (lo + hi) // 2
        if can_finish(mid): hi = mid
        else: lo = mid + 1
    return lo
```

**模板要点：**
- `lo` 是 **最小不可行候选 +1**（或最小可行候选）。
- `hi` 是 **最大可行候选**（或最大不可行候选）。
- `mid = (lo + hi) // 2` 向下取整。
- 若 `mid` 可行，则在 `[lo, mid]` 中继续搜（`hi = mid`）；若不可行，则在 `[mid + 1, hi]` 中搜（`lo = mid + 1`）。
- 当 `lo == hi` 时循环结束，那就是答案。

### 6. 两个有序数组的中位数

```python
def find_median_sorted_arrays(nums1: list[int], nums2: list[int]) -> float:
    if len(nums1) > len(nums2): nums1, nums2 = nums2, nums1   # 保证 nums1 更短
    m, n = len(nums1), len(nums2)
    lo, hi = 0, m
    half = (m + n + 1) // 2                       # 左侧分区的元素数
    while lo <= hi:
        i = (lo + hi) // 2                        # 在 nums1 上的切分位置
        j = half - i                              # nums2 上对应的切分位置
        l1 = nums1[i - 1] if i > 0 else float('-inf')
        r1 = nums1[i] if i < m else float('inf')
        l2 = nums2[j - 1] if j > 0 else float('-inf')
        r2 = nums2[j] if j < n else float('inf')
        if l1 <= r2 and l2 <= r1:
            if (m + n) % 2: return max(l1, l2)
            return (max(l1, l2) + min(r1, r2)) / 2.0
        if l1 > r2: hi = i - 1                    # nums1 上的切点太靠右
        else: lo = i + 1
    raise ValueError("inputs not sorted")
```

诀窍：在 **较短数组的切分位置** 上做二分，而不是在值上。

## 识别信号

- 「sorted array」、「sorted and rotated」、「find peak element」→ 经典二分。
- 「minimum time/cost/speed X such that...」、「smallest X such that...」、「is it possible to achieve K within X...」→ 对答案做二分。
- 「median of two sorted」、「k-th element of two sorted」→ 基于切分的二分。
- 「find first / last position of target in sorted array」→ `bisect_left` / `bisect_right`。
- 「search in 2D matrix where each row is sorted and first element of row > last of previous」→ 压成一维处理。

## 思考框架

1. **搜索空间有序或单调吗？** 是 → 二分。
2. **谓词 `ok(x)` 是什么？** 必须单调：`False, False, ..., True, True, ...`。
3. **`lo` 和 `hi` 取什么？** 选最小可行的 `lo`（或其再减一），选最大可行的 `hi`。
4. **`mid` 代表什么？** 一个候选答案。
5. **如何缩区间？** 不可行则 `lo = mid + 1`，可行则 `hi = mid`。循环在 `lo == hi` 时结束。
6. **边界情况：** 空数组、单元素、全部可行（lo 一开始就可行）、全部不可行（需要返回特殊值）。

## Hot 150 例题

- **704. Binary Search**：模式 2。
- **33. Search in Rotated Sorted Array**：模式 3。
- **153. Find Minimum in Rotated Sorted Array**：模式 4。
- **4. Median of Two Sorted Arrays**：模式 6。
- **74. Search a 2D Matrix**：压成一维。
- **278. First Bad Version**：谓词式：第一个满足 `isBadVersion(i)` 为 True 的版本。
- **162. Find Peak Element**：沿着梯度方向二分。
- **875. Koko Eating Bananas**：模式 5。
- **2064. Minimized Maximum of Products**：模式 5 加多店判定。
- **410. Split Array Largest Sum**：模式 5：可行性是「能否切分为 ≤ K 段且每段 ≤ mid」。
- **1011. Capacity To Ship Packages Within D Days**：模式 5。
- **774. Minimize Max Distance to Gas Station**：模式 5 在浮点答案上（用 `eps`）。
- **300. Longest Increasing Subsequence**：在 tails 数组上二分找插入位置。
- **35. Search Insert Position**：`bisect_left`。

## 易错点

- **`lo <= hi` 与 `lo < hi`：** 精确查找元素用 `<=`；对答案空间二分用 `<`。混用是死循环的最常见原因。
- **`mid = (lo + hi) // 2` 与 `(lo + hi + 1) // 2`：** 当 `hi = mid`（向上收紧）时，使用 **上偏的 mid** 避免在 `lo` 卡住。当 `lo = mid + 1` 时，标准的 `mid = (lo + hi) // 2` 就是对的。
- **`lo + hi` 整数溢出：** 在 Python 里不是问题（任意精度），但其他语言要用 `lo + (hi - lo) // 2`。
- **旋转数组中存在重复元素：** 当 `nums[lo] == nums[mid] == nums[hi]` 时，没法判断哪半有序，只能 `lo += 1` 和 `hi -= 1`（LC 81）。
- **浮点上的二分：** 用 `hi - lo < eps`（如 1e-6）作为循环结束条件，或固定迭代次数（如 100 次）。
- **谓词必须单调：** 谓词必须是 `False, False, True, True` 的形式。如果出现 `True, False, True`，二分就会失败。
- **`bisect_right` 与 `bisect_left` 的区别：** 当目标出现多次时，二者有区别。
- **旋转数组中 `nums[lo] <= nums[mid]` 与 `<` 的差异：** 用 `<` 会漏掉左半段全部相等的情况（一种全等的旋转）。