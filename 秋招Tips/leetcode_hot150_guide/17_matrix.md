# 17. 矩阵

## 核心概念

Hot 150 中的矩阵题大致可以分成三类：

1. **遍历与变换** —— 螺旋遍历、旋转、置零、生命游戏。
2. **网格上的 BFS / DFS** —— 岛屿问题、墙与门、最短路径、障碍。
3. **网格上的 DP** —— 不同路径、最小路径和、最大正方形（在文件 12 介绍）。

本文件覆盖前两类（遍历与图论类），网格 DP 在文件 12。

## 模式与模板

### 1. 螺旋遍历

```python
def spiral_order(matrix: list[list[int]]) -> list[int]:
    out: list[int] = []
    top, bottom = 0, len(matrix) - 1
    left, right = 0, len(matrix[0]) - 1
    while top <= bottom and left <= right:
        for c in range(left, right + 1): out.append(matrix[top][c])
        top += 1
        for r in range(top, bottom + 1): out.append(matrix[r][right])
        right -= 1
        if top <= bottom:
            for c in range(right, left - 1, -1): out.append(matrix[bottom][c])
            bottom -= 1
        if left <= right:
            for r in range(bottom, top - 1, -1): out.append(matrix[r][left])
            left += 1
    return out
```

**核心思路：** 四个方向（右、下、左、上），每走完一个方向就收缩对应的边界。两个内层 `if` 是为了处理只剩一行或一列的退化情况。

### 2. 生成螺旋矩阵

模式 1 的逆过程：按螺旋顺序走一遍，依次填入 1、2、3、……。

### 3. 矩阵原地顺时针旋转 90° —— 见文件 16

转置 + 每行反转。

### 4. 矩阵置零 —— 见文件 16

用第一行和第一列做标记。

### 5. 生命游戏 —— 同时更新

要让所有格子"同时"更新且不用额外空间，可以用第 0 位存当前状态、第 1 位存下一状态：

```python
def game_of_life(board: list[list[int]]) -> None:
    m, n = len(board), len(board[0])
    def live_neighbors(r: int, c: int) -> int:
        cnt = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0: continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < m and 0 <= nc < n and board[nr][nc] & 1:
                    cnt += 1
        return cnt
    for r in range(m):
        for c in range(n):
            cnt = live_neighbors(r, c)
            if board[r][c] == 1:
                if cnt in (2, 3): board[r][c] |= 2     # 下一状态为 1
            else:
                if cnt == 3: board[r][c] |= 2
    for r in range(m):
        for c in range(n):
            board[r][c] >>= 1
```

第 0 位 = 当前状态，第 1 位 = 下一状态。所有格子算完后，整体右移一位提交新状态。

### 6. 岛屿数量 —— DFS / BFS / 并查集

```python
def num_islands(grid: list[list[str]]) -> int:
    R, C = len(grid), len(grid[0])
    seen = [[False] * C for _ in range(R)]
    def dfs(r: int, c: int) -> None:
        if r < 0 or r >= R or c < 0 or c >= C: return
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

对于非常大的网格，用**迭代式 BFS** 或**并查集**避免递归深度限制。

### 7. 岛屿最大面积 —— 带回传大小的 DFS

```python
def max_area_of_island(grid: list[list[int]]) -> int:
    R, C = len(grid), len(grid[0])
    def dfs(r: int, c: int) -> int:
        if r < 0 or r >= R or c < 0 or c >= C: return 0
        if grid[r][c] != 1: return 0
        grid[r][c] = 0                              # 原地标记已访问
        return 1 + dfs(r+1, c) + dfs(r-1, c) + dfs(r, c+1) + dfs(r, c-1)
    return max((dfs(r, c) for r in range(R) for c in range(C)), default=0)
```

### 8. 被围绕的区域 —— 围捕

```python
def solve(board: list[list[str]]) -> None:
    R, C = len(board), len(board[0])
    # 把与边界连通的 'O' 标记为 'S'（安全的）
    def dfs(r: int, c: int) -> None:
        if not (0 <= r < R and 0 <= c < C) or board[r][c] != 'O': return
        board[r][c] = 'S'
        for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            dfs(r + dr, c + dc)
    for r in range(R):
        dfs(r, 0); dfs(r, C - 1)
    for c in range(C):
        dfs(0, c); dfs(R - 1, c)
    # 现在把剩下的 'O'（被围绕的）翻成 'X'，把 'S' 恢复为 'O'
    for r in range(R):
        for c in range(C):
            if board[r][c] == 'O': board[r][c] = 'X'
            elif board[r][c] == 'S': board[r][c] = 'O'
```

**核心思路：** 一个 `O` 能存活当且仅当它有一条通往边界的路径。从所有边界上的 `O` 开始做 flood-fill 标记，剩下的未被标记的 `O` 就是被围捕的。

### 9. 太平洋大西洋水流问题 —— 多源

与第 8 题同样的骨架：从所有边界格子出发做 BFS/DFS，做两次（一次从太平洋能到达的，一次从大西洋能到达的），最后取交集。

### 10. 墙与门 —— 多源 BFS

已经在文件 09 中介绍（模式 2.1）。

### 11. 01 矩阵 —— 多源 BFS

已经在文件 09 中介绍。

### 12. 二进制矩阵中的最短路径（8 方向）

用 BFS，但邻居是 8 个方向而不是 4 个。

### 13. 最大正方形 —— DP

`dp[i][j]` = 以 `(i, j)` 为右下角的最大正方形的边长：

```python
def maximal_square(matrix: list[list[str]]) -> int:
    R, C = len(matrix), len(matrix[0])
    dp = [[0] * (C + 1) for _ in range(R + 1)]
    best = 0
    for i in range(1, R + 1):
        for j in range(1, C + 1):
            if matrix[i - 1][j - 1] == '1':
                dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1
                best = max(best, dp[i][j])
    return best * best
