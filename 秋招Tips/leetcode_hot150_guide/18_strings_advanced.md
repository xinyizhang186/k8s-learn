# 18. 字符串进阶 [深度]

这是你的薄弱环节之一。好消息是：**真正非平凡的字符串算法只有几个** —— KMP、Z 函数、Rabin-Karp、Manacher。把这四个再加上一批常见模式（双指针、回文扩展、文件 03 的滑动窗口）掌握下来，Hot 150 里 95% 的字符串题都能搞定。

---

## 0. 思维框架

面对字符串题时，先问自己**四个问题**：

1. **要找的是模式的精确匹配，还是字符串本身的某种性质？**
   - 在文本 T 中精确匹配模式 P → KMP / Rabin-Karp。
2. **答案是子串、子序列，还是排列？**
   - 子串（连续）→ 回文扩展、滑动窗口、KMP。
   - 子序列（不连续）→ DP（文件 12）。
   - 异位词 / 排列 → Counter + 滑动窗口（文件 03）。
3. **有没有可以利用的结构（回文、重复子串、公共前缀）？**
   - 回文 → 中心扩展，或用 Manacher 做到 O(n)。
   - 重复 → 求周期 = `n - π[n-1]`（KMP 失败函数）。
4. **需要处理超大文本吗？** 那就用 Rabin-Karp（滚动哈希）而不是 KMP，因为滚动哈希可以推广到二维和多模式匹配。

---

## 1. 双指针 / 哈希 —— 你应该已经掌握的基础

这些在文件 01-03 里都讲过，这里只列个提要：

- **验证回文串** —— 反向双指针（文件 02）。
- **无重复字符的最长子串** —— 滑动窗口（文件 03）。
- **最长回文子串（简单 O(n²)）** —— 中心扩展。
- **字母异位词分组** —— 基于 Counter 的键（文件 01）。

### 1.1 中心扩展 —— O(n²) 求回文

```python
def longest_palindrome_expand(s: str) -> str:
    def expand(l: int, r: int) -> tuple[int, int]:
        while l >= 0 and r < len(s) and s[l] == s[r]:
            l -= 1; r += 1
        return l + 1, r - 1                       # 实际的回文边界

    start, end = 0, 0
    for i in range(len(s)):
        # 奇数长度：中心在 i
        l1, r1 = expand(i, i)
        # 偶数长度：中心在 i 和 i+1 之间
        l2, r2 = expand(i, i + 1)
        if r1 - l1 > end - start: start, end = l1, r1
        if r2 - l2 > end - start: start, end = l2, r2
    return s[start:end + 1]
```

当 `n ≤ 1000` 时，这个方法比 Manacher 简单且几乎一样快。只有当 `n > 10^4` 或者题目专门考察回文时才用 Manacher。

---

## 2. KMP —— O(n + m) 模式匹配

KMP 在 O(n + m) 时间内找出模式 `P`（长度 `m`）在文本 `T`（长度 `n`）中的所有出现位置。其诀窍是构建一个**失败函数** `π[i]`，它等于 `P[:i+1]` 的最长真前缀（同时也是后缀）的长度。

### 2.1 失败函数（也叫"最长前缀后缀"或 LPS）

```python
def compute_lps(p: str) -> list[int]:
    m = len(p)
    lps = [0] * m
    k = 0                                          # 当前匹配前缀的长度
    for i in range(1, m):
        while k > 0 and p[i] != p[k]:
            k = lps[k - 1]
        if p[i] == p[k]:
            k += 1
        lps[i] = k
    return lps
```

**解读：** `lps[i]` 是 `p[:i+1]` 的最长真前缀，同时也是它的后缀。"真"的含义是严格短于 `i + 1`。

**为什么它有效：** 当 `p[i]` 与 `t[j]` 匹配失败时，与其把 `p` 整个回到 `p[0]` 重来，我们已经知道 `p[:lps[i-1]]` 与 `t[j-lps[i-1]..j-1]` 是匹配的，所以可以直接从 `p[lps[i-1]]` 继续。

