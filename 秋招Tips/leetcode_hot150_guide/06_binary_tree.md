# 06. 二叉树 [深入]

这是你的薄弱环节之一。二叉树题是 **掌握递归思维模型** 最简单的地方，因为每道树题都能归结为一个问题：

> 每个节点需要从它的子树收集什么信息，才能算出自己这一层的"贡献"？

如果你能回答这个问题，你就能解决约 80% 的树题。

---

## 0. 那个能解锁一切的思维模型

二叉树问题本质上都是 **后序遍历的伪装**。先访问子节点、收集它们的答案，再在当前节点合并。不同的题目只是对每个子树所需的"答案"不同。

```python
# 通用树题模板 —— 其他树题都是这个模板的变体
def solve(root: TreeNode | None) -> Answer:
    if not root: return <base_answer>             # 空子树应该返回什么？
    left = solve(root.left)                       # 我需要从左子树得到什么？
    right = solve(root.right)                     # 我需要从右子树得到什么？
    return combine(root.val, left, right)         # 在当前节点如何合并？
```

每道树题都要问三个问题：

1. **"空子树返回什么？"** —— 通常是 0、None、[] 或 `(0, False)`，具体取决于题目。
2. **"叶子节点返回什么？"** —— 有时和空子树答案相同，有时是特殊情况。
3. **"每个节点根据子节点的答案算出什么？"** —— 这就是递推式。

如果根节点的返回值就是最终答案，那就直接返回它。如果答案 **藏在树中间某处**（例如树的直径、最大路径和），就需要在递归里维护一个 **全局变量**，而递归函数返回的是 **向上延伸的值**（即可以和父节点继续合并的那部分）。

---

## 1. 节点定义

```python
from __future__ import annotations

class TreeNode:
    def __init__(self, val=0, left: 'TreeNode | None'=None, right: 'TreeNode | None'=None):
        self.val = val
        self.left = left
        self.right = right
```

## 2. 遍历 —— 基础

你需要熟练掌握四种遍历顺序，包括递归和迭代两种写法。

### 2.1 递归版（简单但必会）

```python
def preorder(root):                               # 根、左、右
    if not root: return
    visit(root); preorder(root.left); preorder(root.right)

def inorder(root):                                # 左、根、右 —— BST 中即为有序序列
    if not root: return
    inorder(root.left); visit(root); inorder(root.right)

def postorder(root):                              # 左、右、根 —— 子节点先于父节点
    if not root: return
    postorder(root.left); postorder(root.right); visit(root)
```

### 2.2 层序遍历（BFS）

```python
from collections import deque

def level_order(root: TreeNode | None) -> list[list[int]]:
    if not root: return []
    out: list[list[int]] = []
    q: deque[TreeNode] = deque([root])
    while q:
        level: list[int] = []
        for _ in range(len(q)):                   # 快照当前层的节点数
            node = q.popleft()
            level.append(node.val)
            if node.left: q.append(node.left)
            if node.right: q.append(node.right)
        out.append(level)
    return out
```

### 2.3 迭代版的前序 / 中序（Hot 150 不要求 Morris 遍历）

```python
def preorder_iter(root: TreeNode | None) -> list[int]:
    out, stack = [], []
    cur = root
    while cur or stack:
        while cur:
            out.append(cur.val)                   # 入栈时访问
            stack.append(cur)
            cur = cur.left
        cur = stack.pop().right
    return out

def inorder_iter(root: TreeNode | None) -> list[int]:
    out, stack = [], []
    cur = root
    while cur or stack:
        while cur:
            stack.append(cur); cur = cur.left
        cur = stack.pop()
        out.append(cur.val)                       # 出栈时访问
        cur = cur.right
    return out
```

### 2.4 右视图

取每一层的最后一个节点：

