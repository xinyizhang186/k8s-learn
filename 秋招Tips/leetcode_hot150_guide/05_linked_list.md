# 05. 链表

## 核心概念

链表题的核心大多是 **指针操作**。三大要点：

1. **虚拟头节点** —— 在真实头节点之前再放一个哨兵节点，从而避免对"修改头节点"做特殊处理。
2. **快慢指针** —— 寻找中点、检测环、寻找倒数第 k 个节点。
3. **反转** —— 迭代式的三指针翻转；子链表用递归反转。

## 模式与模板

### 1. 虚拟头节点 —— 合并两个有序链表

```python
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val; self.next = next

def merge_two_lists(l1: ListNode | None, l2: ListNode | None) -> ListNode | None:
    dummy = ListNode()
    tail = dummy
    while l1 and l2:
        if l1.val <= l2.val:
            tail.next = l1; l1 = l1.next
        else:
            tail.next = l2; l2 = l2.next
        tail = tail.next
    tail.next = l1 if l1 else l2
    return dummy.next
```

### 2. 快慢指针 —— 寻找中点 / 检测环

```python
def middle_node(head: ListNode | None) -> ListNode | None:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next; fast = fast.next.next
    return slow                                  # 奇数 n：返回精确中点；偶数 n：返回第二个中点

def has_cycle(head: ListNode | None) -> bool:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next; fast = fast.next.next
        if slow is fast: return True
    return False
```

### 3. 倒数第 k 个 —— 快指针先走 k 步

```python
def remove_nth_from_end(head: ListNode | None, n: int) -> ListNode | None:
    dummy = ListNode(0, head)
    fast = slow = dummy
    for _ in range(n): fast = fast.next
    while fast.next:                              # 当 fast 走到最后一个节点时停止
        slow = slow.next; fast = fast.next
    slow.next = slow.next.next                    # 删除节点
    return dummy.next
```

### 4. 迭代反转

```python
def reverse_list(head: ListNode | None) -> ListNode | None:
    prev, cur = None, head
    while cur:
        nxt = cur.next
        cur.next = prev
        prev = cur; cur = nxt
    return prev
```

### 5. 反转子链表 [left, right]（1-indexed，即 1 起编号）

```python
def reverse_between(head: ListNode | None, left: int, right: int) -> ListNode | None:
    dummy = ListNode(0, head)
    pre = dummy
    for _ in range(left - 1): pre = pre.next      # 反转区间前的节点
    cur = pre.next
    for _ in range(right - left):                 # 把 cur.next 不断插入到区间头部
        nxt = cur.next
        cur.next = nxt.next
        nxt.next = pre.next
        pre.next = nxt
    return dummy.next
```

这种"头部插入"的技巧可以在原地完成反转，无需三指针交换 —— 每轮把 `cur.next` 移动到窗口的最前面。

### 6. 两数相加 —— 虚拟头节点 + 进位

```python
def add_two_numbers(l1: ListNode | None, l2: ListNode | None) -> ListNode | None:
    dummy = ListNode()
    tail = dummy
    carry = 0
    while l1 or l2 or carry:
        v = carry
        if l1: v += l1.val; l1 = l1.next
        if l2: v += l2.val; l2 = l2.next
        carry, d = divmod(v, 10)
        tail.next = ListNode(d); tail = tail.next
    return dummy.next
```

### 7. 重排链表（L0→Ln→L1→Ln-1→……）

寻找中点 → 反转后半段 → 交叉合并。由三个基础操作组合而成。

### 8. 复制带随机指针的链表 —— 哈希表或交错法