### 2.2 KMP 搜索

```python
def kmp_search(text: str, pattern: str) -> list[int]:
    if not pattern: return list(range(len(text) + 1))
    lps = compute_lps(pattern)
    out: list[int] = []
    k = 0                                          # 模式串当前已匹配的字符数
    for i in range(len(text)):
        while k > 0 and text[i] != pattern[k]:
            k = lps[k - 1]
        if text[i] == pattern[k]:
            k += 1
        if k == len(pattern):
            out.append(i - k + 1)
            k = lps[k - 1]                         # 继续找下一个匹配
    return out
```

### 2.3 重复子串模式 —— `n - lps[n-1]` 就是周期

```python
def repeated_substring_pattern(s: str) -> bool:
    n = len(s)
    lps = compute_lps(s)
    period = n - lps[n - 1]
    return period < n and n % period == 0
```

如果字符串是由长度为 `p` 的子串重复构成，那么 `lps[n-1] = n - p`，且 `n % p == 0`。

### 2.4 通过在前面添加字符得到最短回文

找出 `s` 的最长回文前缀。在 `s + '#' + s[::-1]` 上跑 KMP：

```python
def shortest_palindrome(s: str) -> str:
    if not s: return s
    combined = s + '#' + s[::-1]
    lps = compute_lps(combined)
    longest_pal_prefix_len = lps[-1]
    return s[longest_pal_prefix_len:][::-1] + s
```

诀窍在于：`s + '#' + s[::-1]` 的 LPS 数组末尾，正好等于 `s` 的最长前缀中同时也是 `s[::-1]` 后缀的长度 —— 而这恰好就是 `s` 的最长回文前缀。

---

## 3. Rabin-Karp —— 滚动哈希

Rabin-Karp 能以 O(1) 的更新时间（经过 O(m) 的初始哈希后）计算定长 `m` 的子串哈希。适用于：

- 模式匹配（可能产生误判，需要再比较字符串验证）。
- 多模式匹配（预先算出所有模式的哈希，存到集合里查）。
- 最长重复子串（二分 + 滚动哈希，文件 10 + 本节）。
- 二维模式匹配。

### 3.1 滚动哈希 —— 单多项式哈希

```python
def rabin_karp(text: str, pattern: str) -> list[int]:
    n, m = len(text), len(pattern)
    if m == 0 or m > n: return []
    BASE = 256
    MOD = 10**9 + 7
    highest = pow(BASE, m - 1, MOD)
    p_hash = 0
    t_hash = 0
    for i in range(m):
        p_hash = (p_hash * BASE + ord(pattern[i])) % MOD
        t_hash = (t_hash * BASE + ord(text[i])) % MOD
    out: list[int] = []
    for i in range(n - m + 1):
        if t_hash == p_hash and text[i:i + m] == pattern:
            out.append(i)
        if i < n - m:                             # 向前滚动
            t_hash = (t_hash - ord(text[i]) * highest) * BASE + ord(text[i + m])
            t_hash %= MOD
    return out
```

**滚动公式：** `new_hash = ((old_hash - 离开字符 * BASE^(m-1)) * BASE + 新进字符) % MOD`。

### 3.2 双哈希避免冲突

```python
MOD1, MOD2 = 10**9 + 7, 10**9 + 9
BASE1, BASE2 = 256, 257
# 同时计算两组哈希；只有两组哈希都冲突才会出错 —— 实际几乎不可能
```

面试题里，单哈希 + 字符串验证就已经足够且安全。

### 3.3 最长重复子串 —— 二分 + 滚动哈希

