# 11. 回溯

## 核心概念

回溯通过**逐步构建**所有候选解，并在确定某个部分解不可行时立即放弃（"剪枝"）来枚举**所有候选解**。它是**状态树**上的 DFS，树的每一层代表一次决策。

通用模板：

```python
def backtrack(state, choices, partial, result):
    if is_complete(partial):
        result.append(partial.copy())              # 重要：拷贝
        return
    for choice in choices(state):
        if is_valid(partial, choice):              # 剪枝
            apply(partial, choice)                 # 修改状态
            backtrack(state, choices, partial, result)
            undo(partial, choice)                  # 撤销
```

Hot 150 中有三大子模式：

1. **排列 / 组合 / 子集** —— 选择空间会缩小或扩大。
2. **网格搜索** —— 单词搜索、N 皇后。
3. **分割问题** —— 把字符串/数组切成合法的片段。

## 模式与模板

### 1. 子集 —— 每个下标处的决策：选或不选

```python
def subsets(nums: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    def bt(i: int, cur: list[int]) -> None:
        if i == len(nums):
            out.append(cur.copy()); return
        # 不选 nums[i]
        bt(i + 1, cur)
        # 选 nums[i]
        cur.append(nums[i]); bt(i + 1, cur); cur.pop()
    bt(0, [])
    return out
```

另一种写法：每一步对**所有要包含的下一个元素**进行分支（没有"跳过"的路径）：

```python
def subsets_v2(nums: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    def bt(start: int, cur: list[int]) -> None:
        out.append(cur.copy())                     # 每个节点都是一个合法子集
        for i in range(start, len(nums)):
            cur.append(nums[i]); bt(i + 1, cur); cur.pop()
    bt(0, [])
    return out
```

### 2. 含重复元素的子集 —— 先排序再跳过

```python
def subsets_with_dup(nums: list[int]) -> list[list[int]]:
    nums.sort()                                     # 排序使重复元素相邻
    out: list[list[int]] = []
    def bt(start: int, cur: list[int]) -> None:
        out.append(cur.copy())
        for i in range(start, len(nums)):
            if i > start and nums[i] == nums[i - 1]: continue  # 跳过同一层的重复元素
            cur.append(nums[i]); bt(i + 1, cur); cur.pop()
    bt(0, [])
    return out
```

**去重规则：**"若 `i > start` 且 `nums[i] == nums[i-1]`，则跳过"——在同一决策层不要重复选相同的值。先排序，让重复元素相邻。

### 3. 排列

```python
def permute(nums: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    used = [False] * len(nums)
    def bt(cur: list[int]) -> None:
        if len(cur) == len(nums):
            out.append(cur.copy()); return
        for i in range(len(nums)):
            if used[i]: continue
            used[i] = True; cur.append(nums[i])
            bt(cur)
            cur.pop(); used[i] = False
    bt([])
    return out
```

### 4. 含重复元素的排列

```python
def permute_unique(nums: list[int]) -> list[list[int]]:
    nums.sort()
    out: list[list[int]] = []
    used = [False] * len(nums)
    def bt(cur: list[int]) -> None:
        if len(cur) == len(nums):
            out.append(cur.copy()); return
        for i in range(len(nums)):
            if used[i]: continue
            # 若 nums[i] == nums[i-1] 且前一个相同的未被使用，则跳过。
            # 原因：在同一层，前一个相同的元素已经开启了这条分支。
            if i > 0 and nums[i] == nums[i - 1] and not used[i - 1]: continue
            used[i] = True; cur.append(nums[i])
            bt(cur)
            cur.pop(); used[i] = False
    bt([])
    return out
```

排列的去重规则比较微妙："若 `i > 0 and nums[i] == nums[i-1]` 且 `not used[i-1]`，则跳过"。`not used[i-1]` 这个条件保证我们只在**前一个相同元素已被使用（即更深的层）**之后才取后一个相同的元素，避免同一层产生重复。

### 5. 组合 —— 从 N 中选 K 个

