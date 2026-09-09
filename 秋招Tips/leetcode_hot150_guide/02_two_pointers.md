# 02. 双指针

## 核心概念

双指针把 **有序数组**、**回文**、**容器** 类问题中的 O(n²) 暴力解法降到 O(n)。有三种形态：

1. **对撞指针（opposite-direction）** —— 左指针=0、右指针=n-1，向中间移动。有序数组两数之和、盛最多水的容器、验证回文。
2. **快慢指针（fast-slow，龟兔赛跑）** —— 两个指针都从 0 出发，一个跑得快。删除重复项、检测环、寻找中点。
3. **有序数组上的 k-sum 双指针** —— 外层固定 k-2 个元素，最后两个用双指针。

## 模式与模板

### 1. 对撞指针 —— 有序数组两数之和

```python
def two_sum_sorted(nums: list[int], target: int) -> list[int]:
    l, r = 0, len(nums) - 1
    while l < r:
        cur = nums[l] + nums[r]
        if cur == target: return [l, r]
        if cur < target: l += 1
        else: r -= 1
    return []
```

### 2. 对撞指针 —— 盛最多水的容器

```python
def max_area(height: list[int]) -> int:
    l, r, best = 0, len(height) - 1, 0
    while l < r:
        best = max(best, (r - l) * min(height[l], height[r]))
        if height[l] < height[r]: l += 1
        else: r -= 1
    return best
```

背后的原理：移动较高的那一边永远无法让面积增大（宽度变小，而高度受制于较短的那边），所以总是移动较短的那一边。

### 3. 快慢指针 —— 原地删除重复项

```python
def remove_duplicates(nums: list[int]) -> int:
    slow = 0                                    # 写入位置
    for fast in range(1, len(nums)):
        if nums[fast] != nums[slow]:
            slow += 1
            nums[slow] = nums[fast]
    return slow + 1
```

### 4. 有序数组上的三数之和（k-sum 模板）

```python
def three_sum(nums: list[int]) -> list[list[int]]:
    nums.sort()
    out: list[list[int]] = []
    n = len(nums)
    for i in range(n - 2):
        if i > 0 and nums[i] == nums[i - 1]: continue         # 去重 i
        l, r = i + 1, n - 1
        while l < r:
            s = nums[i] + nums[l] + nums[r]
            if s < 0: l += 1
            elif s > 0: r -= 1
            else:
                out.append([nums[i], nums[l], nums[r]])
                while l < r and nums[l] == nums[l + 1]: l += 1
                while l < r and nums[r] == nums[r - 1]: r -= 1
                l += 1; r -= 1
    return out
```

### 5. 快慢指针检测链表 / 序列中的环

```python
def has_cycle(head) -> bool:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast: return True
    return False
```

### 6. 回文判定

```python
def is_palindrome(s: str) -> bool:
    l, r = 0, len(s) - 1
    while l < r:
        while l < r and not s[l].isalnum(): l += 1
        while l < r and not s[r].isalnum(): r -= 1
        if s[l].lower() != s[r].lower(): return False
        l += 1; r -= 1
    return True
```

## 识别信号

- "sorted array" + "两个元素做某事" → 对撞指针。
- "container/area/water/trapping with two sides" → 对撞指针。
- "valid palindrome" → 对撞指针。
- "remove duplicates in place"、"move zeros to end" → 快慢指针（读/写指针）。
- "3Sum"、"4Sum" → 排序 + 嵌套双指针。
- "cycle in linked list" / "happy number" → 龟兔赛跑。

## 思考框架

1. **数组是否有序？**
   - 有序 → 两数之和 / 区间查询使用对撞双指针。
   - 无序 → 如果是两数之和，用 hash（文件 01）。如果允许先排序，就先排序——很多问题可以化为 O(n log n) + O(n)。
2. **你是否在做原地去重 / 分区 / 压缩？** → 快慢指针（读指针在前，写指针在后）。
3. **是否存在"两个边界"的几何问题**（容器、面积、接雨水）？ → 对撞指针 + 贪心移动。
4. **是否出现 k-sum？** → 排序 + 递归直到 2sum（k=2 作为基础情形）。

## Hot 150 例题

- **11. Container With Most Water** —— 模式 2。
- **15. 3Sum** —— 模式 4。
- **125. Valid Palindrome** —— 模式 6。
- **167. Two Sum II (sorted)** —— 模式 1。
- **283. Move Zeroes** —— 快慢指针：先写非零元素，再把后面填零。
  ```python
  def move_zeroes(nums: list[int]) -> None:
      w = 0
      for x in nums:
          if x != 0:
              nums[w] = x; w += 1
      for i in range(w, len(nums)): nums[i] = 0
  ```
- **392. Is Subsequence** —— 快慢指针：在目标串上设指针，每次匹配成功就前进。
- **42. Trapping Rain Water** —— 对撞指针或单调栈（文件 04），对撞指针更简洁：
  ```python
  def trap(height: list[int]) -> int:
      l, r = 0, len(height) - 1
      lmax = rmax = 0
      ans = 0
      while l < r:
          if height[l] < height[r]:
              lmax = max(lmax, height[l])
              ans += lmax - height[l]
              l += 1
          else:
              rmax = max(rmax, height[r])
              ans += rmax - height[r]
              r -= 1
      return ans
  ```

## 易错点

- **3Sum 去重：** 在找到三元组 *之后* 去重（同时跳过 `l` 和 `r` 上连续相等的值），并且在外层 `i` 循环也要去重（`if i > 0 and nums[i] == nums[i-1]: continue`）。
- **容器面积公式用的是 `min(h[l], h[r])`，不是 `max`。**
- **双指针要求"有序"的前提：** 如果数组无序且题目允许，就先排序。如果排序会破坏答案（例如需要返回原始下标），就用哈希。
- **差一错误：** 用 `while l < r`（不是 `<=`）——当 `l == r` 时两指针已经重合，没有配对。
- **删除重复项的返回值** 是 *新的长度*，不是下标。如果 slow 指向 *最后写入的位置*，记得 `+1`。