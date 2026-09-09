# 14. 字典树（Trie）

## 核心概念

字典树（前缀树）用于存储字符串，**所有共享前缀的字符串从根节点开始共享同一条路径**。插入和查找的时间复杂度都是 O(L)，其中 L 是字符串长度，与存储了多少个字符串无关。

常见应用场景：
- 前缀查询："以 X 开头的所有单词"。
- 在棋盘上搜索单词（提前剪掉不可能的路径）。
- 数组中两个数的最大异或值（将数字以二进制字符串形式存入字典树）。
- 自动补全 / 字典。

## 节点定义

```python
class TrieNode:
    __slots__ = ('children', 'end')
    def __init__(self):
        self.children: dict[str, TrieNode] = {}
        self.end: bool = False
```

`__slots__` 能显著减少大型字典树的内存占用。

## 模式与模板

### 1. 标准字典树 —— 插入与查找

```python
class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.end = True

    def search(self, word: str) -> bool:
        node = self._walk(word)
        return node is not None and node.end

    def starts_with(self, prefix: str) -> bool:
        return self._walk(prefix) is not None

    def _walk(self, s: str) -> TrieNode | None:
        node = self.root
        for ch in s:
            if ch not in node.children: return None
            node = node.children[ch]
        return node
```

### 2. 单词搜索 II —— 字典树 + 回溯

在棋盘中同时搜索多个单词时，先用所有单词构建字典树；然后对棋盘做 DFS，**当字典树没有匹配的子节点时立即停止**。

```python
def find_words(board: list[list[str]], words: list[str]) -> list[str]:
    R, C = len(board), len(board[0])
    root = TrieNode()
    for w in words:
        node = root
        for ch in w:
            if ch not in node.children: node.children[ch] = TrieNode()
            node = node.children[ch]
        node.end = True

    out: list[str] = []

    def dfs(r: int, c: int, node: TrieNode, path: list[str]) -> None:
        if not (0 <= r < R and 0 <= c < C): return
        ch = board[r][c]
        if ch not in node.children: return
        nxt = node.children[ch]
        path.append(ch)
        if nxt.end:
            out.append(''.join(path))
            nxt.end = False                          # 避免重复收集
        board[r][c] = '#'                            # 标记已访问
        for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            dfs(r + dr, c + dc, nxt, path)
        board[r][c] = ch                             # 取消标记
        path.pop()
        # 优化：当节点变为叶子时删除，加速后续搜索
        if not nxt.children:
            del node.children[ch]

    for r in range(R):
        for c in range(C):
            dfs(r, c, root, [])
    return out
```

两个关键优化：
1. 收集到一个单词后将 `node.end = False`，避免从不同路径重复收集同一个单词。
2. 当字典树节点的孩子全部为空时将其删除，加速后续搜索。

### 3. 最大异或对 —— 二进制字典树

```python
def find_maximum_xor(nums: list[int]) -> int:
    L = max(nums).bit_length()
    root: dict = {}
    # 将每个数字插入为固定长度 L 的二进制字符串
    for x in nums:
        node = root
        for i in range(L - 1, -1, -1):
            bit = (x >> i) & 1
            node = node.setdefault(bit, {})

    ans = 0
    for x in nums:
        node = root
        cur = 0
        for i in range(L - 1, -1, -1):
            bit = (x >> i) & 1
            toggle = 1 - bit                         # 取反位可以让异或结果为 1
            if toggle in node:
                cur = (cur << 1) | 1                # 异或的这一位是 1
                node = node[toggle]
            else:
                cur = (cur << 1) | 0                # 只能选相同的位
                node = node[bit]
        ans = max(ans, cur)
    return ans
```

**核心思路：** 对于每个数字，沿字典树每一步都优先走**相反的位**（这样会让异或结果为 1）。如果相反位不存在，就走相同的位。

### 4. 实现带通配符（"."）的字典树 —— 使用递归

对于 `search("a.c")`，其中 `.` 匹配任意字符，需要在该位置递归遍历所有子节点。

