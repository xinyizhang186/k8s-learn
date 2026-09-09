# 08. 堆 / 优先队列

## 核心概念

堆是一棵二叉树，维护着 **堆性质**：每个父节点 ≤（小顶堆）或 ≥（大顶堆）其子节点。Python 的 `heapq` 默认提供小顶堆。要实现大顶堆，把键取负即可。

关键操作（都是原地操作，基于列表）：

- `heapq.heapify(a)`：O(n) 建堆。
- `heapq.heappush(a, x)`：O(log n)。
- `heapq.heappop(a)`：O(log n)，弹出最小值。
- `heapq.heappushpop(a, x)`：先推入再弹出，比分开调用略快。
- `heapq.nlargest(k, a)`、`heapq.nsmallest(k, a)`：O(n log k)，内部维护一个大小为 k 的堆。

## 模式与模板

### 1. 前 K 个元素

```python
import heapq

def top_k_frequent(nums: list[int], k: int) -> list[int]:
    from collections import Counter
    cnt = Counter(nums)
    return heapq.nlargest(k, cnt.keys(), key=cnt.get)
    # 等价写法：heapq.nsmallest(k, cnt.keys(), key=lambda x: -cnt[x])
```

如果需要 **最坏情况 O(n) 的前 K 高频**，可以按频率桶排序：

```python
def top_k_frequent_linear(nums: list[int], k: int) -> list[int]:
    from collections import Counter
    cnt = Counter(nums)
    max_freq = max(cnt.values()) if cnt else 0
    buckets: list[list[int]] = [[] for _ in range(max_freq + 1)]
    for v, c in cnt.items():
        buckets[c].append(v)
    out: list[int] = []
    for f in range(max_freq, 0, -1):
        for v in buckets[f]:
            out.append(v)
            if len(out) == k: return out
    return out
```

### 2. 维护大小为 K 的堆：第 K 大的数据流

```python
class KthLargest:
    def __init__(self, k: int, nums: list[int]):
        self.k = k
        self.h: list[int] = nums
        heapq.heapify(self.h)
        while len(self.h) > k:                   # 只保留最大的 k 个
            heapq.heappop(self.h)

    def add(self, val: int) -> int:
        heapq.heappush(self.h, val)
        if len(self.h) > self.k:
            heapq.heappop(self.h)
        return self.h[0]                          # k 个最大元素中的最小值 = 第 K 大的元素
```

**要点：** 要找 **第 K 大** 的元素，维护一个大小为 K 的小顶堆。每次插入后，如果大小超过 K，就弹出最小值。堆顶始终是第 K 大的元素。

**对称地**，要找 **第 K 小** 的元素，维护一个大小为 K 的大顶堆（值取负）。

### 3. 合并 K 个有序流

```python
def merge_k_lists(lists: list[ListNode | None]) -> ListNode | None:
    dummy = ListNode()
    tail = dummy
    h: list[tuple[int, int, ListNode]] = []      # (val, list_idx, node)，list_idx 用来打破平局
    for i, node in enumerate(lists):
        if node: heapq.heappush(h, (node.val, i, node))
    while h:
        val, i, node = heapq.heappop(h)
        tail.next = node; tail = tail.next
        if node.next: heapq.heappush(h, (node.next.val, i, node.next))
    return dummy.next
```

**为什么要在堆键中加入链表下标：** Python 的堆按元组逐项比较，所以如果没有稳定的平局打破器，当两个 val 相等时，会继续比较 `ListNode` 对象（而它没有定义 `<`）。加入一个唯一下标后，比较到下标处就会停止，永远不会触碰到 `ListNode`。

### 4. 数据流的中位数：两个堆

维护一个大顶堆 `lo`（较小的一半）和一个小顶堆 `hi`（较大的一半），满足 `len(lo) == len(hi)` 或 `len(lo) == len(hi) + 1`。

```python
from heapq import heappush, heappop

class MedianFinder:
    def __init__(self):
        self.lo: list[int] = []                   # 大顶堆（值取负）
        self.hi: list[int] = []                   # 小顶堆

    def add_num(self, num: int) -> None:
        # 总是先插入 lo，再做平衡。
        heappush(self.lo, -num)
        heappush(self.hi, -heappop(self.lo))      # 把 lo 中最大的移到 hi
        if len(self.lo) < len(self.hi):           # 再平衡：lo 应 >= hi
            heappush(self.lo, -heappop(self.hi))

    def find_median(self) -> float:
        if len(self.lo) > len(self.hi): return float(self.lo[0] * -1)
        return (self.lo[0] * -1 + self.hi[0]) / 2.0
```

**要点：** `lo` 用大顶堆保存较小的一半，所以堆顶是较小一半的最大值（即左中位数）。`hi` 用小顶堆保存较大的一半，所以堆顶是较大一半的最小值（即右中位数）。先插入 `lo`，再把 `lo` 的最大值转移到 `hi`，最后再做平衡。

### 5. 懒删除：维护一个「待删除」计数器

如果你需要删除任意元素（而不是堆顶），`heapq` 不支持高效删除。可以使用 **懒删除**：把元素标记为已删除，等到它到达堆顶时再真正弹出。

