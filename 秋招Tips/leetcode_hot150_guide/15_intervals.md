# 15. 区间

## 核心概念

区间是一对 `[start, end]`。最常见的操作包括：

1. **按起点排序**（或按终点排序）—— 排序之后大部分区间问题都会变得简单。
2. **合并重叠区间** —— 扫描并不断扩展当前右端点。
3. **插入新区间** —— 找到重叠部分，合并，再放回。
4. **会议室问题** —— 通过堆或扫描线统计重叠数。

## 模式与模板

### 1. 合并区间

```python
def merge(intervals: list[list[int]]) -> list[list[int]]:
    intervals.sort()                              # 按 (start, end) 排序
    out: list[list[int]] = []
    for s, e in intervals:
        if out and s <= out[-1][1]:              # 与最后一个已合并区间重叠
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
```

### 2. 插入区间

```python
def insert(intervals: list[list[int]], new_interval: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    i = 0
    n = len(intervals)
    ns, ne = new_interval
    # 阶段 1：完全位于 new_interval 之前的区间
    while i < n and intervals[i][1] < ns:
        out.append(intervals[i]); i += 1
    # 阶段 2：与 new_interval 重叠的区间 —— 进行合并
    while i < n and intervals[i][0] <= ne:
        ns = min(ns, intervals[i][0])
        ne = max(ne, intervals[i][1])
        i += 1
    out.append([ns, ne])
    # 阶段 3：完全位于之后的区间
    while i < n:
        out.append(intervals[i]); i += 1
    return out
```

### 3. Meeting Rooms I —— 能否参加所有会议？

按起点排序，检查相邻区间是否重叠：

```python
def can_attend_meetings(intervals: list[list[int]]) -> bool:
    intervals.sort()
    for i in range(1, len(intervals)):
        if intervals[i][0] < intervals[i - 1][1]: return False
    return True
```

### 4. Meeting Rooms II —— 最少需要的会议室数

```python
def min_meeting_rooms(intervals: list[list[int]]) -> int:
    import heapq
    starts = sorted(i[0] for i in intervals)
    ends   = sorted(i[1] for i in intervals)
    i = j = 0
    rooms = max_rooms = 0
    while i < len(starts):
        if starts[i] < ends[j]:
            rooms += 1; i += 1
        else:
            rooms -= 1; j += 1
        max_rooms = max(max_rooms, rooms)
    return max_rooms
```

双指针扫描：遇到起点需要开新房间；遇到终点释放一间。把两个数组分别排序即可。

另一种用堆维护结束时间的写法（对某些人来说更直观）：

```python
def min_meeting_rooms(intervals: list[list[int]]) -> int:
    import heapq
    intervals.sort()
    heap: list[int] = []                           # 当前正在进行的会议的结束时间
    max_rooms = 0
    for s, e in intervals:
        while heap and heap[0] <= s:               # 在该会议开始前已结束的会议
            heapq.heappop(heap)
        heapq.heappush(heap, e)
        max_rooms = max(max_rooms, len(heap))
    return max_rooms
```

### 5. 无重叠区间 —— 最少删除数

等价于求**最多能保留多少个互不重叠的区间**（按终点贪心），再用总数减去。

```python
def erase_overlap_intervals(intervals: list[list[int]]) -> int:
    intervals.sort(key=lambda x: x[1])            # 按 END 排序
    end = float('-inf')
    keep = 0
    for s, e in intervals:
        if s >= end:                               # 与上一个保留的不重叠
            keep += 1; end = e
    return len(intervals) - keep
```

**贪心原则：** 总是保留结束时间最早的区间，这样能给后续留出最大空间。

### 6. 区间列表的交集

```python
def interval_intersection(first: list[list[int]], second: list[list[int]]) -> list[list[int]]:
    i = j = 0
    out: list[list[int]] = []
    while i < len(first) and j < len(second):
        lo = max(first[i][0], second[j][0])
        hi = min(first[i][1], second[j][1])
        if lo <= hi: out.append([lo, hi])
        if first[i][1] < second[j][1]: i += 1
        else: j += 1
    return out
```

### 7. 汇总区间 / 缺失区间

```python
def summary_ranges(nums: list[int]) -> list[str]:
    if not nums: return []
    out: list[str] = []
    start = nums[0]
    for i in range(1, len(nums)):
        if nums[i] != nums[i - 1] + 1:
            out.append(f"{start}->{nums[i - 1]}" if start != nums[i - 1] else str(start))
            start = nums[i]
    out.append(f"{start}->{nums[-1]}" if start != nums[-1] else str(start))
    return out
```

### 8. 天际线问题