```python
def longest_dup_substring(s: str) -> str:
    n = len(s)
    BASE = 26
    MOD = (1 << 63) - 1                            # 用大素数减少冲突

    def search_len(L: int) -> str:
        if L == 0: return ""
        # 计算 BASE^L mod MOD
        power = pow(BASE, L, MOD)
        # s[:L] 的初始哈希
        cur = 0
        for i in range(L):
            cur = (cur * BASE + ord(s[i]) - ord('a')) % MOD
        seen = {cur}
        for i in range(L, n):
            cur = (cur * BASE - (ord(s[i - L]) - ord('a')) * power
                   + (ord(s[i]) - ord('a'))) % MOD
            if cur in seen:
                # 可选：再做一次字符串比较来验证
                return s[i - L + 1:i + 1]
            seen.add(cur)
        return ""

    lo, hi = 0, n
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = search_len(mid)
        if candidate:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best
```

在子串长度上二分；对每个长度，用滚动哈希扫描一遍看是否有重复。

---

## 4. Z 函数 —— 字符串上的模式分析

Z 数组 `z[i]` = `s` 与 `s[i:]` 的最长公共前缀。算出 Z 数组后可以：

- 在 `P + '$' + T` 上算 Z，然后找 `z[i] == len(P)`，从而找出 P 在 T 中所有出现位置。
- 求字符串的周期（与 `n - max(z[1:])` 相关）。
- 检测重复结构。

### 4.1 Z 函数的构造

```python
def z_function(s: str) -> list[int]:
    n = len(s)
    z = [0] * n
    l = r = 0                                      # 当前最右匹配区间 [l, r)
    for i in range(1, n):
        if i < r:
            z[i] = min(r - i, z[i - l])           # 处于已匹配区间内
        while i + z[i] < n and s[z[i]] == s[i + z[i]]:
            z[i] += 1
        if i + z[i] > r:
            l, r = i, i + z[i]
    return z
```

**核心思路：** 我们维护最右的 `[l, r)`，其中 `s[l:r] == s[:r-l]`。当 `i < r` 时，由区间匹配可以知道 `z[i]` 至少是 `min(r - i, z[i - l])`，然后再用 while 循环尝试继续扩展。

### 4.2 用 Z 函数做模式搜索

```python
def z_search(text: str, pattern: str) -> list[int]:
    if not pattern: return list(range(len(text) + 1))
    combined = pattern + '$' + text
    z = z_function(combined)
    m = len(pattern)
    return [i - m - 1 for i in range(m + 1, len(combined)) if z[i] == m]
```

分隔符 `$`（一个不在两个串中出现的字符）保证 Z 值不会跨越边界。

---

## 5. Manacher 算法 —— O(n) 求最长回文

Manacher 在 O(n) 时间内算出所有回文半径。诀窍是**先把字符串做变换**：在每个字符之间（以及两端）插入哨兵字符，让所有回文在变换后的串里都变成**奇数长度**。

### 5.1 Manacher —— 完整模板

```python
def manacher(s: str) -> str:
    # 变换："abc" -> "^#a#b#c#$"
    # ^ 和 $ 是哨兵，避免边界检查
    t = '^#' + '#'.join(s) + '#$'
    n = len(t)
    p = [0] * n                                    # p[i] = 以 i 为中心的回文半径
    c = r = 0                                      # 当前中心，当前右边界
    for i in range(1, n - 1):
        mirror = 2 * c - i
        if i < r:
            p[i] = min(r - i, p[mirror])           # 可以镜像 —— 复制半径，可能再扩展
        while t[i + p[i] + 1] == t[i - p[i] - 1]: # 尝试向外扩展
            p[i] += 1
        if i + p[i] > r:                           # 扩展右边界
            c, r = i, i + p[i]
    # 找最大半径；还原回文
    max_len, center = max((p[i], i) for i in range(1, n - 1))
    start = (center - max_len) // 2                 # 映射回原始字符串
    return s[start:start + max_len]
```

**为什么变换有效：** `^#a#b#c#$` —— 原串里任意奇偶长度的回文，在变换串中都变成以某个位置为中心的回文，因为每个原字符都被 `#` 包裹。镜像性质让我们可以复用之前算出来的半径。

**为什么用哨兵 `^` 和 `$`：** 它们是不在原串中的字符，因此 while 循环不需要显式判断边界就能在两端停下来。由于 `^` ≠ `$` 且不等于任何原字符，`+1` 和 `-1` 的下标永远不会越界。