```python
class HeapWithRemoval:
    def __init__(self):
        self.h: list[tuple[int, int]] = []        # (priority, id)
        self.to_delete: dict[int, int] = {}        # id -> 计数
        self.size = 0

    def push(self, prio: int, item_id: int) -> None:
        heapq.heappush(self.h, (prio, item_id))
        self.size += 1

    def remove(self, item_id: int) -> None:
        if item_id in self.to_delete: self.to_delete[item_id] += 1
        else: self.to_delete[item_id] = 1
        self.size -= 1

    def top(self) -> tuple[int, int] | None:
        while self.h and self.to_delete.get(self.h[0][1], 0) > 0:
            prio, item_id = heapq.heappop(self.h)
            self.to_delete[item_id] -= 1
            if self.to_delete[item_id] == 0: del self.to_delete[item_id]
        return self.h[0] if self.h else None
```

常用于滑动窗口中位数（LC 480）、调度类问题。

### 6. Dijkstra / Prim：基于堆的最短路径 / 最小生成树

完整算法见 `09_graph.md`，堆的部分只是把 `(dist, node)` 存进去，弹出最小的即可。

### 7. 有序矩阵中的第 K 小 / 第 K 小的数对和

这类题使用 **最佳优先搜索** 模式加堆：每次弹出当前最小元素，再把它的「邻居」推进堆。

```python
def kth_smallest_sorted_matrix(matrix: list[list[int]], k: int) -> int:
    n = len(matrix)
    h: list[tuple[int, int, int]] = []
    for r in range(n):
        heapq.heappush(h, (matrix[r][0], r, 0))
    for _ in range(k - 1):
        _, r, c = heapq.heappop(h)
        if c + 1 < n:
            heapq.heappush(h, (matrix[r][c + 1], r, c + 1))
    return h[0][0]
```

## 识别信号

- 「top K」、「k-th largest/smallest」→ 堆或快速选择。
- 「merge K sorted lists」、「smallest range covering elements from K lists」→ 堆存链表头。
- 「median in a stream」、「sliding window median」→ 两个堆。
- 「next closest」、「next nearest」、「K-th nearest」→ 基于堆的最佳优先搜索。
- 「dijkstra」、「shortest path with non-negative weights」→ 存 `(dist, node)` 的小顶堆。
- 「kth smallest pair/difference」→ 堆或对答案做二分（见第 10 篇）。

## 思考框架

1. **是不是 Top-K 问题？** 用 `heapq.nlargest` / `nlargest`，如果是数据流则用大小为 K 的堆。
2. **是数据流且需要任意删除？** 懒删除堆或有序容器（若允许，`from sortedcontainers import SortedList`）。
3. **是否在合并有序流？** 堆里存 `(head_val, list_id, head_node)`。
4. **同时需要最小和最大？** 两个堆（中位数模式）。
5. **时间/空间权衡？** 快速选择给出平均 O(n) 的 Top-K，不需要额外 O(k) 空间。

## Hot 150 例题

- **703. Kth Largest Element in a Stream**：模式 2。
- **347. Top K Frequent Elements**：模式 1。
- **215. Kth Largest Element in an Array**：模式 2 或快速选择（平均 O(n)）。
- **973. K Closest Points to Origin**：`heapq.nsmallest(k, points, key=dist)` 或快速选择。
- **23. Merge K Sorted Lists**：模式 3。
- **295. Find Median from Data Stream**：模式 4。
- **378. Kth Smallest in a Sorted Matrix**：模式 7。
- **502. IPO**：按 capital 排序，用大顶堆装不超过当前 capital 的利润。
- **1642. Furthest Building You Can Reach**：用小顶堆存最大的梯子使用。
- **355. Design Twitter**：每个关注者的最近推文组成堆（模式 3 加上时间戳）。
- **373. Find K Pairs with Smallest Sums**：模式 7（每个 `(i, j)` 的邻居是 `(i+1, j)` 和 `(i, j+1)`）。
- **1046. Last Stone Weight**：大顶堆，弹出两个再推入差值。
- **253. Meeting Rooms II**：小顶堆存会议结束时间（与 `15_intervals.md` 关联）。

## 易错点

- **元组比较会一路穿透到对象：** 如果堆里存的是 `(val, node)`，val 相等时 Python 会去比较 `node`，而 `ListNode` 没定义该运算符。一定要插入唯一的平局打破器，比如 `(val, list_id, node)` 或中间夹一个 `(val, i, j)`。
- **小顶堆与大顶堆混淆：** `heapq` 只有小顶堆。要用大顶堆，数字取负，或存 `(-priority, item)`，弹出时再翻转符号。
- **中位数插入顺序：** 先推入 `lo`，再把 `lo` 堆顶推入 `hi`，最后再平衡。如果跳过再平衡，`lo` 会比 `hi` 还少，中位数就错了。
- **`heapq.nsmallest` 与排序：** 当 `k << n` 时，`nsmallest` 是 O(n log k)，比 `sorted(a)[:k]` 的 O(n log n) 快。当 `k ≈ n` 时，直接排序即可。
- **懒删除堆必须在 `top()` 返回前清理。** 懒删除的核心就是延迟清理，如果不在 top 检查，会返回陈旧条目。
- **浮点键值优先级相同时：** 加一个计数器打破平局，避免浮点带来比较不稳定的问题。