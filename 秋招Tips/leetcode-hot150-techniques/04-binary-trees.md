# 04 · 二叉树实战与避坑

> 已刷过一遍 Hot 150,但二叉树"非常薄弱"。本文直接进入:识别信号 → 两大思维(遍历 vs 分治)→ 子模式全家桶(含 Morris、LCA 三种、BST 性质、路径和前缀和)→ 避坑 → 速记。
> 心法:**二叉树题只有一个核心问题——"递归函数返回什么,以及在哪里更新答案"。** 想清这两点,90% 的树题能写。

```python
# 节点定义(全文统一)
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right
```

---

## 一、识别信号

| 题目特征 | 推荐技法 |
|---|---|
| "深度""直径""平衡""最大路径和" | **分治 + 全局 ans 更新** |
| "层序""右视图""锯齿" | **BFS 层序** |
| "前中后序" + "迭代" | **栈式遍历** |
| "序列化""重建二叉树" | **前序/层序 + 递归构建** |
| "BST + 验证/查找/删除/恢复" | **中序有序性** |
| "最近公共祖先" | **LCA 三种变体** |
| "路径和""目标和" | **DFS + 前缀和** |
| "填充右侧指针" | **BFS / 链表式** |
| "二叉树最大路径和" | **后序 + 全局 ans** |
| Trie / 字典树 | 见 `02-strings.md` 3.7 |

---

## 二、心智模型 — 两大思维(CRITICAL)

### 2.1 遍历思维(回溯 on tree)

**特征**:用一条递归路径"游走"整棵树,沿途记录答案,递归**无返回值**或返回布尔判定。常配合全局变量。

```python
ans = 0
def traverse(node):
    if not node: return
    # 处理当前(前序位置)
    traverse(node.left)
    # 处理当前(中序位置)
    traverse(node.right)
    # 处理当前(后序位置)
```
适用:路径枚举、路径和、所有路径、二叉搜索树迭代器。

### 2.2 分治思维(后序整合子树信息)

**特征**:递归**有返回值**,把左右子树的结果整合后返回给父节点。**这是树形 DP 的基础**。

```python
def solve(node):
    if not node: return base_case
    left = solve(node.left)
    right = solve(node.right)
    return combine(node.val, left, right)
```
适用:最大深度、直径、平衡、最大路径和、LCA。

### 2.3 关键决策点 — "返回值 vs 全局 ans"(最常错的地方)

很多题需要**两种值同时用**:
- **返回值**:递归给父节点用(局部、自底向上)
- **全局 ans**:在递归过程中更新(全局、最终答案)

**经典案例 — 二叉树直径(543)**:
```python
def diameterOfBinaryTree(root):
    ans = 0
    def depth(node):
        nonlocal ans
        if not node: return 0
        l = depth(node.left)
        r = depth(node.right)
        # 全局 ans:经过 node 的最长路径 = 左深 + 右深
        ans = max(ans, l + r)
        # 返回值:node 的最大深度(给父节点用)
        return max(l, r) + 1
    depth(root)
    return ans
```
**为什么返回深度而答案记直径?** 因为父节点需要"子树深度"来组合自己的直径,但题目要的是直径不是深度。返回值服务递归,全局 ans 服务答案。

> ⚠️ **这是二叉树最重要的一个 callout**:看到"求最值但递归返回的不是这个最值" → 99% 是"返回值 + 全局 ans"模式。

---

## 三、子模式全家桶

### 3.1 遍历(前/中/后/层序 + Morris + 迭代栈)

**递归版(最简单)**:
```python
def preorder_rec(root):
    if not root: return
    print(root.val)        # 前序位置
    preorder_rec(root.left)
    preorder_rec(root.right)

def inorder_rec(root):
    if not root: return
    inorder_rec(root.left)
    print(root.val)        # 中序位置
    inorder_rec(root.right)
```

