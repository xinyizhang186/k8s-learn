# 03 · 图论实战与避坑

> 已刷过一遍 Hot 150,但图论"非常薄弱"。本文直接进入:识别信号(含"伪装的图")→ 心智模型 → 子模式全家桶(BFS/DFS/拓扑/并查集/最短路/MST/二分图/欧拉)→ 避坑 → 速记。
> 心法:**图问题 = 表示法 + 遍历方式 + 状态维度**。卡住 80% 是没认出"这是一张图",或没把"已访问状态"塞进 BFS 队列。**

通用模板(并查集、BFS、DFS、Dijkstra、拓扑、Trie)见 `00-thinking-framework-and-templates.md`。本文只写图论专属变体。

---

## 一、识别信号(含"伪装的图")

| 题目特征 | 推荐图算法 |
|---|---|
| "连通""分量""朋友圈""岛屿" | **并查集 / DFS 连通分量** |
| "课程表""依赖""先修""外星词典" | **拓扑排序** |
| "冗余连接""等式方程""账户合并" | **并查集** |
| "最短路径""最少步数""网络延迟" | **BFS(无权) / Dijkstra(正权)** |
| "网格最短路径""01 矩阵" | 多源 BFS / 0-1 BFS |
| "单词接龙""最小基因突变" | **双向 BFS** |
| "二分图""分组""可能的两部分" | **染色(DFS/BFS)** |
| "重新安排行程""欧拉回路" | **Hierholzer** |
| "除法求值""带权连通" | **带权并查集** |
| 矩阵 flood fill、岛屿数 | 矩阵即图,4/8 邻接 |

> ⚠️ **伪装识别**:看到"两个东西等价 / 可达 / 可交换",先想"能不能建成无向边";看到"变化的中间态 + 最少步数",先想"状态 = 节点,BFS"。

---

## 二、心智模型

### 2.1 表示法选择

| 表示 | 空间 | 适用 |
|---|---|---|
| 邻接表 `g[u] = [v,...]` | `O(V+E)` | 稀疏图(常用) |
| 邻接矩阵 `g[u][v]` | `O(V²)` | 稠密图、Floyd |
| 边集 `[(u,v,w),...]` | `O(E)` | Kruskal、Bellman-Ford |

### 2.2 BFS vs DFS 选择

| 维度 | BFS | DFS |
|---|---|---|
| 求最短(无权) | ✅ 天然 | ❌ 要记录所有路径 |
| 求连通分量 | ✅ | ✅ |
| 拓扑/环检测 | ✅(入度) | ✅(三色标记) |
| 路径枚举/回溯 | ❌ | ✅ |
| 栈深度风险 | 无 | 有(Python 递归改迭代) |

### 2.3 何时需要把"状态"塞进 BFS 队列(CRITICAL)

普通 BFS 队列元素 = 节点。但有些题节点会"重复经过",普通 `visited` 会误杀。

**判断标准**:**一个节点能否在不同状态下被访问到,且后续路径不同?**
- 847 访问所有节点:同一节点,但"已访问集合"不同 → 状态 `(node, mask)`
- 864 获取所有钥匙的最短路径:同一节点,但"已拿钥匙"不同 → 状态 `(node, keys)`
- 单词接龙:同一单词只有一种状态 → 普通 BFS

**口诀**:**"节点会被重复经过 + 后续行为不同 → 把额外维度塞进状态"**。

---

## 三、子模式全家桶

### 3.1 BFS/DFS 基础 — 岛屿与连通

**模板 — 岛屿数量(200)**:
```python
def numIslands(grid):
    if not grid: return 0
    m, n = len(grid), len(grid[0])
    ans = 0
    def dfs(i, j):
        if i < 0 or i >= m or j < 0 or j >= n or grid[i][j] != '1':
            return
        grid[i][j] = '2'          # 原地标记,省 visited
        for di, dj in [(1,0),(-1,0),(0,1),(0,-1)]:
            dfs(i + di, j + dj)
    for i in range(m):
        for j in range(n):
            if grid[i][j] == '1':
                ans += 1
                dfs(i, j)
    return ans
```
**Hot 150 真题**:200 岛屿数、695 岛屿最大面积、1254 封闭岛屿、130 被围绕的区域、133 克隆图、733 图像渲染。

⚠️ **避坑**:原地标记 `'2'` 修改了输入,面试要问"能否修改";不能修改就开 `visited` 集。

### 3.2 拓扑排序(CRITICAL)

**识别**:依赖关系、DAG、判断有无环、外星词典字母序。

