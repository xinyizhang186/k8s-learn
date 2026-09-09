# 09. 图论 [深入]

这是你的薄弱环节。图论题 **算法很多**，但在 Hot 150 中真正反复出现的只有大约 10 种模式。掌握这些，90% 的图论题就变成「该套哪个模板」。

---

## 0. 心智模型：每个图论题都可归结为四个问题

1. **图是有向还是无向？** 决定环检测 / 拓扑排序的写法是否不同。
2. **边权是否一致（或无权）？** 一致 → BFS 就能求最短路。不一致 → Dijkstra（若权值为负则用 Bellman-Ford / SPFA）。
3. **节点代表什么，边代表什么？** 有时「节点」是一个 *状态*（比如 `(row, col)`、`(position, keyring)`），而不是字面意义上的图顶点。
4. **我们在算什么？** 连通性 / 最短路 / 拓扑序 / 最小生成树 / 最大流 / 染色。

能回答这四个问题，就给题目归好类了。剩下的就是选择下面的模板。

---

## 1. 图的表示

```python
# 邻接表（最常用，稀疏图）
from collections import defaultdict
graph: dict[int, list[int]] = defaultdict(list)
for u, v in edges: graph[u].append(v)             # 有向
# 无向：再加一句 graph[v].append(u)

# 带权的邻接表
wg: dict[int, list[tuple[int, int]]] = defaultdict(list)  # u -> [(v, w)]
for u, v, w in edges: wg[u].append((v, w))

# 邻接矩阵（稠密图，n 较小，如 n ≤ 300，Floyd-Warshall）
n = max_node_id + 1
adj = [[0] * n for _ in range(n)]
for u, v, w in edges: adj[u][v] = w

# 网格视为图：用方向取邻居
DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]

def neighbors(r: int, c: int) -> list[tuple[int, int]]:
    return [(r + dr, c + dc) for dr, dc in DIRS
            if 0 <= r + dr < R and 0 <= c + dc < C]
```

## 2. BFS：无权图的最短路径

```python
from collections import deque

def bfs(start: int, graph: dict[int, list[int]]) -> dict[int, int]:
    dist = {start: 0}
    q: deque[int] = deque([start])
    while q:
        u = q.popleft()
        for v in graph[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist
```

**为什么 BFS 能求无权图的最短路：** 它按距起点的距离递增顺序探索节点。第一次到达 `v` 时，得到的距离就是最短的。

### 2.1 网格上的 BFS：洪水填充 / 最短路径

```python
def nearest_zero_distance(mat: list[list[int]]) -> list[list[int]]:
    R, C = len(mat), len(mat[0])
    dist = [[-1] * C for _ in range(R)]
    q: deque[tuple[int, int]] = deque()
    for r in range(R):
        for c in range(C):
            if mat[r][c] == 0:
                dist[r][c] = 0
                q.append((r, c))                  # 多源 BFS
    while q:
        r, c = q.popleft()
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and dist[nr][nc] == -1:
                dist[nr][nc] = dist[r][c] + 1
                q.append((nr, nc))
    return dist
```

**多源 BFS 的诀窍：** 把所有起点先放进队列，再照常处理。第一次到达目标时仍然是最短距离。

### 2.2 带状态的 BFS：带约束的最短路

对于「收集 K 把钥匙的最短路」或「最多打破 K 面墙的最短路」这类题，**节点是状态元组**，而不只是 `(r, c)`。

```python
def shortest_path_with_state(grid: list[list[int]], K: int) -> int:
    R, C = len(grid), len(grid[0])
    start = (0, 0, 0)                            # (r, c, 已打破的墙数)
    dist = {start: 0}
    q = deque([start])
    while q:
        r, c, k = q.popleft()
        if (r, c) == (R - 1, C - 1): return dist[(r, c, k)]
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < R and 0 <= nc < C): continue
            nk = k + grid[nr][nc]
            if nk > K: continue
            if (nr, nc, nk) not in dist:
                dist[(nr, nc, nk)] = dist[(r, c, k)] + 1
                q.append((nr, nc, nk))
    return -1
```

### 2.3 双向 BFS：当起点和终点都已知时

```python
def bidirectional_bfs(start: int, target: int, graph) -> int:
    if start == target: return 0
    front = {start}
    back = {target}
    dist_f = {start: 0}
    dist_b = {target: 0}
    level = 0
    while front and back:
        if len(front) > len(back): front, back, dist_f, dist_b = back, front, dist_b, dist_f
        nxt: set[int] = set()
        for u in front:
            for v in graph[u]:
                if v in back:
                    return dist_f[u] + 1 + dist_b[v]   # 在中间相遇
                if v not in dist_f:
                    dist_f[v] = dist_f[u] + 1
                    nxt.add(v)
        front = nxt
    return -1
```

