# 00 · 思考框架 + Python 通用模板速查

> 面向"已经刷过一遍 Hot 150、但四块薄弱"的应试者。本文是 **元文件**:DP / 字符串 / 图 / 二叉树 四篇都引用这里的通用模板。
> 心法:**先看数据范围 → 倒推复杂度 → 选模式 → 套模板 → 补边界**。

---

## 一、通用思考框架(每题必走 7 步)

| 步 | 动作 | 防止的失败类型 |
|---|---|---|
| ① | **读题 + 手算 2-3 个样例**(含最小/最大/退化) | 题意误读、隐含约束漏看 |
| ② | **看数据范围 → 倒推复杂度**(见下表) | TLE / 选错算法 |
| ③ | **选模式**(对照"题目特征→算法"速查表) | 没思路、暴力硬冲 |
| ④ | **先写暴力再优化**(暴力是正确性基准) | 一上来抠最优导致 bug |
| ⑤ | **列边界**:空 / 单元素 / 全等 / 已排序 / 负数 / 溢出 | 边界 WA |
| ⑥ | **实现**:命名清晰、复用模板、变量含义单一 | off-by-one、状态污染 |
| ⑦ | **自测**:手测样例 + 至少 1 个反例 + 复杂度自证 | 隐藏 bug、说不清复杂度 |

> ⚠️ 第 ② 步是最容易被忽略但最值钱的。**数据范围写在题目里不是装饰**,是出题人给的"复杂度上限暗示"。

---

## 二、数据范围 → 复杂度 → 算法 对照表(CRITICAL)

| 数据范围 n | 可承受复杂度 | 典型算法/模式 |
|---|---|---|
| `n ≤ 10` | `O(n!)` | 全排列、回溯全枚举 |
| `n ≤ 20` | `O(2^n · n)` | **状态压缩 DP**、子集枚举、子集回溯 |
| `n ≤ 100` | `O(n³)` | **区间 DP**、三指针、Floyd |
| `n ≤ 250~500` | `O(n³)` 紧 | 区间 DP(戳气球、石子合并) |
| `n ≤ 1000~2000` | `O(n²)` | 普通二维 DP、双指针、KMP 匹配 |
| `n ≤ 1e5` | `O(n log n)` | 排序、二分、线段树、堆、单调栈 |
| `n ≤ 1e6` | `O(n)` | 线性扫描、KMP、Manacher、并查集、前缀和 |
| `n ≤ 1e9` | `O(log n)` | 二分答案、快速幂 |
| `n ≤ 1e18` | `O(log n)` | 矩阵快速幂、欧拉函数 |

**1 秒时限经验值(Python,常数取宽松)**:

| 复杂度 | n 上限 |
|---|---|
| `O(n!)` | ~10 |
| `O(2^n)` | ~22 |
| `O(n^3)` | ~300 |
| `O(n^2)` | ~3000 |
| `O(n log n)` | ~2·10^5 |
| `O(n)` | ~10^7 |
| `O(log n)` | ∞ |

> Python 比 C++ 慢约 20-50 倍。如果题目卡 `n=1e5` 的 `O(n log n)`,Python 可能要紧;`n=1e6` 的 `O(n)` 基本到上限。**用 `sys.stdin` 加速读入**,别用 `input()`。

---

## 三、Python 速记(内置工具)

```python
import heapq                            # 最小堆;最大堆取 -x
heapq.heappush(h, x); heapq.heappop(h)  # O(log n)
heapq.heapify(lst)                      # O(n)
heapq.nlargest(k, lst) / nsmallest(...) # 等价于排序取尾/头

from collections import deque           # 双端队列,BFS 专用
q = deque([start]); q.popleft(); q.append(x)   # 两端 O(1)

from collections import defaultdict, Counter
g = defaultdict(list); g[u].append(v)   # 邻接表,免初始化
cnt = Counter(s); cnt.most_common(k)    # 计数 + TopK

from bisect import bisect_left, bisect_right, insort
# 在有序序列中找第一个 ≥ x:bisect_left(a, x)
# LIS O(n log n):每次 insort 替换尾数组(见 01-DP)

from functools import lru_cache
@lru_cache(None)                        # 记忆化搜索
def dfs(i, j): ...

import itertools
itertools.combinations(xs, k)           # 组合
itertools.permutations(xs, k)           # 排列
itertools.product(xs, repeat=k)        # 笛卡尔积
itertools.accumulate(xs)               # 前缀和
itertools.chain(*lists)                # 拍平嵌套

import sys
sys.setrecursionlimit(10**6)            # 树/图递归必加
sys.stdin.read().split()               # 快读
```

