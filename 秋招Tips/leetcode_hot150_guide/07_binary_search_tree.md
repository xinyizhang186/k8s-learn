# 07. 二叉搜索树（BST）

## 核心概念

BST 按大小存储键值：对于任意节点，其左子树的所有键都 `< node.val`，右子树的所有键都 `> node.val`。由此得到：

- **中序遍历得到有序序列。**
- **查找 / 插入 / 删除均为 O(h)** —— 其中 `h` 为树高，平衡时为 `O(log n)`，退化为链表时为 `O(n)`。
- **两节点的最近公共祖先是它们在数值上夹住它们的第一个祖先。**
- **第 k 小 = 中序遍历的第 k 个节点。**

## 模式与模板

### 1. 验证 BST —— 中序单调性

```python
def is_valid_bst(root: TreeNode | None, low=float('-inf'), high=float('inf')) -> bool:
    if not root: return True
    if not (low < root.val < high): return False
    return (is_valid_bst(root.left, low, root.val)
            and is_valid_bst(root.right, root.val, high))
```

传入 `(low, high)` 区间的方法最简洁。中序的版本（检查每个值都比前一个大）也可以，有时调试起来更方便。

### 2. 中序遍历 —— 第 k 小元素

```python
def kth_smallest(root: TreeNode | None, k: int) -> int:
    stack: list[TreeNode] = []
    cur = root
    while cur or stack:
        while cur:
            stack.append(cur); cur = cur.left
        cur = stack.pop()
        k -= 1
        if k == 0: return cur.val
        cur = cur.right
    return -1                                    # 不会到达这里
```

迭代式中序可以 **提前结束**（弹出 k 次后即停），而递归式中序做不到。

### 3. BST 迭代器（均摊常数空间）

```python
class BSTIterator:
    def __init__(self, root: TreeNode | None):
        self.stack: list[TreeNode] = []
        self._push_left(root)

    def _push_left(self, node: TreeNode | None) -> None:
        while node:
            self.stack.append(node); node = node.left

    def next(self) -> int:
        node = self.stack.pop()
        self._push_left(node.right)              # 右子树的左链
        return node.val

    def has_next(self) -> bool:
        return bool(self.stack)
```

`next()` 是 **均摊 O(1)** —— 整个调用过程中，每个节点恰好入栈、出栈各一次。

### 4. 查找 / 插入 / 删除

```python
def search_bst(root: TreeNode | None, val: int) -> TreeNode | None:
    while root and root.val != val:
        root = root.left if val < root.val else root.right
    return root

def insert_into_bst(root: TreeNode | None, val: int) -> TreeNode:
    if not root: return TreeNode(val)
    if val < root.val: root.left = insert_into_bst(root.left, val)
    else: root.right = insert_into_bst(root.right, val)
    return root

def delete_node(root: TreeNode | None, key: int) -> TreeNode | None:
    if not root: return None
    if key < root.val: root.left = delete_node(root.left, key)
    elif key > root.val: root.right = delete_node(root.right, key)
    else:
        # 找到要删除的节点
        if not root.right: return root.left      # 没有右孩子：提升左子树
        if not root.left: return root.right      # 没有左孩子：提升右子树
        # 两个孩子：找中序后继（右子树中最小的节点）
        succ = root.right
        while succ.left: succ = succ.left
        root.val = succ.val                      # 交换值
        root.right = delete_node(root.right, succ.val)  # 删除后继
    return root
```

### 5. BST 中的最近公共祖先（比通用 LCA 更简洁）

```python
def lca_bst(root: TreeNode | None, p: TreeNode, q: TreeNode) -> TreeNode | None:
    while root:
        if p.val < root.val and q.val < root.val: root = root.left
        elif p.val > root.val and q.val > root.val: root = root.right
        else: return root                        # 分叉点 = LCA
    return None
```

### 6. 区间和 —— 带剪枝的 DFS

```python
def range_sum_bst(root: TreeNode | None, low: int, high: int) -> int:
    if not root: return 0
    if root.val < low: return range_sum_bst(root.right, low, high)   # 剪掉左子树
    if root.val > high: return range_sum_bst(root.left, low, high)  # 剪掉右子树
    return root.val + range_sum_bst(root.left, low, high) + range_sum_bst(root.right, low, high)
```