常用于单词接龙（LC 127）， 单向 BFS 在大词表上会超时。

## 3. DFS：连通性 / 环 / 拓扑

```python
def dfs_iter(start: int, graph: dict[int, list[int]]) -> list[int]:
    order: list[int] = []
    seen: set[int] = set()
    stack: list[int] = [start]
    while stack:
        u = stack.pop()
        if u in seen: continue
        seen.add(u); order.append(u)
        for v in graph[u]:
            if v not in seen: stack.append(v)
    return order
```

**迭代 DFS 避免在 10^5+ 节点的图上出现 `RecursionError`。** 拿不准就用迭代。

### 3.1 递归 DFS 配合 `sys.setrecursionlimit`

```python
import sys
sys.setrecursionlimit(10**6)

def dfs(u: int, graph, seen: set[int]) -> None:
    seen.add(u)
    for v in graph[u]:
        if v not in seen:
            dfs(v, graph, seen)
```

### 3.2 连通分量 / 岛屿数量

```python
def num_islands(grid: list[list[str]]) -> int:
    R, C = len(grid), len(grid[0])
    seen = [[False] * C for _ in range(R)]
    def dfs(r: int, c: int) -> None:
        if not (0 <= r < R and 0 <= c < C): return
        if seen[r][c] or grid[r][c] != '1': return
        seen[r][c] = True
        for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            dfs(r + dr, c + dc)
    count = 0
    for r in range(R):
        for c in range(C):
            if grid[r][c] == '1' and not seen[r][c]:
                dfs(r, c); count += 1
    return count
```

## 4. 并查集（不相交集合）

用于 **动态连通性** 的数据结构，「这两个元素是否在同一集合，以及能否合并？」。

### 4.1 标准模板：路径压缩 + 按秩合并

```python
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n
        self.components = n                        # 不同集合的数量

    def find(self, x: int) -> int:                  # 路径压缩（迭代）
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:               # 压缩路径
            x, self.parent[x] = self.parent[x], root
        return root

    def union(self, x: int, y: int) -> bool:        # 若已在同一集合则返回 False
        rx, ry = self.find(x), self.find(y)
        if rx == ry: return False
        if self.rank[rx] < self.rank[ry]: rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]: self.rank[rx] += 1
        self.components -= 1
        return True
```

每次操作 **均摊 α(n) ≈ O(1)**。

### 4.2 典型应用

- **冗余边：** 逐条加边，第一条两端已经连通的边就是答案。
- **连通分量个数：** 所有 union 完成后看 `uf.components`。
- **账户合并：** 每个邮箱是一个节点，按用户聚合。
- **判断图是否是一棵树：** 恰好 `n - 1` 条边 **且** 所有边 union 完后 `components == 1`。

### 4.3 最小生成树：Kruskal

```python
def kruskal_mst(n: int, edges: list[tuple[int, int, int]]) -> int:
    edges.sort(key=lambda e: e[2])                  # 按权值排序
    uf = UnionFind(n)
    total = 0
    for u, v, w in edges:
        if uf.union(u, v): total += w               # 仅当连接两个分量时才加入
    return total if uf.components == 1 else -1      # 确保整体连通
```

## 5. 拓扑排序

仅适用于 **有向无环图（DAG）**。如果图有环，则不存在拓扑序。

### 5.1 Kahn 算法（BFS）： 最直观

```python
def topological_sort(n: int, edges: list[list[int]]) -> list[int]:
    g: list[list[int]] = [[] for _ in range(n)]
    indeg = [0] * n
    for u, v in edges:
        g[u].append(v); indeg[v] += 1
    q: deque[int] = deque([i for i in range(n) if indeg[i] == 0])
    order: list[int] = []
    while q:
        u = q.popleft(); order.append(u)
        for v in g[u]:
            indeg[v] -= 1
            if indeg[v] == 0: q.append(v)
    return order if len(order) == n else []        # 空列表表示有环
```

用于「课程安排」、「任务排序」、「编译顺序」等问题。

### 5.2 检测有向图中的环：DFS 三色标记

```python
def has_cycle_directed(n: int, edges: list[list[int]]) -> bool:
    g: list[list[int]] = [[] for _ in range(n)]
    for u, v in edges: g[u].append(v)
    color = [0] * n                                # 0=白，1=灰（递归栈中），2=黑（已完成）

    def dfs(u: int) -> bool:                       # 若发现环则返回 True
        color[u] = 1
        for v in g[u]:
            if color[v] == 1: return True          # 反向边 -> 环
            if color[v] == 0 and dfs(v): return True
        color[u] = 2
        return False

    for i in range(n):
        if color[i] == 0 and dfs(i): return True
    return False
```