```python
def right_side_view(root: TreeNode | None) -> list[int]:
    if not root: return []
    out: list[int] = []
    q: deque[TreeNode] = deque([root])
    while q:
        n = len(q)
        for i in range(n):
            node = q.popleft()
            if i == n - 1: out.append(node.val)
            if node.left: q.append(node.left)
            if node.right: q.append(node.right)
    return out
```

## 3. "子节点答案 → 父节点汇总"模式

这套模式可以解决：深度、高度、直径、平衡、最大路径和、反转、是否同树、是否子树、最深叶子子树等。

### 3.1 最大深度

```python
def max_depth(root: TreeNode | None) -> int:
    if not root: return 0
    return 1 + max(max_depth(root.left), max_depth(root.right))
```

**答案：** 当前节点的深度 = `1 + max(左, 右)`。根节点返回的值就是整棵树的深度。

### 3.2 直径（答案藏在树中间）

直径是 **任意两节点之间的最长路径**，它一定经过某个"最高"节点。在每个节点上，经过该节点的最长路径为 `left_depth + right_depth`。我们更新一个全局变量，但递归函数只返回 *向上延伸* 的深度。

```python
def diameter_of_binary_tree(root: TreeNode | None) -> int:
    ans = 0
    def depth(node: TreeNode | None) -> int:
        nonlocal ans
        if not node: return 0
        l = depth(node.left)
        r = depth(node.right)
        ans = max(ans, l + r)                      # 经过当前节点的路径
        return 1 + max(l, r)                       # 向上延伸的深度
    depth(root)
    return ans
```

**"全局更新 + 向上延伸返回值"** 是树题中最重要的一个模式。务必背熟。

### 3.3 平衡二叉树

```python
def is_balanced(root: TreeNode | None) -> bool:
    ok = True
    def height(node: TreeNode | None) -> int:
        nonlocal ok
        if not node: return 0
        l = height(node.left)
        r = height(node.right)
        if abs(l - r) > 1: ok = False
        return 1 + max(l, r)
    height(root)
    return ok
```

一种更快的方式是返回 `-1` 实现短路：

```python
def is_balanced(root: TreeNode | None) -> bool:
    def check(node: TreeNode | None) -> int:       # 不平衡则返回 -1
        if not node: return 0
        l = check(node.left)
        if l == -1: return -1
        r = check(node.right)
        if r == -1: return -1
        if abs(l - r) > 1: return -1
        return 1 + max(l, r)
    return check(root) != -1
```

### 3.4 最大路径和

和直径的骨架一样，只是把计数改成求和：

```python
def max_path_sum(root: TreeNode | None) -> int:
    ans = float('-inf')
    def gain(node: TreeNode | None) -> int:
        nonlocal ans
        if not node: return 0
        l = max(gain(node.left), 0)               # 忽略负贡献的子树
        r = max(gain(node.right), 0)
        ans = max(ans, node.val + l + r)          # 经过当前节点的路径
        return node.val + max(l, r)                # 向上延伸的单边最大贡献
    gain(root)
    return ans
```

### 3.5 同树 / 子树判断

```python
def is_same_tree(p: TreeNode | None, q: TreeNode | None) -> bool:
    if not p and not q: return True
    if not p or not q: return False
    return (p.val == q.val
            and is_same_tree(p.left, q.left)
            and is_same_tree(p.right, q.right))

def is_subtree(root: TreeNode | None, sub: TreeNode | None) -> bool:
    if not root: return False
    if is_same_tree(root, sub): return True
    return is_subtree(root.left, sub) or is_subtree(root.right, sub)
```

### 3.6 反转二叉树

```python
def invert_tree(root: TreeNode | None) -> TreeNode | None:
    if not root: return None
    root.left, root.right = invert_tree(root.right), invert_tree(root.left)
    return root
```

### 3.7 最近公共祖先（二叉树，没有父指针）

两种情况：

- 如果当前节点就是 `p` 或 `q`，它就是 LCA 候选（另一个节点可能在它的子树中）。
- 否则，递归到左右子树。如果两边都返回非空，当前节点就是 LCA；如果只有一边返回非空，则把该结果向上传递。