### 5.2 用 Manacher 统计所有回文子串的数量

```python
def count_substrings_manacher(s: str) -> int:
    t = '^#' + '#'.join(s) + '#$'
    n = len(t)
    p = [0] * n
    c = r = 0
    for i in range(1, n - 1):
        mirror = 2 * c - i
        if i < r: p[i] = min(r - i, p[mirror])
        while t[i + p[i] + 1] == t[i - p[i] - 1]: p[i] += 1
        if i + p[i] > r: c, r = i, i + p[i]
    # 在变换串中半径为 p[i] 的回文对应 (p[i] + 1) // 2 个原串回文子串
    return sum((p[i] + 1) // 2 for i in range(1, n - 1))
```

---

## 6. 常用模式（与其他文件有重叠）

### 6.1 最小覆盖子串（文件 03 的进阶版）

变长滑动窗口，配合两个计数器 —— 一个记"还需要的字符"，一个记"已满足的字符"。

```python
def min_window(s: str, t: str) -> str:
    from collections import Counter
    need = Counter(t)
    missing = len(t)                              # 还差多少字符
    l = 0
    best = (0, float('inf'))
    for r, ch in enumerate(s):
        if need[ch] > 0: missing -= 1              # 这个字符有用
        need[ch] -= 1
        while missing == 0:                       # 窗口合法 —— 尝试收缩
            if r - l < best[1] - best[0]: best = (l, r + 1)
            if need[s[l]] == 0: missing += 1       # s[l] 即将变得不够
            need[s[l]] += 1
            l += 1
    return s[best[0]:best[1]] if best[1] != float('inf') else ""
```

`need[ch]` 计数器对 `s` 中不在 `t` 里的字符会变成**负数**；当字符离开窗口使它变回 0 时 —— `need[ch] == 0` 表示"恰好够用"，再移走一个窗口就又不合法了。

### 6.2 验证异位词 —— Counter 相等

```python
def is_anagram(s: str, t: str) -> bool:
    return Counter(s) == Counter(t)
```

### 6.3 字母异位词分组 —— 用 Counter 作为哈希键

见文件 01 的模式 2。

### 6.4 最长公共前缀 —— 纵向扫描

```python
def longest_common_prefix(strs: list[str]) -> str:
    if not strs: return ""
    for i in range(len(strs[0])):
        c = strs[0][i]
        for s in strs[1:]:
            if i >= len(s) or s[i] != c:
                return strs[0][:i]
    return strs[0]
```

### 6.5 字符串编解码 —— 长度前缀

```python
def encode(strs: list[str]) -> str:
    return ''.join(f"{len(s)}#{s}" for s in strs)

def decode(s: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(s):
        j = s.index('#', i)
        L = int(s[i:j])
        out.append(s[j + 1:j + 1 + L])
        i = j + 1 + L
    return out
```

### 6.6 字符串转整数（atoi）

状态机：依次处理前导空白、符号、数字、溢出。

```python
def my_atoi(s: str) -> int:
    s = s.lstrip()
    if not s: return 0
    sign = 1
    i = 0
    if s[0] in '+-':
        sign = -1 if s[0] == '-' else 1
        i = 1
    num = 0
    while i < len(s) and s[i].isdigit():
        num = num * 10 + int(s[i])
        i += 1
    num *= sign
    INT_MIN, INT_MAX = -2**31, 2**31 - 1
    if num < INT_MIN: return INT_MIN
    if num > INT_MAX: return INT_MAX
    return num
```

### 6.7 简化路径 —— 栈

见文件 04。

### 6.8 反转字符串中的单词

```python
def reverse_words(s: str) -> str:
    return ' '.join(s.split()[::-1])
```

如果是原地操作（字符数组），先整体反转，再反转每个单词。

### 6.9 字符串乘法 —— 小学竖式