灰色的含义是「当前在递归栈上」， 遇到一个灰色邻居就意味着存在反向边。

## 6. 最短路径

### 6.1 Dijkstra：非负权值，单源

```python
import heapq

def dijkstra(graph: dict[int, list[tuple[int, int]]], src: int, n: int) -> list[int]:
    dist = [float('inf')] * n
    dist[src] = 0
    pq: list[tuple[int, int]] = [(0, src)]          # (dist, node)
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue                   # 陈旧条目，跳过
        for v, w in graph[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                heapq.heappush(pq, (dist[v], v))
    return dist
```

**陈旧条目跳过** 必不可少，跳过才能避免同一个节点被处理多次。

### 6.2 Bellman-Ford：允许负权，可检测负环

```python
def bellman_ford(n: int, edges: list[tuple[int, int, int]], src: int) -> list[int]:
    dist = [float('inf')] * n
    dist[src] = 0
    for _ in range(n - 1):                         # 松弛所有边 n-1 轮
        updated = False
        for u, v, w in edges:
            if dist[u] != float('inf') and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                updated = True
        if not updated: break
    # 可选：再多一轮检测负环
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            raise ValueError("negative cycle reachable from src")
    return dist
```

时间复杂度 O(V·E)。可用于「K 站内最便宜的航班」（LC 787，注意那题限制恰好 K 站，所以要使用限制为 K 轮松弛的变体）。

### 6.3 Floyd-Warshall：全源最短路，稠密图

```python
def floyd_warshall(n: int, edges: list[tuple[int, int, int]]) -> list[list[int]]:
    INF = float('inf')
    d = [[INF] * n for _ in range(n)]
    for i in range(n): d[i][i] = 0
    for u, v, w in edges: d[u][v] = min(d[u][v], w)
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if d[i][k] + d[k][j] < d[i][j]:
                    d[i][j] = d[i][k] + d[k][j]
    return d
```

时间复杂度 O(V³)。n ≤ 200 时可用。三重循环的顺序必须是 **k, i, j**，`k`（中间节点）必须放在最外层。

### 6.4 A*：启发式引导的最短路

在已知终点的网格上求最短路时，A* 配合曼哈顿距离启发式能极大剪枝。

```python
import heapq

def astar(grid: list[list[int]], start: tuple[int, int], goal: tuple[int, int]) -> int:
    R, C = len(grid), len(grid[0])
    def h(r, c): return abs(r - goal[0]) + abs(c - goal[1])
    pq = [(h(*start), 0, start)]
    g = {start: 0}
    while pq:
        _, d, u = heapq.heappop(pq)
        if u == goal: return d
        if d > g.get(u, float('inf')): continue
        r, c = u
        for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and grid[nr][nc] == 0:
                nd = d + 1
                if nd < g.get((nr, nc), float('inf')):
                    g[(nr, nc)] = nd
                    heapq.heappush(pq, (nd + h(nr, nc), nd, (nr, nc)))
    return -1
```

## 7. 二分图 / 染色

```python
def is_bipartite(graph: list[list[int]], n: int) -> bool:
    color = [-1] * n
    for start in range(n):
        if color[start] != -1: continue
        color[start] = 0
        q = deque([start])
        while q:
            u = q.popleft()
            for v in graph[u]:
                if color[v] == -1:
                    color[v] = color[u] ^ 1
                    q.append(v)
                elif color[v] == color[u]:
                    return False
    return True
```

二分图检测就是带染色的 BFS。可用于「可能的二分」（LC 886）。

## 8. 最小生成树

- **Kruskal：** 把边按权值排序，用并查集。写起来更简单。
- **Prim：** 从任意节点出发，每次加入最便宜的跨边来扩展树，基于堆，O(E log V)。

```python
def prim(n: int, graph: list[list[tuple[int, int]]]) -> int:
    seen = [False] * n
    seen[0] = True
    pq = graph[0][:]                              # 元素为 (w, v) 的列表
    heapq.heapify(pq)
    total = 0
    count = 1
    while pq and count < n:
        w, v = heapq.heappop(pq)
        if seen[v]: continue
        seen[v] = True
        total += w; count += 1
        for w2, v2 in graph[v]:
            if not seen[v2]: heapq.heappush(pq, (w2, v2))
    return total if count == n else -1
```

## 9. 网络流：Ford-Fulkerson（BFS 实现即 Edmonds-Karp）