**迭代统一写法**(前/中/后都用一个模板,关键在于"何时访问"与空指针标记):
```python
def preorder_iter(root):
    """前序迭代:栈"""
    if not root: return []
    stack, res = [root], []
    while stack:
        node = stack.pop()
        res.append(node.val)
        if node.right: stack.append(node.right)   # 右先入栈(后出)
        if node.left:  stack.append(node.left)    # 左后入栈(先出)
    return res

def inorder_iter(root):
    """中序迭代:一路向左压栈"""
    res, stack = [], []
    cur = root
    while cur or stack:
        while cur:
            stack.append(cur)
            cur = cur.left
        cur = stack.pop()
        res.append(cur.val)
        cur = cur.right
    return res
```

**Morris 遍历(O(1) 空间)** — 中序为例:
```python
def morris_inorder(root):
    res = []
    cur = root
    while cur:
        if not cur.left:
            res.append(cur.val)        # 左空 → 访问 → 向右
            cur = cur.right
        else:
            # 找 cur 左子树的最右节点(前驱)
            pred = cur.left
            while pred.right and pred.right != cur:
                pred = pred.right
            if not pred.right:
                pred.right = cur        # 临时线索
                cur = cur.left
            else:
                pred.right = None       # 拆线索
                res.append(cur.val)     # 第二次到达 → 访问
                cur = cur.right
    return res
```
**原理**:利用空闲的右指针做"线索"回到祖先,省去栈。中序访问时机 = 左子树处理完(第一次到达设线索,第二次到达拆线索并访问)。

**层序 BFS**:
```python
from collections import deque
def levelOrder(root):
    if not root: return []
    q = deque([root])
    res = []
    while q:
        level = []
        for _ in range(len(q)):       # 分层关键
            node = q.popleft()
            level.append(node.val)
            if node.left:  q.append(node.left)
            if node.right: q.append(node.right)
        res.append(level)
    return res
```
**变体**:103 锯齿层序(偶数层 `level[::-1]`)、199 右视图(每层取 `level[-1]`)。

**Hot 150 真题**:144/94/145 三序、102 层序、103 锯齿、199 右视图、173 BST 迭代器(中序栈缓式)。

### 3.2 分治 — 深度/直径/平衡/路径和

**最大深度(104)**:
```python
def maxDepth(root):
    if not root: return 0
    return 1 + max(maxDepth(root.left), maxDepth(root.right))
```

**平衡二叉树(110)** — 自底向上 `O(n)`:
```python
def isBalanced(root):
    def height(node):
        if not node: return 0
        l = height(node.left)
        r = height(node.right)
        if l == -1 or r == -1 or abs(l - r) > 1:
            return -1            # -1 表示"不平衡",向上传播
        return 1 + max(l, r)
    return height(root) != -1
```
⚠️ 自顶向下递归会 `O(n²)`(每节点重复算高度)。**自底向上用 -1 标记不平衡,一次 DFS `O(n)`**。

**二叉树最大路径和(124)** — 经典"返回值 + 全局 ans":
```python
def maxPathSum(root):
    ans = float('-inf')
    def gain(node):
        nonlocal ans
        if not node: return 0
        # 负贡献舍弃(取 max(0, x))
        l = max(gain(node.left), 0)
        r = max(gain(node.right), 0)
        # 全局:经过 node 的倒 V 形路径
        ans = max(ans, node.val + l + r)
        # 返回值:以 node 为端点的最大单链(给父用)
        return node.val + max(l, r)
    gain(root)
    return ans
```
**关键**:`gain` 返回"单链",`ans` 记录"倒 V 形路径"。两者是不同概念,这是返回值/全局区分的极致体现。

### 3.3 路径家族

**Hot 150 真题 + 思路**:

| 题 | 解法要点 |
|---|---|
| 112 路径总和 | DFS 递归,叶节点判 `target == node.val` |
| 113 路径总和 II | DFS + 回溯 `path.append/pop` |
| 437 路径总和 III | **前缀和 + 哈希**,任意路径 ↓ |
| 687 最长同值路径 | 后序返回"同值单链",全局记"倒 V" |
| 124 最大路径和 | 见 3.2 |