```python
def lca(root: TreeNode | None, p: TreeNode, q: TreeNode) -> TreeNode | None:
    if not root or root is p or root is q: return root
    l = lca(root.left, p, q)
    r = lca(root.right, p, q)
    if l and r: return root                       # 两边都匹配 -> 当前节点就是 LCA
    return l or r                                 # 把非空的一边向上传递
```

无论 `p` 是 `q` 的祖先还是反过来，只要 `p`、`q` 都保证在树中存在，该算法都能正确工作。

## 4. 路径问题 —— 维护更多状态

"路径"问题需要的状态超出了简单的"左+右"返回值。常见模式有：

### 4.1 根到叶子的路径和

```python
def has_path_sum(root: TreeNode | None, target: int) -> bool:
    if not root: return False
    if not root.left and not root.right:           # 叶子节点
        return root.val == target
    return (has_path_sum(root.left, target - root.val)
            or has_path_sum(root.right, target - root.val))
```

### 4.2 任意向下路径和等于目标值

这**不是**一道普通的树题，而是一道 **根到当前节点路径上前缀和** 的题。用一个哈希集合维护前缀和。

```python
def path_sum_iii(root: TreeNode | None, target: int) -> int:
    from collections import defaultdict
    count = 0
    prefix: dict[int, int] = defaultdict(int)
    prefix[0] = 1
    def dfs(node: TreeNode | None, cur: int) -> None:
        nonlocal count
        if not node: return
        cur += node.val
        count += prefix[cur - target]
        prefix[cur] += 1
        dfs(node.left, cur)
        dfs(node.right, cur)
        prefix[cur] -= 1                           # 回溯前缀和
    dfs(root, 0)
    return count
```

### 4.3 带约束的最大二叉树路径

对于"最长 Z 字形路径"、"最长同值路径"等题，每个子树需要返回 **两个值**：以左分支开头的最长路径、以右分支开头的最长路径。用它们的和更新全局答案。

```python
# 最长同值路径
def longest_univalue_path(root: TreeNode | None) -> int:
    ans = 0
    def dfs(node: TreeNode | None, parent_val: int) -> int:
        nonlocal ans
        if not node: return 0
        l = dfs(node.left, node.val)
        r = dfs(node.right, node.val)
        ans = max(ans, l + r)                      # 经过当前节点的同值路径
        if node.val == parent_val:
            return 1 + max(l, r)                    # 向上延伸
        return 0
    dfs(root, root.val if root else 0)
    return ans
```

## 5. 序列化

### 5.1 编码 / 解码二叉树（前序 + 空位标记）

```python
def serialize(root: TreeNode | None) -> str:
    out: list[str] = []
    def dfs(node: TreeNode | None) -> None:
        if not node:
            out.append('#')
            return
        out.append(str(node.val))
        dfs(node.left); dfs(node.right)
    dfs(root)
    return ','.join(out)

def deserialize(data: str) -> TreeNode | None:
    it = iter(data.split(','))
    def dfs() -> TreeNode | None:
        val = next(it)
        if val == '#': return None
        node = TreeNode(int(val))
        node.left = dfs()
        node.right = dfs()
        return node
    return dfs()
```

用 `'#'`（或任何哨兵）标记空孩子，这样树的结构才能被唯一还原。**前序** 是必须的 —— 你必须先知道根节点，才能处理它的子树。

### 5.2 层序序列化

思路相同，只是换成 BFS。适用于矮而宽的树。

## 6. 构造问题

构造题把遍历反过来：给定遍历结果，重建二叉树。

### 6.1 前序 + 中序

前序告诉你谁是根（第一个元素）；中序告诉你左右子树的分界。