```python
def combine(n: int, k: int) -> list[list[int]]:
    out: list[list[int]] = []
    def bt(start: int, cur: list[int]) -> None:
        if len(cur) == k:
            out.append(cur.copy()); return
        # 剪枝：只有剩余元素足够时才继续枚举
        for i in range(start, n - (k - len(cur)) + 2):
            cur.append(i); bt(i + 1, cur); cur.pop()
    bt(1, [])
    return out
```

`range(start, n - (k - len(cur)) + 2)` 这个剪枝是关键优化——若剩余元素不足以凑齐组合，就提前停止。

### 6. 组合总和（可重复使用）

```python
def combination_sum(candidates: list[int], target: int) -> list[list[int]]:
    out: list[list[int]] = []
    def bt(start: int, remaining: int, cur: list[int]) -> None:
        if remaining == 0:
            out.append(cur.copy()); return
        if remaining < 0: return
        for i in range(start, len(candidates)):
            cur.append(candidates[i])
            bt(i, remaining - candidates[i], cur)  # 同一个 i：可无限次复用
            cur.pop()
    bt(0, target, [])
    return out
```

若要求"每个数字只能用一次"，则用 `bt(i + 1, ...)`。若输入含重复元素，先排序并跳过同一层的重复。

### 7. 单词搜索 —— 网格 DFS

```python
def exist(board: list[list[str]], word: str) -> bool:
    R, C = len(board), len(board[0])
    def bt(r: int, c: int, i: int) -> bool:
        if i == len(word): return True
        if not (0 <= r < R and 0 <= c < C) or board[r][c] != word[i]: return False
        tmp, board[r][c] = board[r][c], '#'         # 标记已访问
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            if bt(r + dr, c + dc, i + 1): return True
        board[r][c] = tmp                           # 还原
        return False
    for r in range(R):
        for c in range(C):
            if bt(r, c, 0): return True
    return False
```

"原地标记"技巧（`board[r][c] = '#'`）省去了单独的 visited 集合——当网格本身是可变输入时特别好用。

### 8. N 皇后

```python
def solve_n_queens(n: int) -> list[list[str]]:
    out: list[list[str]] = []
    cols: set[int] = set()
    diag1: set[int] = set()                        # r - c（主对角线方向）
    diag2: set[int] = set()                        # r + c（副对角线）
    board: list[int] = []                          # 每行皇后所在的列下标

    def bt(r: int) -> None:
        if r == n:
            out.append(['.' * c + 'Q' + '.' * (n - c - 1) for c in board])
            return
        for c in range(n):
            if c in cols or (r - c) in diag1 or (r + c) in diag2: continue
            cols.add(c); diag1.add(r - c); diag2.add(r + c); board.append(c)
            bt(r + 1)
            cols.remove(c); diag1.remove(r - c); diag2.remove(r + c); board.pop()

    bt(0)
    return out
```

对角线技巧：同一条"主"对角线上的格子共享 `r - c`；同一条"副"对角线上的格子共享 `r + c`。用 set 实现 O(1) 检查。

### 9. 分割 —— 切成合法片段

```python
def partition(s: str) -> list[list[str]]:
    out: list[list[str]] = []
    def is_pal(s: str, l: int, r: int) -> bool:
        while l < r:
            if s[l] != s[r]: return False
            l += 1; r -= 1
        return True
    def bt(start: int, cur: list[str]) -> None:
        if start == len(s):
            out.append(cur.copy()); return
        for end in range(start, len(s)):
            if is_pal(s, start, end):
                cur.append(s[start:end + 1])
                bt(end + 1, cur)
                cur.pop()
    bt(0, [])
    return out
```

### 10. 电话号码的字母组合

```python
def letter_combinations(digits: str) -> list[str]:
    if not digits: return []
    mp = {'2': 'abc', '3': 'def', '4': 'ghi', '5': 'jkl',
          '6': 'mno', '7': 'pqrs', '8': 'tuv', '9': 'wxyz'}
    out: list[str] = []
    def bt(i: int, cur: list[str]) -> None:
        if i == len(digits):
            out.append(''.join(cur)); return
        for ch in mp[digits[i]]:
            cur.append(ch); bt(i + 1, cur); cur.pop()
    bt(0, [])
    return out
```

### 11. 生成括号 —— 统计左/右括号数