**模板 — 路径总和 III(437)前缀和**:
```python
def pathSum(root, target):
    from collections import defaultdict
    prefix = defaultdict(int)
    prefix[0] = 1
    ans = 0
    def dfs(node, cur):
        nonlocal ans
        if not node: return
        cur += node.val
        # 找前缀和 cur - target 的出现次数,即为以当前节点为尾的合法路径数
        ans += prefix[cur - target]
        prefix[cur] += 1
        dfs(node.left, cur)
        dfs(node.right, cur)
        prefix[cur] -= 1            # 回溯撤销
    dfs(root, 0)
    return ans
```
**原理**:与数组的"和为 K 的子数组"完全同构 —— 把"根到当前节点"看作数组前缀和,树上任意"向下路径" = 两个前缀和之差。

⚠️ **避坑**:树上前缀和**必须回溯撤销**(因为路径只能从父到子,不能跨分支)。这是与数组前缀和最大的不同。

### 3.4 构建 — 从遍历还原 + 序列化

**从前序与中序构造(105)**:
```python
def buildTree(preorder, inorder):
    """前序定根,中序分左右"""
    idx_map = {v: i for i, v in enumerate(inorder)}   # 中序值→下标,O(1) 查
    pre_iter = iter(preorder)
    def build(l, r):
        if l > r: return None
        val = next(pre_iter)         # 前序下一个 = 根
        root = TreeNode(val)
        mid = idx_map[val]
        root.left = build(l, mid - 1)
        root.right = build(mid + 1, r)
        return root
    return build(0, len(inorder) - 1)
```
**核心**:前序第一个是根,在中序里找到根的位置 → 左边是左子树、右边是右子树 → 递归。用哈希表存中序值的位置避免 `O(n)` 线性查找 → 整体 `O(n)`。

**从中序与后序构造(106)**:类似,根在后序**末尾**。

**有序数组转 BST(108)**:
```python
def sortedArrayToBST(nums):
    def build(l, r):
        if l > r: return None
        mid = (l + r) // 2            # 取中点为根保证平衡
        root = TreeNode(nums[mid])
        root.left = build(l, mid - 1)
        root.right = build(mid + 1, r)
        return root
    return build(0, len(nums) - 1)
```

**序列化与反序列化(297)**:
```python
class Codec:
    def serialize(self, root):
        """前序 + '#' 标空"""
        if not root: return '#'
        return f"{root.val},{self.serialize(root.left)},{self.serialize(root.right)}"

    def deserialize(self, data):
        """用迭代器消费"""
        it = iter(data.split(','))
        def build():
            v = next(it)
            if v == '#': return None
            root = TreeNode(int(v))
            root.left = build()
            root.right = build()
            return root
        return build()
```
⚠️ `'#'` 必须标记空节点,否则无法唯一还原(否则不知道左右子树何时为空)。也可用层序序列化,但前序写法更简洁。

### 3.5 BST 性质

BST 中序 = 升序。这是所有 BST 题的根。

**验证 BST(98)** — 用"上下界"法 `O(n)`:
```python
def isValidBST(root):
    def check(node, low, high):
        if not node: return True
        if not (low < node.val < high): return False
        return check(node.left, low, node.val) and check(node.right, node.val, high)
    return check(root, float('-inf'), float('inf'))
```
⚠️ 不能用"左 < 根 < 右"局部判断!必须**整棵子树的值都在范围内**(否则 `[5,1,4,null,null,3,6]` 这种会误判)。上下界法传递的就是"子树必须落在 (low, high) 区间"。

**第 K 小(230)** — 中序提前终止:
```python
def kthSmallest(root, k):
    stack = []
    cur = root
    while cur or stack:
        while cur:
            stack.append(cur)
            cur = cur.left
        cur = stack.pop()
        k -= 1
        if k == 0: return cur.val
        cur = cur.right
```

**恢复 BST(99)** — 中序找"逆序对":
```python
def recoverTree(root):
    """中序遍历找两个错位节点,交换值"""
    first = second = prev = None
    stack = []
    cur = root
    while cur or stack:
        while cur:
            stack.append(cur)
            cur = cur.left
        cur = stack.pop()
        if prev and prev.val > cur.val:
            if not first: first = prev      # 第一次逆序的大值
            second = cur                   # 最后一次逆序的小值
        prev = cur
        cur = cur.right
    first.val, second.val = second.val, first.val
```
**原理**:中序本应升序,两个节点交换后会有一处或两处逆序。第一处逆序的"大值"和最后一处逆序的"小值"就是错位节点。