```python
def multiply(num1: str, num2: str) -> str:
    if num1 == '0' or num2 == '0': return '0'
    m, n = len(num1), len(num2)
    res = [0] * (m + n)
    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            mul = (ord(num1[i]) - ord('0')) * (ord(num2[j]) - ord('0'))
            p1, p2 = i + j, i + j + 1
            total = mul + res[p2]
            res[p2] = total % 10
            res[p1] += total // 10
    # 跳过前导零
    k = 0
    while k < len(res) and res[k] == 0: k += 1
    return ''.join(str(d) for d in res[k:])
```

### 6.10 验证回文串 —— 只看字母数字

见文件 02。

### 6.11 回文分割 —— 回溯 + DP

算法见文件 11（回溯）；用区间 DP 预处理 `is_pal[i][j]`（文件 12）。

---

## 7. 识别信号

| 关键词 | 模式 |
|---|---|
| "找出模式 P 在文本 T 中所有出现位置" | KMP / Rabin-Karp / Z 函数 |
| n ≤ 1000 时的"最长回文子串" | 中心扩展（O(n²)） |
| n > 1000 时的"最长回文子串" | Manacher（O(n)） |
| "统计回文子串数量" | Manacher 或区间 DP |
| "通过在前面加字符得到最短回文" | 对 `s + '#' + s[::-1]` 用 KMP 失败函数 |
| "重复子串模式" | KMP LPS —— 周期 = `n - lps[n-1]` |
| "最长重复子串" | 二分 + Rabin-Karp |
| "最小覆盖子串" | 带双计数器的滑动窗口 |
| "异位词"、"的排列"、"同构" | Counter 比较 |
| "字符串编解码" | 长度前缀编码 |
| "有效数字"、"字符串转整数" | 状态机 |
| "字符串乘法"、"字符串加法" | 小学竖式 |
| "简化路径"、"反转单词" | 栈 / 双指针 |

## 8. 思考框架

1. **题目是关于精确模式匹配吗？**
   - 是，单模式：KMP 或 Rabin-Karp。
   - 是，多模式：Aho-Corasick（Hot 150 里很少见）或对每个模式单独算哈希。
2. **是关于回文吗？**
   - 小输入：中心扩展。
   - 大输入：Manacher。
   - 计数或分割：DP / 回溯。
3. **是关于重复子串吗？**
   - 用 KMP 失败函数 —— 周期 = `n - lps[n-1]`。
4. **是关于有约束的子串吗？**（无重复字符、包含 T 的所有字符等）
   - 用带哈希计数器的滑动窗口（文件 03 + 本文件 6.1）。
5. **需要解析 / 状态机吗？**（atoi、有效数字、简化路径）
   - 状态机或基于栈。
6. **需要大数运算吗？**（字符串乘法、二进制加法）
   - 小学竖式逐位运算，处理进位。

## 9. 常见出错点

1. **KMP 失败函数的边界差一：** `lps[i]` 是 `p[:i+1]` 的最长真前缀（也是它的后缀）—— "真"意味着严格短于该子串本身，所以 `lps[i] < i + 1`。
2. **Manacher 没加哨兵：** 如果省略 `^` 和 `$`，就要在 while 循环里显式判断边界。哨兵能省去很多 bug。
3. **Manacher 半径的含义：** `p[i]` 是**变换串**里的半径，不是原串的半径。要还原回去：`start = (center - max_len) // 2`。
4. **Rabin-Karp 取模：** 滚动更新后别忘了 `% MOD`，否则哈希值会无限增长。
5. **Rabin-Karp 的最高位幂：** `BASE^(m-1) mod MOD` 用来减掉离开的字符。如果忘了它，滚动哈希就错了。
6. **Rabin-Karp 冲突：** 单 MOD 在大数据下会有冲突。要么用双哈希，要么在哈希相等时再比较一次字符串。
7. **Z 函数的初始化：** `z[0]` 按惯例是 0（或 `n`，取决于你选的约定）。要和自己使用的算法保持一致。
8. **滑动窗口"missing 计数"的正负号混淆：** 在 min-window-substring 中，`need[ch]` 对 `s` 中多余的字符会变成负数。`need[ch] == 0` 表示"恰好够"，并不代表"完全没有"。
9. **循环里反复字符串拼接：** Python 里 `s += c` 每次都会创建新字符串，整体是 O(n²)。改用 `''.join(list)` 或 `io.StringIO`。
10. **`s.split()` vs `s.split(' ')`：** 前者按任意空白分割并去掉空串；后者只按单个空格分割。
11. **`isalnum()` 和 `lower()`** —— 验证回文串时，用 `c.isalnum()` 跳过非字母数字字符，再用 `c.lower()` 做大小写无关的比较。
12. **罗马数字的方向：** 从左往右遍历；如果一个值比下一个值小，就把它减掉（如 `IV` = 4，`IX` = 9）。从右往左遍历的写法更简洁。
13. **KMP 字符串下标越界：** `while k > 0 and p[i] != p[k]` 之后必须紧跟 `if p[i] == p[k]: k += 1`。这个 if 是在 while 外面。