```python
def generate_parenthesis(n: int) -> list[str]:
    out: list[str] = []
    def bt(o: int, c: int, cur: list[str]) -> None:
        if len(cur) == 2 * n:
            out.append(''.join(cur)); return
        if o < n: cur.append('('); bt(o + 1, c, cur); cur.pop()
        if c < o: cur.append(')'); bt(o, c + 1, cur); cur.pop()
    bt(0, 0, [])
    return out
```

状态就是两个计数：`o`（已使用的左括号数）和 `c`（已使用的右括号数）。`o < n` 时可以加 `(`；`c < o` 时可以加 `)`。

## 识别信号

- "所有排列 / 组合 / 子集 / 分割" → 回溯。
- "N 皇后"、"合法放置" → 带状态集合的回溯。
- "单词搜索"、"棋盘上的字母路径" → 网格回溯。
- "生成所有合法的 ..."、"把字符串切分成 ..." → 分割类回溯。
- "字母组合"、"数字组合" → 选项列表回溯。

## 思考框架

1. **每一步的"决策"是什么？** 包含/排除某个元素、选某个位置、追加某个字符、放一个皇后。
2. **部分解的状态是什么？** 一个列表、一个字符串、一个棋盘、(左括号数, 右括号数) 的计数。
3. **什么时候部分解完成？** 长度达到目标、或所有元素都已选完。
4. **什么时候剪枝？** 越早越好——一旦部分解违反约束就立刻停。
5. **怎么撤销？** 严格镜像"应用"那一步。可以用 `cur.append(x)` / `cur.pop()`，或 set 的 `add` / `remove`。
6. **去重：** 先排序，再用"同一层若与前一个相同则跳过"的规则。

## Hot 150 例题

- **78. Subsets** —— 模式 1。
- **90. Subsets II** —— 模式 2。
- **46. Permutations** —— 模式 3。
- **47. Permutations II** —— 模式 4。
- **77. Combinations** —— 模式 5。
- **39. Combination Sum** —— 模式 6。
- **40. Combination Sum II** —— 模式 6 + 去重。
- **216. Combination Sum III** —— 模式 6 + 数字约束。
- **79. Word Search** —— 模式 7。
- **212. Word Search II** —— 模式 7 + 字典树（第 14 章），用于提前剪枝。
- **51. N-Queens** —— 模式 8。
- **52. N-Queens II** —— 模式 8，只需计数。
- **131. Palindrome Partitioning** —— 模式 9。
- **93. Restore IP Addresses** —— 模式 9 的变体。
- **17. Letter Combinations of a Phone Number** —— 模式 10。
- **22. Generate Parentheses** —— 模式 11。
- **301. Remove Invalid Parentheses** —— BFS 或带最小删除次数上界的回溯。
- **1087. Brace Expansion** —— 模式 10 的变体。

## 易错点

- **加入结果时务必 `copy()`。** 否则所有条目都会引用同一个列表，回溯结束后它会被改回空状态。
- **去重规则的微妙之处：** 对于组合/子集，"若 `i > start and nums[i] == nums[i-1]` 则跳过"——这里的 `start` 是循环的起点，而不是 0。对于排列，"若 `i > 0 and nums[i] == nums[i-1]` 且 `not used[i-1]`，则跳过"。
- **先去重再排序。** 否则重复元素不会相邻。
- **组合的剪枝：** `range(start, n - (k - len(cur)) + 2)` 在 `n - start < k - len(cur)` 时能省掉时间——根本不会进入循环。不剪的话会在死分支上浪费时间。
- **单词搜索的原地标记** 省内存，但要求每条返回路径（包括错误路径）都还原。
- **N 皇后对角线集合：** `r - c` 和 `r + c` 都需要；只用其中一个会漏掉一半冲突。
- **无限递归：** 确保每次递归调用都严格推进状态（`cur` 变长、`start` 变大、`used` 更多）。一个常见 bug：写成 `bt(start, cur)` 而不是 `bt(start + 1, cur)`。
- **时间复杂度：** 回溯本质上是指数级的。别指望多项式时间——把精力放在剪枝上。
- **`pop()` 的顺序：** 应用了多处修改时，要按**逆序**（LIFO）撤销——`append(a); append(b)` 对应 `pop(); pop()`。

(End of file - total 303 lines)