**删除 BST 节点(450)**:
```python
def deleteNode(root, key):
    if not root: return None
    if key < root.val:
        root.left = deleteNode(root.left, key)
    elif key > root.val:
        root.right = deleteNode(root.right, key)
    else:
        # 找到要删的节点
        if not root.left: return root.right       # 无左 → 用右替代
        if not root.right: return root.left       # 无右 → 用左替代
        # 左右都有:找右子树最小值替代
        succ = root.right
        while succ.left: succ = succ.left
        root.val = succ.val
        root.right = deleteNode(root.right, succ.val)
    return root
```

### 3.6 最近公共祖先 LCA — 三种变体(CRITICAL)

**变体 1 — 二叉树 LCA(236)**:
```python
def lowestCommonAncestor(root, p, q):
    if not root or root == p or root == q:
        return root
    left = lowestCommonAncestor(root.left, p, q)
    right = lowestCommonAncestor(root.right, p, q)
    if left and right: return root    # p、q 分布在两侧 → root 是 LCA
    return left or right              # 都在一侧 → 沿该侧上传
```
**思路**:后序返回"p 或 q 是否在子树里"。当某节点的左右都返回非空 → 它就是 LCA。

**变体 2 — BST LCA(235)**:
```python
def lowestCommonAncestor(root, p, q):
    while root:
        if p.val < root.val and q.val < root.val:
            root = root.left          # 都在左
        elif p.val > root.val and q.val > root.val:
            root = root.right         # 都在右
        else:
            return root              # 分叉点即 LCA
```
利用 BST 性质,**不用递归**也可。

**变体 3 — 带父指针的 LCA(1650)**:
节点有 `parent` 指针。做法:**两指针对齐深度后同步上行**,相遇即 LCA(类似链表相交)。
```python
def lowestCommonAncestor(p, q):
    # 对齐深度:p 和 q 走到同深,然后同步上行
    a, b = p, q
    while a != b:
        a = a.parent if a.parent else q     # 走完自己的链换到对方链
        b = b.parent if b.parent else p     # 巧用换链消除深度差
    return a
```
**巧解**(如上):两指针各走完自己链后切到对方链,路程相等 → 必在 LCA 相遇。这和"链表相交"的统一写法一致。

### 3.7 填充右侧指针

**116 满树 / 117 任意树**(后者更通用):
```python
def connect(root):
    """BFS 层序,把每层节点串成链表"""
    if not root: return root
    q = deque([root])
    while q:
        size = len(q)
        prev = None
        for _ in range(size):
            node = q.popleft()
            if prev: prev.next = node
            prev = node
            if node.left:  q.append(node.left)
            if node.right: q.append(node.right)
    return root
```
**O(1) 空间版**(利用上一层已建立的 next 链):每层从左到右走上一层链表,把下一层串起来。满树有简化写法,任意树需要 dummy 虚拟头。

### 3.8 树形 DP(交叉引用 01-dynamic-programming.md)

**打家劫舍 III(337)**:
```python
def rob(root):
    """返回 (不偷当前的最大, 偷当前的最大)"""
    def dfs(node):
        if not node: return (0, 0)
        l = dfs(node.left)
        r = dfs(node.right)
        # 偷当前 → 左右子节点都不能偷
        rob_now = node.val + l[0] + r[0]
        # 不偷当前 → 左右子节点可偷可不偷
        skip_now = max(l) + max(r)
        return (skip_now, rob_now)
    return max(dfs(root))
```
**思路**:每个节点返回二元组"(不偷,偷)",父节点根据子节点状态组合。这是树形 DP 的范式 —— **返回值是状态向量**。

---

## 四、高频避坑清单