用扫描线配合最大堆维护当前活动的高度。每个事件是 `(x, height_change)`。在每个 x 处更新堆，并记录当前最大高度（如果发生变化）。

```python
def get_skyline(buildings: list[list[int]]) -> list[list[int]]:
    import heapq
    events: list[tuple[int, int]] = []
    for l, r, h in buildings:
        events.append((l, -h))                     # 起始事件（取负表示"开始"）
        events.append((r, h))                      # 结束事件
    events.sort()
    heap: list[int] = [0]                          # 当前活动的高度（通过取负实现最大堆）
    removed: dict[int, int] = {}                   # 懒删除计数器
    prev_max = 0
    out: list[list[int]] = []
    i = 0
    while i < len(events):
        x = events[i][0]
        while i < len(events) and events[i][0] == x:
            _, h = events[i]
            if h < 0: heapq.heappush(heap, h)      # 开始：压入负值
            else: removed[-h] = removed.get(-h, 0) + 1   # 结束：标记待删除
            i += 1
        while heap and removed.get(heap[0], 0) > 0:    # 弹出已过期的
            removed[heap[0]] -= 1
            heapq.heappop(heap)
        cur_max = -heap[0] if heap else 0
        if cur_max != prev_max:
            out.append([x, cur_max]); prev_max = cur_max
    return out
```

## 识别信号

- "合并区间"、"无重叠"、"最少房间/资源数" → 排序 + 扫描。
- "将区间插入已排序列表" → 三阶段插入。
- "区间列表的交集" → 在两个已排序列表上用双指针。
- "天际线"、"建筑物轮廓" → 扫描线 + 带懒删除的最大堆。
- "射气球"、"划分字母区间" → 贪心的区间合并。

## 思考框架

1. **区间列表已排序吗？** 如果没有，先排序（按起点或终点，取决于题目）。
2. **"重叠"如何定义？** `[a, b]` 与 `[c, d]` 重叠当且仅当 `a <= d and c <= b`。对于刚好相接的区间（`a == d`），是否算重叠要看题目。
3. **能否贪心？** 按终点排序并保留最早结束的区间，是最常见的贪心策略。
4. **是否用扫描线？** 把每个区间转成两个事件（开始，+1）和（结束，-1），按 x 排序，再依次处理。
5. **是否需要求任意时刻的最大重叠数？** 用一个堆维护当前所有打开区间的结束时间。

## Hot 150 例题

- **56. Merge Intervals** —— 模式 1。
- **57. Insert Interval** —— 模式 2。
- **435. Non-overlapping Intervals** —— 模式 5。
- **252. Meeting Rooms** —— 模式 3。
- **253. Meeting Rooms II** —— 模式 4。
- **986. Interval List Intersections** —— 模式 6。
- **228. Summary Ranges** —— 模式 7。
- **452. Minimum Number of Arrows to Burst Balloons** —— 与模式 5 类似，但相接的判定用 `>` 而非 `>=`。
- **763. Partition Labels** —— 找到每个字符最后出现的位置，再合并区间。
- **352. Data Stream as Disjoint Intervals** —— 用 `SortedList` 或二分查找确定插入点。
- **218. The Skyline Problem** —— 模式 8。
- **1854. Maximum Population Year** —— 扫描线（或者直接按年份桶统计）。

## 常见陷阱

- **排序键：** 合并 / 插入 / 会议室问题按 `start` 排序；"最多不重叠"问题按 `end` 排序。混用会得到错误答案。
- **相接的区间：** `[1, 2]` 和 `[2, 3]` 是否算重叠要看题意。Meeting Rooms II 通常认为它们不重叠（一个在 2 结束，另一个在 2 开始）。`<=` 和 `<` 的选择要慎重。
- **空输入或单区间** —— 当列表可能为空时，要防止访问 `intervals[0]` 越界。
- **天际线的同 x 多事件：** 在同一个 x 处要把所有事件一起处理完（先处理开始事件），再取新的最大值，否则会记录出虚假的小峰。
- **天际线的懒删除** —— 如果不删除已经过期的高度，`heap[0]` 可能指向一栋已经结束的建筑。
- **Meeting Rooms II：要把开始和结束事件都纳入**，相同时刻按 (时间，结束事件优先) 排序——这样在 T 时刻结束的事件会在 T 时刻开始的事件之前处理（即 T 时刻结束的会议能腾出房间给 T 时刻开始的会议）。
- **元组排序的稳定性：** `[(1, 2), (1, 3)]` 用 `lambda x: x[0]` 排序时，相同键会保持原顺序——大多数情况没问题，但如果需要特定次序，要把 tiebreak 加进 key。