## 10. 练习清单 —— Hot 150 字符串题

按下面的顺序闭卷做。重点是把**算法选择**锁死，而不是实现细节。

### 基础题（不需要花哨的算法）

| # | 题目 | 模式 |
|---|---------|---------|
| 1 | 125. Valid Palindrome | 6.10 —— 双指针 |
| 2 | 242. Valid Anagram | 6.2 —— Counter |
| 3 | 49. Group Anagrams | 6.3 —— Counter 签名 |
| 4 | 20. Valid Parentheses | 文件 04 |
| 5 | 14. Longest Common Prefix | 6.4 —— 纵向扫描 |
| 6 | 58. Length of Last Word | split / 从右往左扫描 |
| 7 | 151. Reverse Words in a String | 6.8 |
| 8 | 71. Simplify Path | 文件 04 —— 栈 |
| 9 | 271. Encode and Decode Strings | 6.5 —— 长度前缀 |

### 字符串滑动窗口（与文件 03 重叠）

| # | 题目 | 模式 |
|---|---------|---------|
| 10 | 3. Longest Substring Without Repeating Characters | 文件 03 |
| 11 | 438. Find All Anagrams in a String | 文件 03 —— 定长窗口 + Counter |
| 12 | 76. Minimum Window Substring | 6.1 |
| 13 | 424. Longest Repeating Character Replacement | 文件 03 |
| 14 | 567. Permutation in String | 定长窗口 + Counter |

### 字符串双指针

| # | 题目 | 模式 |
|---|---------|---------|
| 15 | 344. Reverse String | 原地双指针 |
| 16 | 392. Is Subsequence | 双指针 |
| 17 | 680. Valid Palindrome II | 双指针 + 尝试删一边 |

### 回文家族（比较考算法的部分）

| # | 题目 | 模式 |
|---|---------|---------|
| 18 | 5. Longest Palindromic Substring | 1.1（扩展）或 5.1（Manacher） |
| 19 | 647. Palindromic Substrings | 5.2（Manacher）或区间 DP |
| 20 | 131. Palindrome Partitioning | 文件 11 —— 回溯 |
| 21 | 132. Palindrome Partitioning II | 区间 DP（文件 12） |
| 22 | 214. Shortest Palindrome | 2.4 —— 对 `s + '#' + s[::-1]` 用 KMP |
| 23 | 680. Valid Palindrome II | 双指针 + 最多删一个 |

### 模式匹配

| # | 题目 | 模式 |
|---|---------|---------|
| 24 | 28. Find the Index of the First Occurrence in a String | KMP（或内置 `find`） |
| 25 | 459. Repeated Substring Pattern | 2.3 —— KMP 失败函数 |
| 26 | 1044. Longest Duplicate Substring | 3.3 —— 二分 + Rabin-Karp |
| 27 | 686. Repeated String Match | Rabin-Karp 或直接枚举长度增长 |

### 字符串数学 / 解析