**两种实现 — 都要会**:

**Kahn(BFS 入度法)** — 模板见 `00` 4.13。判环:`len(order) < n` 则有环。

**DFS 三色标记法**:
```python
def canFinish(n, prerequisites):
    g = [[] for _ in range(n)]
    for a, b in prerequisites:
        g[b].append(a)       # b → a(b 先修)
    color = [0] * n          # 0=未访问 1=访问中 2=完成
    def dfs(u):
        if color[u] == 1: return False      # 回边 → 环
        if color[u] == 2: return True
        color[u] = 1
        for v in g[u]:
            if not dfs(v): return False
        color[u] = 2
        return True
    for i in range(n):
        if not dfs(i): return False
    return True
```
**为什么三色?** 灰色(访问中)遇到灰色 = 回边 = 环。黑色(已完成)直接跳过避免重复 DFS。

**外星词典(269)**:把字母序差异建边 → 拓扑排序;若有环或矛盾 → 无效。

**Hot 150 真题**:207 课程表、210 课程表 II、269 外星词典、444 序列重建、1136 并行课程。

### 3.3 并查集 — 普通版

模板见 `00` 4.1。

**Hot 150 真题**:
- 684 冗余连接:加边前两端已连通 → 这条边就是冗余
- 721 账户合并:邮箱为节点,同一账户的邮箱合并
- 547 朋友圈 / 1319 连通网络操作次数
- 990 等式方程的可满足性:`a==b` 合并,`a!=b` 检查是否同根

### 3.4 带权并查集(CRITICAL — 除法求值)

**识别**:节点间有"比例/差值/异或"关系,且关系可传递(如 `a/b=2, b/c=3 → a/c=6`)。

**模板 — 除法求值(399)**:
```python
def calcEquation(equations, values, queries):
    parent = {}     # 节点 → (父, 到父的倍数)
    def find(x):
        if x not in parent:
            parent[x] = (x, 1.0)
            return (x, 1.0)
        if parent[x][0] == x:
            return parent[x]
        root, w = find(parent[x][0])     # 递归到根,顺便压缩
        # x 到根 = x 到父 * 父到根
        parent[x] = (root, parent[x][1] * w)
        return parent[x]
    def union(x, y, w):
        rx, wx = find(x)                 # x/root[x] = wx
        ry, wy = find(y)                 # y/root[y] = wy
        if rx == ry: return
        # 已知 x/y = w,即 root[x]/root[y] = wx / wy * w
        parent[rx] = (ry, wy * w / wx)
    # 建图
    for (a, b), v in zip(equations, values):
        union(a, b, v)
    # 查询
    ans = []
    for a, b in queries:
        if a not in parent or b not in parent:
            ans.append(-1.0); continue
        ra, wa = find(a)
        rb, wb = find(b)
        if ra != rb:
            ans.append(-1.0)
        else:
            ans.append(wa / wb)          # a/b = (a/ra) / (b/rb)
    return ans
```
**核心**:带权并查集在 `find` 时维护"节点到根的权",`union` 时通过权的关系把两棵树接起来。

### 3.5 最短路

| 算法 | 适用 | 复杂度 |
|---|---|---|
| BFS | 无权图 | `O(V+E)` |
| **Dijkstra** | 非负权 | `O((V+E) log V)` |
| Bellman-Ford | 可负权 | `O(VE)` |
| Floyd | 多源、`n ≤ 100` | `O(n³)` |
| SPFA | 队列优化 BF(最坏退化) | 平均 `O(kE)` |

**Dijkstra 模板** 见 `00` 4.4。**关键那行 `if d > dist[u]: continue` 不能漏** —— 否则过期数据会污染。

**网格 BFS 最短路 — 二进制矩阵最短路径(1091)**:
```python
from collections import deque
def shortestPathBinaryMatrix(grid):
    n = len(grid)
    if grid[0][0] or grid[n-1][n-1]: return -1
    q = deque([(0, 0, 1)])       # (r, c, dist)
    visited = {(0, 0)}
    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]  # 8 方向
    while q:
        r, c, d = q.popleft()
        if (r, c) == (n-1, n-1): return d
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n and not grid[nr][nc] and (nr, nc) not in visited:
                visited.add((nr, nc))
                q.append((nr, nc, d + 1))
    return -1
```

### 3.6 双向 BFS(CRITICAL)

**识别**:起点 + 终点都明确 + 求最短步数 + 单词接龙类(分支因子大)。