```python
def build_tree(preorder: list[int], inorder: list[int]) -> TreeNode | None:
    idx_map = {v: i for i, v in enumerate(inorder)}
    pre_iter = iter(preorder)
    def build(lo: int, hi: int) -> TreeNode | None:
        if lo > hi: return None
        val = next(pre_iter)
        node = TreeNode(val)
        mid = idx_map[val]
        node.left = build(lo, mid - 1)
        node.right = build(mid + 1, hi)
        return node
    return build(0, len(inorder) - 1)
```

关键技巧：用同一个迭代器遍历前序数组，递归过程中它会自动前进 —— 每次 `next()` 都是前序中的下一个根。

### 6.2 中序 + 后序

后序的最后一个元素是根。从右向左遍历后序，先构造右子树。

## 7. 识别信号

| 题面中的关键词 | 对应模式 |
|---|---|
| "maximum depth"、"minimum depth"（最大/最小深度） | 递归深度（3.1） |
| "diameter"、"longest path between any two nodes"（直径、任意两节点最长路径） | 全局变量 + 向上延伸（3.2） |
| "is balanced"、"check subtree heights differ by ≤1"（是否平衡、子树高度差是否 ≤1） | 短路式高度（3.3） |
| "maximum path sum"、"best path"（最大路径和、最佳路径） | 全局变量 + 向上贡献（3.4） |
| "same tree"、"is subtree"、"is symmetric"（同树、子树、对称） | 直接递归（3.5） |
| "lowest common ancestor"、"find common ancestor"（最近公共祖先、找公共祖先） | LCA 后序（3.7） |
| "path sum equals target" 根到叶子（路径和等于目标） | 下行时减去（4.1） |
| "any path downward summing to target"（任意向下路径和等于目标） | 根路径上前缀和（4.2） |
| "level order"、"right side view"、"average of levels"（层序、右视图、每层均值） | BFS（2.2、2.4） |
| "serialize / deserialize"、"encode tree"（序列化/反序列化、编码树） | 前序 + 标记（5.1） |
| "construct from preorder + inorder"（由前序+中序构造） | 反向遍历（6.1） |
| "longest zigzag"、"univalue path"（最长 Z 字形、同值路径） | 返回两个值（4.3） |

## 8. 思维框架（卡壳时就回来重读）

1. **递归函数返回什么？** 高度？和？元组 `(深度, 计数)`？布尔？
2. **空子树返回什么？** 通常是 0、零元组、`False` 或 `None`。
3. **叶子节点返回什么？** 有时等于空子树答案，有时是 `node.val` 本身。
4. **答案是根节点的返回值，还是藏在树中间？**
   - 根节点返回值 → 直接 `return dfs(root)`。
   - 答案藏在中间 → 用 `nonlocal ans`，在 `dfs` 内部更新它，并返回向上延伸的值。
5. **如果左右子树都要贡献？** 求深度时用 `1 + max(l, r)`；求经过节点的路径时用 `l + r`。
6. **路径是否可以从任意节点开始？** 那就是"任意向下路径"问题 —— 转化为根路径上的前缀和问题（4.2）。
7. **写代码前**，先用一棵 4 节点的例子在纸上推演一遍。

## 9. 常见错误模式

1. **忘记写 `nonlocal ans`**：当答案在树中间时，全局变量会一直是 0。
2. **把根节点的返回值误当成答案**：当最佳路径并不经过根时，这种做法会出错。
3. **深度与边数的偏一错误：**"直径"统计的是边数（`l + r`）；"路径和"统计的是节点（`node.val + l + r`）。
4. **混淆 `is` 与 `==`：** 树节点身份比较应该用 `is`，值比较用 `==`。
5. **本该返回 `0` 却返回了 `None`：** 每个分支的返回类型要明确 —— 一个函数不能有时返回 int、有时返回 None。
6. **退化树上的递归深度：** 一条 10^4 节点的左链会撞上 Python 默认的 1000 递归上限。在文件开头加上 `sys.setrecursionlimit(10**6)`。
7. **遍历过程中修改树：** 如果一定要改树，返回新的子树根，不要在前序遍历中原地给子节点重新赋值（这样会丢失原结构）。
8. **PathSum III 的前缀和忘记回溯** → 会把没真正结束在当前节点的路径也算进去。
9. **LCA 中节点可能不存在：** 如果 `p` 或 `q` 不在树中，简单算法会返回错误的节点。需要加一遍验证，或者显式追踪"是否两个都找到了"。
10. **构造树时混用可变迭代器与下标：** 用列表下标作为外部状态没问题；用 Python 的 `iter()` 更优雅。两者不要混用。