| # | 题目 | 模式 |
|---|---------|---------|
| 28 | 8. String to Integer (atoi) | 6.6 —— 状态机 |
| 29 | 43. Multiply Strings | 6.9 —— 小学竖式 |
| 30 | 67. Add Binary | 逐位 + 进位 |
| 31 | 415. Add Strings | 与 6.9 类似 |
| 32 | 13. Roman to Integer | 文件 16 |
| 33 | 12. Integer to Roman | 文件 16 |

### 难题 / 特殊题

| # | 题目 | 模式 |
|---|---------|---------|
| 34 | 10. Regular Expression Matching | DP（文件 12 —— 8.1 节） |
| 35 | 44. Wildcard Matching | DP（文件 12 —— 8.2 节） |
| 36 | 91. Decode Ways | DP（文件 12 —— 1.4 节） |
| 37 | 139. Word Break | DP（文件 12 —— 1.5 节） |
| 38 | 140. Word Break II | DP + 回溯 |
| 39 | 212. Word Search II | 字典树（文件 14） |
| 40 | 127. Word Ladder | 双向 BFS（文件 09） |
| 41 | 126. Word Ladder II | BFS + 路径重建 |

**分阶段锁定模式的计划：**
- **第 1-2 天：** 基础题（1-9）—— 这些比较简单，过一遍就行。
- **第 3 天：** 字符串滑动窗口（10-14）—— 变长窗口 + 双计数器的套路回报率很高。
- **第 4 天：** 回文家族（18-23）—— 中心扩展和 Manacher 都要练会，知道什么时候该用哪个。
- **第 5 天：** 模式匹配（24-27）—— 默写 KMP；Rabin-Karp 写一遍即可。
- **第 6 天：** 解析 / 数学（28-33）。
- **第 7 天：** 难题 DP / 正则（34-41）—— 这些题代码量大，配合 DP 文件一起复习。

完成后，把第 5、22、24、26 题再闭卷做一遍 —— 这几道是真正考察你 KMP、Manacher 和 Rabin-Karp 是否理解到位的算法密集型字符串题。

---

## 总结性思维框架

每遇到"字符串"题，先按下面的骨架写一遍：

```python
def solve(s: str, ...) -> Answer:
    # 1. 答案到底是子串、子序列还是排列？
    #    - 子串（连续）：KMP / Rabin-Karp / Manacher / 滑动窗口
    #    - 子序列：DP（文件 12）
    #    - 排列：Counter + 滑动窗口（文件 03 + 本文件 6.1）
    # 2. 如果是精确模式匹配：
    #    - n <= 10^6 单模式：KMP 或内置 str.find
    #    - 大文本多模式：Rabin-Karp
    # 3. 如果是回文：
    #    - n <= 1000：中心扩展（O(n^2)）
    #    - n > 1000 或要计数：Manacher（O(n)）
    # 4. 如果是重复子串：KMP 失败函数给出周期。
    # 5. 如果是解析 / 转换：状态机或栈。
```

只要能根据题意填出该用哪个算法，实现就是机械的。难点在于**识别哪个算法适用** —— 把第 7 节的表格练到自动反应。

### 字符串算法速查表

| 需求 | 算法 | 时间 |
|---|---|---|
| 单模式精确匹配 | KMP | O(n + m) |
| 单模式精确匹配（更简单） | Rabin-Karp | O(n + m) 平均 |
| 最长回文子串（n 较小） | 中心扩展 | O(n²) |
| 最长回文子串（n 较大） | Manacher | O(n) |
| 最长重复子串 | 二分 + Rabin-Karp | O(n log n) 平均 |
| 最长公共前缀 | 纵向扫描 | O(S) 总字符数 |
| 包含指定字符集的子串 | 滑动窗口 + Counter | O(n) |
| 周期 / 重复子串 | KMP 失败函数 | O(n) |
| 两个串的公共子串 | DP（LCS 变种） | O(nm) |
| 编辑距离 | DP | O(nm) |
| 带通配符的所有模式匹配 | DP（正则匹配） | O(nm) |