**位运算**:
```python
x & -x              # 取最低位的 1(如 12 & -12 = 4)
x & (x - 1)         # 去掉最低位的 1(判 2 的幂、popcount 循环)
sub = (sub - 1) & mask   # 枚举 mask 的所有真子集(降序)
bin(x).count('1')   # popcount(也可是 int.bit_count(), Py3.10+)
```

---

## 四、通用模板速查

### 4.1 并查集(路径压缩 + 按秩合并)

```python
class DSU:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n          # 按秩合并,秩=树高近似
        self.cnt = n                 # 连通分量数

    def find(self, x):
        # 路径压缩:递归把路径上所有点直接挂到根
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False             # 已连通,这条边是冗余边
        # 小树挂大树,保证高不增
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        self.cnt -= 1
        return True
```
复杂度:均摊 `O(α(n))` ≈ `O(1)`。带权版本(除法求值 399)见 `03-graph-theory.md`。

### 4.2 BFS(分层 / 不分层)

```python
from collections import deque

def bfs(start, adj):
    """不分层:只求可达/最短步数(无权图)"""
    q = deque([start])
    visited = {start}
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in visited:
                visited.add(v)
                q.append(v)

def bfs_layers(start, adj):
    """分层:每层 = 同距离。求最短距离/最短路径条数时用"""
    q = deque([start])
    visited = {start}
    dist = 0
    while q:
        # 关键:先记当前层大小,再按 size 弹
        for _ in range(len(q)):
            u = q.popleft()
            for v in adj[u]:
                if v not in visited:
                    visited.add(v)
                    q.append(v)
        dist += 1            # 一层结束,距离 +1
```
⚠️ **入队时立即标记 visited**,否则同一节点会被多次入队,复杂度退化到 `O(V·E)`。

### 4.3 DFS(递归 + 迭代栈)

```python
import sys; sys.setrecursionlimit(10**6)

def dfs_rec(u, adj, visited):
    visited.add(u)
    for v in adj[u]:
        if v not in visited:
            dfs_rec(v, adj, visited)

def dfs_iter(start, adj):
    """迭代栈写法,防栈溢出"""
    visited = set()
    stack = [start]
    while stack:
        u = stack.pop()
        if u in visited:
            continue
        visited.add(u)
        for v in adj[u]:
            if v not in visited:
                stack.append(v)   # 注意:逆序入栈可保持原顺序
```

### 4.4 Dijkstra(非负权最短路)

```python
import heapq

def dijkstra(n, adj, src):
    """adj[u] = [(v, w), ...]; 返回 src 到各点最短距离"""
    dist = [float('inf')] * n
    dist[src] = 0
    pq = [(0, src)]                  # (距离, 节点);最小堆
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:              # 过期数据跳过(关键!)
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist
```
复杂度 `O((V+E) log V)`。⚠️ 不能处理负权 → 用 Bellman-Ford。

### 4.5 二分查找(两种写法,选定一种别混用)

```python
def lower_bound(a, x):
    """左闭右开:返回第一个 ≥ x 的位置"""
    lo, hi = 0, len(a)        # hi = n, 不是 n-1
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo                 # 落点即答案

def bsearch_closed(lo, hi, check):
    """左闭右闭:check(mid) 单调;找最后一个满足 check 的位置"""
    while lo <= hi:
        mid = (lo + hi) // 2
        if check(mid):
            lo = mid + 1     # 满足,往右找更优
        else:
            hi = mid - 1
    return hi                 # hi 是最后一个满足的位置
```

### 4.6 回溯(全排列 / 子集 / 组合 通用框架)