**模板 — 单词接龙(127)**:
```python
def ladderLength(beginWord, endWord, wordList):
    word_set = set(wordList)
    if endWord not in word_set: return 0
    # 双向 BFS:从 begin 和 end 同时扩散,碰头即答案
    front = {beginWord}
    back = {endWord}
    visited = set()
    step = 1
    while front:
        if len(front) > len(back):       # 总是扩展较小的一端
            front, back = back, front
        nxt = set()
        for word in front:
            for i in range(len(word)):
                for c in 'abcdefghijklmnopqrstuvwxyz':
                    if c == word[i]: continue
                    new = word[:i] + c + word[i+1:]
                    if new in back:       # 碰头!
                        return step + 1
                    if new in word_set and new not in visited:
                        visited.add(new)
                        nxt.add(new)
        front = nxt
        step += 1
    return 0
```
**为什么快?** 单向 BFS 扩散的节点数随距离指数增长,双向把"两个圆"变成"两个小圆",理论上 `O(b^d) → O(b^(d/2))`。

⚠️ **避坑**:`if new in back` 检测碰头,`step + 1` 因为两端各走了半步要加 1。

### 3.7 多源 BFS

**识别**:`01 矩阵`(所有 0 到最近 1 的距离)、`腐烂橘子`(多源同时扩散)。

**模板 — 01 矩阵(542)**:
```python
from collections import deque
def updateMatrix(mat):
    m, n = len(mat), len(mat[0])
    q = deque()
    dist = [[float('inf')] * n for _ in range(m)]
    # 把所有 0 作为超级源,同时入队
    for i in range(m):
        for j in range(n):
            if mat[i][j] == 0:
                dist[i][j] = 0
                q.append((i, j))
    while q:
        i, j = q.popleft()
        for di, dj in [(1,0),(-1,0),(0,1),(0,-1)]:
            ni, nj = i + di, j + dj
            if 0 <= ni < m and 0 <= nj < n and dist[ni][nj] > dist[i][j] + 1:
                dist[ni][nj] = dist[i][j] + 1
                q.append((ni, nj))
    return dist
```
**核心**:多源 BFS = 加一个"超级源"连到所有起点,等价于从超级源做单源 BFS。

### 3.8 0-1 BFS(双端队列)

**识别**:边权只有 0 和 1 → 用 `deque` 代替优先队列,`O(V+E)`。

```python
from collections import deque
def zero_one_bfs(n, adj, src):
    dist = [float('inf')] * n
    dist[src] = 0
    dq = deque([src])
    while dq:
        u = dq.popleft()
        for v, w in adj[u]:
            if dist[v] > dist[u] + w:
                dist[v] = dist[u] + w
                if w == 0:
                    dq.appendleft(v)    # 0 权优先,放队首
                else:
                    dq.append(v)        # 1 权放队尾
    return dist
```

### 3.9 二分图判定 / 染色

**识别**:"能否分成两组,组内无边""二分图""可能的二分法"。

**模板 — 二分图判定(786)**:
```python
from collections import deque
def isBipartite(graph):
    n = len(graph)
    color = [-1] * n       # -1 未染,0/1 两色
    for i in range(n):
        if color[i] != -1: continue
        color[i] = 0
        q = deque([i])
        while q:
            u = q.popleft()
            for v in graph[u]:
                if color[v] == -1:
                    color[v] = color[u] ^ 1     # 染相反色
                    q.append(v)
                elif color[v] == color[u]:       # 同色 → 非二分
                    return False
    return True
```
**核心**:相邻必须异色,冲突即非二分。DFS 染色也行,逻辑一致。

**Hot 150 真题**:786/886 二分图判定、886 可能的二分法、885 螺旋矩阵(非二分,边界)。

### 3.10 欧拉路径 / 回路

**识别**:"重新安排行程""一笔画""访问每条边恰好一次"。

**模板 — 重新安排行程(332)** — Hierholzer:
```python
import heapq
from collections import defaultdict
def findItinerary(tickets):
    g = defaultdict(list)
    for a, b in tickets:
        heapq.heappush(g[a], b)        # 小顶堆保证字典序最小
    path = []
    def dfs(u):
        while g[u]:
            v = heapq.heappop(g[u])
            dfs(v)
        path.append(u)                  # 关键:逆序入栈!后序
    dfs('JFK')
    return path[::-1]                   # 反转得到欧拉路径
```
**为什么后序入栈?** Hierholzer 算法:DFS 走到死路(无出边)时,该节点应在路径末尾。后序入栈再反转即得欧拉路径。