1. **全局变量 vs 返回值混淆**(最重要):见 2.3,看"返回值服务递归,全局 ans 服务答案"。
2. **None 边界**:每个递归先判 `if not node: return ...`,递归返回类型要能接住 None(如 `return left or right`)。
3. **空树 / 单节点**:测试必加,很多边界 bug 出在这。
4. **路径"从上到下"vs"任意路径"**:`437` 是"从上到下"(前缀和),`124` 是"任意路径"(倒 V 形,需后序整合)。状态设计完全不同!
5. **BST 中序有序性**:能用中序就别用普通树做法,常能 `O(n)` 一次扫描。
6. **序列化空节点标记**:`'#'` 必须有,否则无法唯一还原;反序列化用迭代器消费最简洁。
7. **删除节点的左右子树重连**:BST 删除有左右子树时,用**右子树最小值**或**左子树最大值**替代,再递归删那个值。
8. **LCA 的"左右都非空即根"判定**:`left and right` → 当前是 LCA;`left or right` → 沿非空侧上传。
9. **递归改迭代栈的入栈顺序**:前序迭代要"右先入栈"才能让左先出。
10. **Python 默认递归深度**:`sys.setrecursionlimit(10**6)` 防止深度为 1e4 的链式树栈溢出。
11. **层序用 `deque`**:别用 `list.pop(0)`(O(n))。
12. **Morris 中序访问时机**:第一次到 cur 设线索走左,第二次到 cur(线索存在)拆线索并访问走右 —— 别搞反。
13. **前缀和树上要回溯**:数组前缀和不用回溯(线性),树上必须 `prefix[cur] -= 1` 撤销,因为路径只能从父到子不能跨分支。

---

## 五、速记口诀 + 对比表

**口诀**:"分治靠后序,遍历靠栈;路径和用前缀,BST 用中序;LCA 找分叉,序列化用'#';树形 DP 返状态向量。"

| 维度 | 遍历思维 | 分治思维 |
|---|---|---|
| 返回值 | 无/布尔 | 有(子树信息) |
| 全局 ans | 常用 | 也常用(配合返回值) |
| 适用 | 路径枚举/求和 | 深度/直径/平衡/LCA |

| 维度 | 递归 | 迭代栈 | Morris |
|---|---|---|---|
| 空间 | O(h) 调用栈 | O(h) 显式栈 | **O(1)** |
| 写法 | 最易 | 中 | 难 |
| 适用 | 一般 | 栈溢出防护 | 极限空间 |

| 维度 | 前序 | 中序 | 后序 |
|---|---|---|---|
| 自然顺序 | 根左右 | 左根右 | 左右根 |
| 适用 | 构建/序列化 | **BST** | **分治/树形DP** |

| 维度 | 二叉树 LCA | BST LCA | 带父指针 LCA |
|---|---|---|---|
| 思路 | 后序找分叉 | 利用 BST 分叉 | 对齐深度同步上行 |
| 复杂度 | O(n) | O(h) | O(h) |

---

## 六、自测清单

- [ ] 默写"返回值 + 全局 ans"模式,**说清 543 直径为什么返回深度却记直径**
- [ ] 默写 124 最大路径和,**说清 `gain` 返回单链、`ans` 记倒 V 的区别**
- [ ] 默写中序迭代栈式(`while cur: stack.append; cur = cur.left`)
- [ ] 默写 Morris 中序,**说清两次到达 cur 的动作差异**
- [ ] 默写层序分层(`for _ in range(len(q))`)
- [ ] 默写 105 前中序建树,**说清为什么用哈希表存中序位置**
- [ ] 默写 297 序列化/反序列化(前序 + `'#'` + 迭代器)
- [ ] 默写 98 验证 BST 上下界法,**说清为什么局部"左<根<右"不够**
- [ ] 默写 99 恢复 BST(中序找逆序对)
- [ ] 默写三种 LCA(二叉树 / BST / 带父指针)
- [ ] 默写 437 路径总和 III,**说清为什么树上前缀和要回溯**
- [ ] 默写 337 打家劫舍 III(返回状态向量)

> 任何一项卡壳 → 回到对应小节手抄模板再默写。二叉树薄弱的本质是"返回值设计"和"分治 vs 遍历"没分清 —— **每做一道题问自己:这道返回值服务谁?答案从哪里取?**