```python
def permute(nums):
    ans = []
    used = [False] * len(nums)
    path = []
    def dfs():
        if len(path) == len(nums):
            ans.append(path[:])      # 必须拷贝!path 还会变
            return
        for i in range(len(nums)):
            if used[i]:
                continue
            used[i] = True
            path.append(nums[i])
            dfs()
            path.pop()               # 撤销选择
            used[i] = False
    dfs()
    return ans

def subsets(nums):
    """子集:用 start 控制不重复"""
    ans = []
    path = []
    def dfs(start):
        ans.append(path[:])
        for i in range(start, len(nums)):
            path.append(nums[i])
            dfs(i + 1)
            path.pop()
    dfs(0)
    return ans

def combine(n, k):
    ans = []
    path = []
    def dfs(start, need):
        if need == 0:
            ans.append(path[:])
            return
        # 剪枝:剩余元素不够就停
        for i in range(start, n - need + 2):
            path.append(i)
            dfs(i + 1, need - 1)
            path.pop()
    dfs(1, k)
    return ans
```

### 4.7 滑动窗口(可变长)

```python
def sliding_window(s, target):
    """求满足条件的最小/长子串。框架:右扩、左缩"""
    left = 0
    cnt = defaultdict(int)           # 窗口内状态
    need = Counter(target)           # 目标状态
    valid = 0                        # 已满足的字符种类数
    best = 0
    for right, ch in enumerate(s):
        cnt[ch] += 1                 # 右端入窗
        if ch in need and cnt[ch] == need[ch]:
            valid += 1
        while valid == len(need):   # 满足条件 → 收缩左端
            # 更新答案(此时窗口 [left, right] 满足条件)
            best = max(best, right - left + 1)
            cnt[s[left]] -= 1
            if s[left] in need and cnt[s[left]] == need[s[left]] - 1:
                valid -= 1
            left += 1
    return best
```

### 4.8 单调栈(下一个更大元素)

```python
def next_greater(nums):
    """返回每个位置右边第一个比它大的下标,没有则 -1"""
    n = len(nums)
    res = [-1] * n
    stack = []                       # 存下标,栈内元素对应值单调递减
    for i in range(n):
        while stack and nums[stack[-1]] < nums[i]:
            res[stack.pop()] = i
        stack.append(i)
    return res
```
经典题:每日温度 739、下一个更大元素 I/II 496/503、接雨水 42。

### 4.9 单调队列(滑动窗口最大值)

```python
from collections import deque

def max_sliding_window(nums, k):
    """双端队列存下标,队首始终是当前窗口最大值"""
    dq = deque()
    res = []
    for i, x in enumerate(nums):
        # 队首过期:出窗
        if dq and dq[0] <= i - k:
            dq.popleft()
        # 队尾比 x 小的都没用,弹掉
        while dq and nums[dq[-1]] <= x:
            dq.pop()
        dq.append(i)
        if i >= k - 1:
            res.append(nums[dq[0]])
    return res
```

### 4.10 堆(TopK / 数据流中位数)

```python
import heapq

# TopK 小:维护大小为 K 的最大堆(存负数),超出 K 就弹最大
def topk_smallest(nums, k):
    h = []
    for x in nums:
        heapq.heappush(h, -x)
        if len(h) > k:
            heapq.heappop(h)
    return [-x for x in h]

# 数据流中位数:大根堆(左)+ 小根堆(右),左堆顶 ≤ 右堆顶
class MedianFinder:
    def __init__(self):
        self.left = []     # 最大堆(存负数)
        self.right = []    # 最小堆
    def add(self, num):
        heapq.heappush(self.left, -num)
        # 平衡:左堆顶可能 > 右堆顶,要倒过去
        heapq.heappush(self.right, -heapq.heappop(self.left))
        if len(self.left) < len(self.right):
            heapq.heappush(self.left, -heapq.heappop(self.right))
    def median(self):
        if len(self.left) > len(self.right):
            return -self.left[0]
        return (-self.left[0] + self.right[0]) / 2
```

### 4.11 前缀和与差分

```python
# 一维前缀和
prefix = [0]
for x in a:
    prefix.append(prefix[-1] + x)
# 区间和 a[l..r] = prefix[r+1] - prefix[l]

# 差分:对区间 [l,r] 加 v
diff = [0] * (n + 1)
diff[l] += v
diff[r + 1] -= v
# 还原:逐项累加 diff 即得原数组操作后的结果

# 二维前缀和
# s[i][j] = a[i][j] + s[i-1][j] + s[i][j-1] - s[i-1][j-1]
# 子矩阵 (r1,c1)-(r2,c2) 和:
#   s[r2][c2] - s[r1-1][c2] - s[r2][c1-1] + s[r1-1][c1-1]
```