## 10. 刷题清单 —— Hot 150 二叉树题

按以下顺序冷启动做题。目标是反复练习模式，直到能下意识地写出来。

| # | 题目 | 模式 |
|---|---------|---------|
| 1 | 226. Invert Binary Tree | 3.6 —— 直接递归 |
| 2 | 104. Maximum Depth of Binary Tree | 3.1 —— 递归深度 |
| 3 | 100. Same Tree | 3.5 —— 直接递归 |
| 4 | 572. Subtree of Another Tree | 3.5 —— 同树 + 递归 |
| 5 | 101. Symmetric Tree | 3.5 —— 在 (左, 镜像(右)) 上做同树判断 |
| 6 | 110. Balanced Binary Tree | 3.3 —— 短路式高度 |
| 7 | 543. Diameter of Binary Tree | 3.2 —— **全局变量 + 向上延伸**（核心模式） |
| 8 | 111. Minimum Depth | 3.1 —— 注意单子树的情形 |
| 9 | 222. Count Complete Tree Nodes | 在最右侧路径上做二分 |
| 10 | 199. Binary Tree Right Side View | 2.4 —— BFS |
| 11 | 102. Binary Tree Level Order | 2.2 —— BFS |
| 12 | 105. Construct Binary Tree from Preorder + Inorder | 6.1 |
| 13 | 297. Serialize and Deserialize Binary Tree | 5.1 |
| 14 | 235. LCA of BST | BST 变种（见文件 07） |
| 15 | 236. Lowest Common Ancestor of a Binary Tree | 3.7 |
| 16 | 124. Binary Tree Maximum Path Sum | 3.4 —— **全局变量 + 向上延伸** |
| 17 | 112. Path Sum | 4.1 —— 根到叶子 |
| 18 | 437. Path Sum III | 4.2 —— 根路径上前缀和 |
| 19 | 173. Binary Search Tree Iterator | 基于栈的中序遍历（见文件 07） |
| 20 | 230. Kth Smallest Element in a BST | 中序遍历（见文件 07） |
| 21 | 98. Validate Binary Search Tree | 中序遍历单调性（见文件 07） |
| 22 | 1448. Count Good Nodes in Binary Tree | 自顶向下传递当前最大值 |
| 23 | 1372. Longest ZigZag Path | 4.3 —— 返回两个值 |
| 24 | 687. Longest Univalue Path | 4.3 —— 返回两个值 |
| 25 | 662. Maximum Width of Binary Tree | 带下标编码的 BFS |
| 26 | 450. Delete Node in a BST | （见文件 07） |

**模式锁死计划：** 先做 1–6（直接递归），再做 7、16、22（**全局变量 + 向上延伸** 模式 —— 反复做直到不用思考就能写出来）。然后做 17–18（路径和家族）。最后再做其余题目。

---

## 最后的思维模型

每道二叉树题，先写出下面的骨架，再补全空缺：

```python
def solve(root: TreeNode | None) -> Answer:
    if not root: return BASE                       # 1. 空子树的答案
    left = solve(root.left)                       # 2. 递归左子树
    right = solve(root.right)                     # 3. 递归右子树
    if SOME_CONDITION: ans = max(ans, COMBINE)   # 4. 更新全局变量（可选）
    return UPWARD_EXTEND(root.val, left, right)  # 5. 向上延伸的返回值
```

如果你能根据题意填出 `BASE`、`COMBINE` 和 `UPWARD_EXTEND`，就已经把它解出来了。