在 Hot 150 中只会出现「求最大匹配 / 最大流」的题（比较少见）。基本模板：

```python
def bfs_augmenting(s: int, t: int, cap: list[list[int]], parent: list[int]) -> bool:
    visited = [False] * len(cap)
    visited[s] = True
    q = deque([s])
    while q:
        u = q.popleft()
        for v in range(len(cap)):
            if not visited[v] and cap[u][v] > 0:
                visited[v] = True
                parent[v] = u
                if v == t: return True
                q.append(v)
    return False

def max_flow(s: int, t: int, cap: list[list[int]]) -> int:
    n = len(cap)
    flow = 0
    parent = [-1] * n
    while bfs_augmenting(s, t, cap, parent):
        # 沿路径找瓶颈
        v = t; bottleneck = float('inf')
        while v != s:
            u = parent[v]; bottleneck = min(bottleneck, cap[u][v]); v = u
        # 更新残余容量
        v = t
        while v != s:
            u = parent[v]
            cap[u][v] -= bottleneck
            cap[v][u] += bottleneck
            v = u
        flow += bottleneck
    return flow
```

Edmonds-Karp 的复杂度是 O(V · E²)。只有「安排考试的最大学生数」、「二分图最大匹配」之类的问题会用到。

## 10. 识别信号

| 描述 | 模式 |
|---|---|
| 「shortest path」、「fewest steps」、「minimum moves」（无权） | BFS |
| 「minimum cost」、「shortest distance」（权值 ≥ 0） | Dijkstra |
| 「cheapest flight within K stops」 | Bellman-Ford，限制 K 轮松弛 |
| 「all pairs shortest path」、「city with smallest neighboring distance」 | Floyd-Warshall |
| 「course schedule」、「task order」、「dependencies」 | 拓扑排序（Kahn） |
| 「redundant connection」、「merge accounts」 | 并查集 |
| 「number of islands」、「connected components」 | DFS / BFS / 并查集 |
| 「bipartite」、「can split into two groups」 | BFS 染色 |
| 「minimum spanning tree」 | Kruskal / Prim |
| 「is there a path from A to B?」 | BFS / DFS / 并查集（离线） |
| 「max flow」、「min cut」、「maximum matching」 | Edmonds-Karp |
| 「word ladder」、「transform word A to B」 | 双向 BFS |
| 「walls and gates」、「01 matrix」、「nearest X」 | 多源 BFS |
| 「rotting oranges」 | BFS 多源，记录时间 |
| 「snakes and ladders」 | BFS，棋盘状态就是节点 |
| 「second minimum time」 | 改造的 BFS：同时跟踪最短和次短 |

## 11. 思考框架

1. **明确节点和边的类型。** 节点是位置？状态？还是二元组（位置, 状态）？
2. **有向还是无向？** 影响环检测和拓扑排序。
3. **代价一致还是有权？** 一致 → BFS。有权 → Dijkstra（负权则用 Bellman-Ford）。
4. **单源还是多源？** 多源：把所有源点一起放进队列。
5. **求最短路还是只求可达？** 可达 → DFS / 并查集即可。
6. **需要检测环吗？** 无向图：并查集即可（每条边要么合并集合要么发现环）。有向图：三色 DFS。
7. **边权有负吗？** 用 Bellman-Ford 或 SPFA。
8. **是否有「最多 K 站」或「最多 K 个障碍」之类的约束？** 把状态做成 `(node, k_used)` 元组，再对元组做 BFS。
9. **图是隐式的吗？** 例如单词接龙中图并未给出，需要通过字符变换或预计算的通配模式（如 `*ot, h*t, ho*`）来构造邻接。

## 12. 常见错误

1. **大连通分量触发 `RecursionError`。** 用 `sys.setrecursionlimit(10**6)`，或改用迭代 BFS/DFS。
2. **BFS 中 visited 的检查位置：** 必须在 **入队时** 设置 visited，弹出时设置会让重复节点进队。
3. **Dijkstra 没做陈旧检查：** 弹出后必须判断 `if d > dist[u]: continue`：堆里可能存在距离更大的陈旧条目。
4. **Floyd-Warshall 的循环顺序：** `for k ... for i ... for j ...`：k 必须是最外层。顺序错结果就错。
5. **拓扑排序的环检测：** Kahn BFS 结束后，若 `len(order) != n` 就说明有环，别忘了这一步。
6. **负环检测：** Bellman-Ford 跑 `n - 1` 轮后，再多跑一轮，若还有更新则存在负环。
7. **忘记处理非连通图：** 从单个源出发的 BFS 只覆盖一个连通分量。如果需要所有分量，要遍历所有节点。
8. **把 `dist` 同时当作 BFS 的 visited 和距离：** `dist == -1` 表示未访问，一旦赋值就不再重新入队。
9. **`defaultdict` 邻接表删除键后：** 读取时可能把已删除的键重新创建。只读场景用 `dict` 加 `.get()`。
10. **网格越界：** 访问 `grid[nr][nc]` **之前** 必须先判断 `0 <= nr < R and 0 <= nc < C`。