```python
def search_wildcard(self, word: str) -> bool:
    def dfs(node: TrieNode, i: int) -> bool:
        if i == len(word): return node.end
        ch = word[i]
        if ch == '.':
            return any(dfs(child, i + 1) for child in node.children.values())
        if ch not in node.children: return False
        return dfs(node.children[ch], i + 1)
    return dfs(self.root, 0)
```

### 5. 所有前缀都成词的最长单词

先插入所有单词，然后对字典树做 DFS，优先遍历 `end` 为 True 且字典序最小的子节点，同时记录深度。

```python
def longest_word(words: list[str]) -> str:
    root = TrieNode()
    for w in words:
        node = root
        for ch in w:
            if ch not in node.children: node.children[ch] = TrieNode()
            node = node.children[ch]
        node.end = True

    best = ""
    def dfs(node: TrieNode, path: list[str]) -> None:
        nonlocal best
        if path and (len(path) > len(best) or (len(path) == len(best) and ''.join(path) < best)):
            best = ''.join(path)
        for ch in sorted(node.children.keys()):
            child = node.children[ch]
            if child.end:                            # 只有当前前缀本身也是一个单词时才继续
                path.append(ch); dfs(child, path); path.pop()
    dfs(root, [])
    return best
```

### 6. 自动补全 / 搜索建议

先对产品列表排序，然后对每个前缀用二分查找（`bisect_left`）找到范围——这比字典树更简单，足以处理"字典序最小的 3 个"这种需求。

## 识别信号

- "前缀"、"以 X 开头"、"所有以 X 开头的单词" → 字典树。
- "单词搜索 II"、"在棋盘上找单词" → 字典树 + 回溯。
- "两个数的最大异或值"、"最大化 a ^ b" → 二进制字典树。
- "带通配符的单词字典" → 字典树 + 在 `.` 处递归。
- "所有前缀都成词的最长单词" → 字典树 + DFS。
- "设计一个字典"、"实现自动补全" → 字典树（或排序列表 + bisect）。

## 思考框架

1. **字符集是什么？** —— 小写字母（26 个孩子）、小写 + 大写（52 个）、二进制（2 个）、ASCII（128/256 个）。
2. **字符串是短还是长？** —— 短的：每个节点用 `defaultdict` 即可；长或数据量大：用数组做孩子（`[None] * 26`）并配合 `__slots__`。
3. **是否需要标记单词结尾？** —— 用 `end: bool` 标志。
4. **是否需要回溯式的剪枝？** —— 如果搜索空间很大，当节点变成叶子时将其剪掉（模式 2）。
5. **异或问题用二进制字典树？** —— 将数字存为定长的二进制位串。

## Hot 150 例题

- **208. Implement Trie (Prefix Tree)** —— 模式 1。
- **211. Design Add and Search Words Data Structure** —— 模式 4。
- **212. Word Search II** —— 模式 2。
- **14. Longest Common Prefix** —— 更简单的方法：纵向扫描；字典树属于杀鸡用牛刀。
- **648. Replace Words** —— 用词根建字典树，把每个单词替换成最短匹配的词根。
- **676. Implement Magic Dictionary** —— 字典树 + 差一个字符的搜索。
- **421. Maximum XOR of Two Numbers in an Array** —— 模式 3。
- **1804. Implement Trie II (prefix count)** —— 给 TrieNode 扩展 `count` 和 `prefix_count`。
- **1268. Search Suggestions System** —— 排序 + bisect，或字典树 + DFS。

## 常见陷阱

- **`end` 标志与节点上存储的完整单词。** 节点表示一条前缀路径，是否是*完整单词*是另一个独立的标志。不要混为一谈。
- **大量长字符串导致内存爆炸。** 使用 `__slots__`（节省约 50% 内存），字符集小时用数组代替字典存孩子。
- **Word Search II 去重：** 从多条路径收集同一个单词会产生重复——收集后要将 `node.end = False`。
- **在 Word Search II 中剪掉叶子节点**可以加速后续 DFS，去掉死分支。如果题目没要求可以不做。
- **二进制字典树的位顺序：** 总是先处理最高位。先确定好位长度——`max(nums).bit_length()`。
- **通配符递归的最坏复杂度**是 O(26^L)——短单词没问题，但通配符多了会很慢。
- **`setdefault` 返回的是已有的字典**，不是新创建的——链式调用时要小心。