### 7. 有序数组转平衡 BST

```python
def sorted_array_to_bst(nums: list[int]) -> TreeNode | None:
    def build(lo: int, hi: int) -> TreeNode | None:
        if lo > hi: return None
        mid = (lo + hi) // 2
        return TreeNode(nums[mid], build(lo, mid - 1), build(mid + 1, hi))
    return build(0, len(nums) - 1)
```

**要点：** 取中点作为根。若总是取 `mid = (lo + hi) // 2`（偏左中点）或 `mid = (lo + hi + 1) // 2`（偏右中点），测试通常都接受。

### 8. BST 转有序双向链表（中序）

```python
def tree_to_doubly_list(root: TreeNode | None) -> TreeNode | None:
    if not root: return None
    dummy = TreeNode()
    prev = dummy
    def dfs(node: TreeNode | None) -> None:
        nonlocal prev
        if not node: return
        dfs(node.left)
        prev.right = node
        node.left = prev
        prev = node
        dfs(node.right)
    dfs(root)
    head = dummy.right                           # 第一个被访问的节点
    head.left = prev                             # 闭环
    prev.right = head
    return head
```

## 识别信号

- "binary search tree"、"BST"（二叉搜索树、BST）→ 利用 BST 性质剪枝。
- "k-th smallest/largest in a BST"（BST 中第 k 小/大）→ 迭代式中序遍历。
- "validate BST"、"is valid BST"（验证 BST、是否合法 BST）→ 带区间限制的递归，或中序单调性。
- "lowest common ancestor"（最近公共祖先）+ BST 保证 → 分叉点下行（5）。
- "balanced BST from sorted array"（有序数组转平衡 BST）→ 递归取中点。
- "range sum"、"in [low, high]"（区间和、落在 [low, high] 内）→ 带剪枝的 DFS（6）。
- "recover swapped nodes"（恢复被交换的两个节点）→ 中序扫描找两处逆序对。

## 思维框架

1. **题目是否用到 BST 性质？** 若是，每一步就可以剪掉一侧 → O(h)。
2. **是否需要有序序列？** 用中序遍历。
3. **是否需要改变结构？** 在中序过程中串一个 `prev` 指针 —— 与 `sorted_array_to_bst` 反过来用即可。
4. **边界情况：** 重复值（题意会说明是否允许）、单节点树、退化树（形似链表）。

## Hot 150 例题

- **98. Validate Binary Search Tree** —— 模式 1。
- **530. Minimum Absolute Difference in BST** —— 中序遍历，保存前一个值。
- **230. Kth Smallest Element in a BST** —— 模式 2。
- **108. Convert Sorted Array to BST** —— 模式 7。
- **235. Lowest Common Ancestor of a BST** —— 模式 5。
- **173. BST Iterator** —— 模式 3。
- **701. Insert into a BST** —— 模式 4。
- **450. Delete Node in a BST** —— 模式 4（最棘手的一个，多练）。
- **938. Range Sum of BST** —— 模式 6。
- **99. Recover Binary Search Tree** —— 中序遍历找两处逆序对。
- **426. Convert Binary Search Tree to Sorted Doubly Linked List** —— 模式 8。

## 常见陷阱

- **验证 BST 中等于 `node.val` 的情况：** BST 通常不允许相等的键，区间条件应为 `low < val < high`，而不是 `<=`。
- **整型边界：** 用 `float('-inf')` / `float('inf')` 是安全的。若用 `-2**31 - 1` 这类哨兵，当题目本身已经用到 INT_MIN 时可能溢出。
- **迭代式中序 vs 递归式中序：** 迭代式可以提前结束（第 k 小）。需要遍历所有节点时递归式更方便。
- **删除有两个孩子的节点：** 不要真的把后继节点搬过来；只复制它的值，再递归删除那个后继节点。
- **BST 的 LCA 不要假设 `p ≤ q`：** 写代码时要兼容两种顺序。
- **有序数组转 BST 的中点偏向：** `mid = (lo + hi) // 2` 在偶数元素时会让树左偏；偶数时另一写法则右偏。两种都可以。