### 4.12 快速幂(取模)

```python
def qpow(base, exp, mod):
    """O(log exp)"""
    res = 1
    base %= mod
    while exp:
        if exp & 1:
            res = res * base % mod
        base = base * base % mod
        exp >>= 1
    return res
```

### 4.13 拓扑排序(Kahn / BFS 入度法)

```python
from collections import deque, defaultdict

def topo(n, edges):
    """返回拓扑序;若长度 < n 说明有环"""
    g = defaultdict(list)
    indeg = [0] * n
    for u, v in edges:
        g[u].append(v)
        indeg[v] += 1
    q = deque([i for i in range(n) if indeg[i] == 0])
    order = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in g[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return order if len(order) == n else []   # 空 = 有环
```

### 4.14 Trie

```python
class TrieNode:
    __slots__ = ('children', 'end')
    def __init__(self):
        self.children = {}
        self.end = False

class Trie:
    def __init__(self):
        self.root = TrieNode()
    def insert(self, word):
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.end = True
    def search(self, word):
        node = self._walk(word)
        return node is not None and node.end
    def startsWith(self, prefix):
        return self._walk(prefix) is not None
    def _walk(self, s):
        node = self.root
        for ch in s:
            if ch not in node.children:
                return None
            node = node.children[ch]
        return node
```

---

## 五、笔试 / 面试调试技巧

1. **构造反例**:看约束边界 — 全升序、全降序、全相等、首尾最小最大、奇偶长度、单元素、空。
2. **二分定位 bug**:在关键循环里 `print(lo, hi, mid, check(mid))`,看分支走对没。
3. **时间不够先写暴力**:`n ≤ 20` 的暴力 DFS 能拿 60% 分,优化是锦上添花。
4. **Python 递归爆栈**:`sys.setrecursionlimit(10**6)`,或改成迭代栈(见 4.3)。
5. **超时先换数据结构**:`defaultdict(set)` 换 `dict + list`、`list.pop(0)` 换 `deque.popleft()`。
6. **答案取模题**:每一步 `% MOD`,加法和乘法都要模,减法要 `+ MOD` 防负。
7. **二分答案题**(求"最小的最大"):把"判定 check(x)"和"二分 x"分开写,不易错。

---

## 六、四块速记口诀总览

| 块 | 一句口诀 | 详见 |
|---|---|---|
| DP | "最后一步想清楚,状态转移自然有;背包逆序完全序,滚动数组别覆盖" | `01-dynamic-programming.md` |
| 字符串 | "子串想滑窗,匹配想 KMP,回文 Manacher,Trie 找前缀" | `02-strings.md` |
| 图 | "连通 DFS/BFS,最短 Dijkstra,拓扑判环并查集,带权用加权并查" | `03-graph-theory.md` |
| 二叉树 | "分治靠后序,遍历靠栈,路径和用前缀,BST 用中序" | `04-binary-trees.md` |

---

## 七、自测清单

能否在 30 秒内默写以下每个模板的核心骨架(不必逐行,但要结构正确)?

- [ ] 并查集 `find` 路径压缩 + `union` 按秩
- [ ] BFS 分层(`for _ in range(len(q))`)
- [ ] Dijkstra(`if d > dist[u]: continue` 这行不能漏)
- [ ] 二分 `lower_bound`(`lo < hi`,`hi = n`)
- [ ] 回溯"选择 → dfs → 撤销"三件套
- [ ] 滑动窗口"右扩、左缩"双指针
- [ ] 单调栈(`while stack and ... < ...: pop`)
- [ ] 单调队列(队首过期 + 队尾弹小)
- [ ] 数据流中位数双堆平衡
- [ ] 快速幂(`if exp & 1` + `exp >>= 1`)
- [ ] 拓扑排序(`indeg[v] == 0` 入队)

> 任何一个默不出来 → 那块就是薄弱点,去对应主题文件刷模板。