```

`dp[i][j] = min(上, 左, 左上) + 1`，因为能扩展到这里的正方形大小受三者中最小者限制。

### 14. 网格上的二分图（棋盘式染色）

跳过——网格天然就是二分图，每个格子 `(r, c)` 的颜色就是 `(r + c) % 2`。一般只在图论题里才用到。

## 识别信号

- "spiral order"、"generate spiral matrix" → 模式 1 / 2。
- "rotate image"、"transpose" → 见文件 16。
- "number of islands"、"max area of island"、"count components" → DFS / BFS / 并查集。
- "surrounded regions"、"capture" → 从边界开始的多源 DFS。
- "01 matrix"、"walls and gates" → 多源 BFS（见文件 09）。
- "shortest path in binary matrix"、"shortest bridge" → BFS，可能带一些变化。
- "maximal square"、"maximal rectangle" → 网格 DP（见文件 12）或单调栈（见文件 04）。

## 思考框架

1. **是对矩阵的变换吗？** → 原地算法，用一些格子做标记。
2. **是在网格上做搜索吗？** → 求最短用 BFS，求连通性用 DFS。
3. **是否有多个起点？** → 把所有起点一次性压入队列。
4. **需要"已访问"标记吗？** → 用一个独立的布尔矩阵，或原地标记（如把 `'1'` 改成 `'0'`、`'#'` 等）。
5. **网格 DP？** → 见文件 12 的模式。

## Hot 150 例题

- **54. Spiral Matrix** —— 模式 1。
- **59. Spiral Matrix II** —— 模式 2。
- **48. Rotate Image** —— 见文件 16。
- **73. Set Matrix Zeroes** —— 见文件 16。
- **289. Game of Life** —— 模式 5。
- **200. Number of Islands** —— 模式 6。
- **695. Max Area of Island** —— 模式 7。
- **130. Surrounded Regions** —— 模式 8。
- **417. Pacific Atlantic Water Flow** —— 模式 9。
- **286. Walls and Gates** —— 见文件 09。
- **542. 01 Matrix** —— 见文件 09。
- **994. Rotting Oranges** —— 见文件 09。
- **1091. Shortest Path in Binary Matrix** —— 见文件 09，但用 8 方向。
- **934. Shortest Bridge** —— 用 DFS 找第一座岛，再用 BFS 到达第二座岛。
- **1254. Number of Closed Islands** —— 从边界做 DFS（模式 8 的变体）。
- **1020. Number of Enclaves** —— 模式 8 的变体。
- **1905. Count Sub Islands** —— 同时在两个网格上做 DFS。
- **221. Maximal Square** —— 模式 13。
- **85. Maximal Rectangle** —— 见文件 04（直方图 + 栈）。
- **36. Valid Sudoku** —— 见文件 01（行、列、宫分别哈希）。
- **37. Sudoku Solver** —— 回溯（见文件 11）。
- **51. N-Queens** —— 见文件 11。
- **79. Word Search** —— 见文件 11。
- **212. Word Search II** —— 见文件 14（字典树）。
- **329. Longest Increasing Path in a Matrix** —— DFS + 记忆化（网格 DP）。
- **62. Unique Paths** —— 见文件 12。
- **64. Minimum Path Sum** —— 见文件 12。

## 常见陷阱

- **螺旋遍历只剩一行/一列时：** 走完上面一行并把 `top` 减一后，必须先判断 `top <= bottom` 再往左走，否则会重复遍历那一行。
- **大网格的 DFS 递归深度：** 300×300 全 `'1'` 的网格会让递归深达 90000——必须 `sys.setrecursionlimit(10**6)`，或者用迭代式 BFS。
- **原地标记会破坏输入：** 如果通过修改格子来标记已访问，会改掉输入数据。在 Hot 150 里一般没事；否则用独立的 `seen` 矩阵。
- **8 方向 vs 4 方向：** 看清楚题目要求的是不是对角邻居。常见的 bug 是需要 8 方向时却用了 4 方向（如二进制矩阵中的最短路径）。
- **坐标约定：** `(r, c)` 表示行在前、列在后。很多 bug 都来自把 `r` 和 `c` 写反。
- **`matrix[r][c]` 不是 `matrix[c][r]`：** 行是外层维度，列是内层维度。
- **生命游戏的位运算技巧：** 别忘了最后整体 `>>= 1` 来提交下一状态。
- **最大正方形的边界情况：** `dp[0][j]` 和 `dp[i][0]` 都是 0（矩阵外不存在正方形）。通过预留一行一列的 padding，递推式能自然处理边界。
- **数独校验器：** 每个格子恰好属于一个 3×3 宫：`box_index = (r // 3) * 3 + (c // 3)`。
- **最短桥：** 用 DFS 标记完第一座岛后，要从第一座岛的**所有格子**同时做 BFS（多源），直到触及第二座岛。