```python
def copy_random_list(head: 'Node | None') -> 'Node | None':
    if not head: return None
    # 第一步：克隆每个节点并将其穿插进去：A -> A' -> B -> B' -> ...
    cur = head
    while cur:
        nxt = cur.next
        cur.next = Node(cur.val, nxt, None)
        cur = nxt
    # 第二步：给克隆节点设置 random 指针
    cur = head
    while cur:
        if cur.random: cur.next.random = cur.random.next
        cur = cur.next.next
    # 第三步：拆开交错结构
    cur = head
    clone_head = head.next
    while cur:
        clone = cur.next
        cur.next = clone.next
        clone.next = clone.next.next if clone.next else None
        cur = cur.next
    return clone_head
```

交错法只占用 O(1) 额外空间（不计输出）。哈希表法更简单，在 Hot 150 中也是可接受的解法。

## 识别信号

- "merge sorted"、"add two numbers represented as lists"（合并有序链表、用链表表示的两数相加）→ 虚拟头节点 + 进位。
- "detect cycle"、"find middle"、"k-th from end"（检测环、找中点、倒数第 k 个）→ 快慢指针。
- "reverse list"、"reverse between"、"reorder"（反转链表、区间反转、重排）→ 反转基础操作的组合。
- "deep copy with random pointer"（带随机指针的深拷贝）→ 用哈希表保存 (原节点 → 克隆节点) 的映射，或使用交错法。
- "remove nth from end"、"rotate list by k"（删除倒数第 n 个、链表旋转 k 位）→ 虚拟头节点 + 偏移指针。
- "LRU cache"（LRU 缓存）→ 哈希表 + 双向链表（面试常考）。

## 思维框架

1. **会不会修改头节点？** 始终使用虚拟头节点。
2. **答案是否是相对于末尾的位置？** 用快慢指针 + 偏移量。
3. **是否在重构指针？** 先在纸上画出"之前"和"之后"的图；标出哪些指针会变、按什么顺序变化，避免丢失引用。
4. **能否分解成已有的基础操作？** 重排 = 找中点 + 反转 + 交叉合并。不要从零开始重新实现。
5. **边界情况：** 空链表、单节点链表、两节点链表、`k` 大于长度（旋转链表时取模）。

## Hot 150 例题

- **21. Merge Two Sorted Lists** —— 模式 1。
- **141. Linked List Cycle** —— 模式 2。
- **876. Middle of the Linked List** —— 模式 2。
- **19. Remove Nth Node From End** —— 模式 3。
- **206. Reverse Linked List** —— 模式 4。
- **92. Reverse Linked List II** —— 模式 5。
- **2. Add Two Numbers** —— 模式 6。
- **143. Reorder List** —— 模式 7。
- **138. Copy List With Random Pointer** —— 模式 8。
- **287. Find the Duplicate Number** —— 在值图上做 Floyd 环检测（把 `nums[i]` 当作 next 指针）。O(1) 空间，且不会修改输入。
- **146. LRU Cache** —— `dict[int, Node]` + 双向链表。`get` 与 `put` 均为 O(1)。

## 常见陷阱

- **反转之前一定要画图：** 原地反转会永久丢失 `next` 引用，务必先保存 `nxt = cur.next`。
- **快慢指针找中点的偏一错误：** 对于 `1->2->3->4->5`，标准的快慢指针返回 `3`（精确中点）。对于 `1->2->3->4`，返回 `3`（第二个中点）。如果你需要的是第一个中点，应当用 `while fast.next and fast.next.next`。
- **检测环检测的种类：** Floyd 算法返回的是环内的一个相遇点。要找到环的 *入口*，需要把其中一个指针重置为头节点，然后两指针同速前进 —— 它们会在入口处相遇。
- **删除倒数第 n 个节点：** 使用虚拟头节点，使"删除头节点"也能统一处理，无需特判。
- **旋转链表时 `k` 大于长度：** 先 `k %= n`；若 `k == 0`，直接返回原链表。
- **随机指针拷贝的交错法：** 拆开交错的步骤必须把原始的 `next` 指针恢复回去 —— 不要跳过这一步。
- **LRU 缓存：** 双向链表需要 `head` 和 `tail` 两个哨兵节点；每次重新插入到链表头部前，必须先删除该节点。