**前提**:图存在欧拉路径(入度=出度,或恰一个出度多1、一个入度多1)。

### 3.11 最小生成树(简述)

**Kruskal**:边按权排序,并查集合并,连则加入 MST。`O(E log E)`。
**Prim**:堆 + 类 Dijkstra,从任一点扩展最小割边。`O(E log V)`。

Hot 150 较少考,但 Kruskal 模板 = 排序 + 并查集,直接用 `00` 的 DSU 即可。

### 3.12 强连通分量(Tarjan/Kosaraju,简述)

Hot 150 基本不考,但面试会问"判断两个节点是否强连通"。
- Kosaraju:两遍 DFS(原图 + 反图)。
- Tarjan:一次 DFS + 栈 + `dfn/low`。

---

## 四、高频避坑清单

1. **visited 标记时机**:**入队时立即标记**,不是出队时。出队才标记会导致重复入队,复杂度退化到 `O(V·E)`。
2. **邻接表 vs 邻接矩阵**:稀疏用邻接表(`defaultdict(list)`),否则 `O(V²)` 内存爆炸。
3. **拓扑判环**:`len(order) == n` 才无环,否则返回 `[]` 表示有环。
4. **并查集路径压缩 vs 按秩合并**:两个一起用才 `O(α(n))`;只用一个还是可能退化。
5. **Dijkstra 不能处理负权**:有负权用 Bellman-Ford 或 SPFA。
6. **Python heapq 是最小堆**:最大堆存 `-x`;优先队列里 `(dist, node)` 别写反。
7. **双向 BFS 终止条件**:扩展时检测 `new in back`(碰头),不是 `visited`。
8. **矩阵 DFS 边界检查顺序**:`0<=i<m and 0<=j<n` 必须在访问 `grid[i][j]` **之前**。
9. **递归 DFS 栈溢出**:`n` 大时加 `sys.setrecursionlimit(10**6)` 或改迭代栈。
10. **BFS 分层 vs 不分层**:求层数/最短距离必须分层(`for _ in range(len(q))`),求可达可不分层。
11. **Dijkstra 过期数据**:pop 出的 `d > dist[u]` 要 `continue`,否则用旧距离覆盖。
12. **带权并查集的 `find` 要递归压缩**:权要随路径一起更新,不能只改父指针。

---

## 五、速记口诀 + 对比表

**口诀**:"连通并查或 DFS,最短无权 BFS 正权 Dijkstra,拓扑判环看入度,带权并查除法求,二分染色相反色,欧拉后序反转走,双向 BFS 扩小端。"

| 维度 | BFS | DFS |
|---|---|---|
| 最短(无权) | ✅ | ❌ |
| 连通分量 | ✅ | ✅ |
| 路径枚举 | ❌ | ✅ |
| 栈风险 | 无 | 有 |

| 维度 | 并查集 | DFS 连通 |
|---|---|---|
| 复杂度 | `O(α)` | `O(V+E)` |
| 动态加边 | ✅ 友好 | 需重算 |
| 带权 | 可扩展 | 麻烦 |

| 维度 | Dijkstra | Bellman-Ford | Floyd |
|---|---|---|---|
| 负权 | ❌ | ✅ | ✅(无负环) |
| 复杂度 | `O(E log V)` | `O(VE)` | `O(n³)` |
| 单源/全源 | 单源 | 单源 | 全源 |

| 维度 | 拓扑 Kahn | 拓扑 DFS |
|---|---|---|
| 实现 | 入度 BFS | 三色标记 |
| 判环 | `len<n` 有环 | 回边即环 |
| 输出序 | 队列顺序 | 逆后序 |

---

## 六、自测清单

- [ ] 默写 BFS 分层模板,**说清 `visited` 入队时标记的原因**
- [ ] 默写拓扑排序 Kahn 版 + DFS 三色版,**说清判环条件**
- [ ] 默写并查集(路径压缩 + 按秩),**说清均摊 `O(α)`**
- [ ] 默写带权并查集 `find`(权随路径更新)
- [ ] 默写 Dijkstra,**说清 `if d > dist[u]: continue` 不能漏的原因**
- [ ] 默写双向 BFS,**说清为什么总扩较小一端**
- [ ] 默写多源 BFS(超级源思想)
- [ ] 默写二分图染色
- [ ] 默写 Hierholzer(后序入栈 + 反转)

> 任何一项卡壳 → 回到对应小节手抄模板再默写。图论薄弱的核心是"认不出是图"和"状态维度设计",**做完每题问自己:为什么用这个算法?状态塞了几个维度?**