## 13. 训练清单：Hot 150 图论题

| # | 题目 | 模式 |
|---|---------|---------|
| 1 | 200. Number of Islands | 3.2：DFS/BFS 求连通分量 |
| 2 | 133. Clone Graph | DFS/BFS 加 old→new 映射 |
| 3 | 695. Max Area of Island | 3.2，加大小统计 |
| 4 | 994. Rotting Oranges | 2：多源 BFS |
| 5 | 286. Walls and Gates | 2：多源 BFS |
| 6 | 542. 01 Matrix | 2：多源 BFS |
| 7 | 207. Course Schedule | 5：Kahn 算法 |
| 8 | 210. Course Schedule II | 5：返回拓扑序 |
| 9 | 323. Number of Connected Components | 4：并查集 |
| 10 | 684. Redundant Connection | 4：并查集返回首条 |
| 11 | 547. Number of Provinces | 3：对反图做 DFS |
| 12 | 130. Surrounded Regions | 3：从边界出发 DFS |
| 13 | 417. Pacific Atlantic Water Flow | 3：从海洋多源 DFS |
| 14 | 787. Cheapest Flights Within K Stops | 6.2：Bellman-Ford 变体 |
| 15 | 743. Network Delay Time | 6.1：Dijkstra |
| 16 | 1514. Path with Maximum Probability | Dijkstra，改为最大化乘积 |
| 17 | 1631. Path With Minimum Effort | Dijkstra 或 二分 + BFS |
| 18 | 785. Is Graph Bipartite? | 7：BFS 染色 |
| 19 | 886. Possible Bipartition | 7：BFS 染色 |
| 20 | 1584. Min Cost to Connect All Points | 8：MST（Prim 或 Kruskal） |
| 21 | 127. Word Ladder | 2.3：双向 BFS |
| 22 | 433. Minimum Genetic Mutation | 2：BFS（单词接龙变体） |
| 23 | 752. Open the Lock | 2：8192 个状态的 BFS |
| 24 | 909. Snakes and Ladders | 2：BFS |
| 25 | 1091. Shortest Path in Binary Matrix | 2：8 方向 BFS |
| 26 | 1926. Nearest Exit from Maze Entrance | 2：BFS |
| 27 | 1971. Find if Path Exists in Graph | 4：并查集 或 BFS |
| 28 | 841. Keys and Rooms | 3：DFS 求可达性 |
| 29 | 1557. Minimum Number of Vertices to Reach All | 类拓扑：只取入度为 0 的「源」节点 |
| 30 | 1192. Critical Connections in Graph | Tarjan 求桥 |
| 31 | 2101. Detonate the Maximum Bombs | 2：每个源点做 BFS |
| 32 | 1168. Optimize Water Distribution | MST 加虚拟源 |
| 33 | 269. Alien Dictionary | 5：在字符图上做拓扑 |
| 34 | 1135. Connecting Cities With Minimum Cost | 8：MST |

**模式锁定计划：**
- **BFS 系列**（题 1-6、21-26、31）：连做 4-5 道。目标：BFS 模板形成肌肉记忆。
- **DFS 系列**（题 1-3、5、11-13）：递归心智模型与二叉树一致（见第 06 篇）。
- **并查集**（9、10、19、27、28、32）：连续做，固化 DSU 模板。
- **Dijkstra**（15、16、17）：三道题难度递增。
- **拓扑**（7、8、29、33）：Kahn 算法足以应对全部。

---

## 最终心智模型

面对每道图论题，先写出下面的骨架：

```python
def solve(input) -> Answer:
    # 1. 建图（节点 + 边）。节点是什么？边是什么？
    # 2. 问题是什么？可达性 / 最短路 / 拓扑 / MST / 染色
    # 3. 选择模板：
    #    - 一致代价 + 可达性：BFS
    #    - 一致代价 + 最短路：BFS
    #    - 有权 + 单源：Dijkstra
    #    - 有权 + 负权：Bellman-Ford
    #    - 全源，n 较小：Floyd-Warshall
    #    - DAG 序：Kahn
    #    - 合并集合：并查集
    # 4. 边界：非连通、单节点、环、多分量。
```

只要能根据题意完成第 1-3 步，答案就是机械操作。