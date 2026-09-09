# 02 · 字符串实战与避坑

> 已刷过一遍 Hot 150,但字符串"非常薄弱"。本文直接进入:识别信号 → 三大思维轴 → 子模式全家桶(含 KMP / Manacher / Rabin-Karp / Trie / 括号 / 计算器)→ 避坑 → 速记。
> 心法:**字符串问题 = 指针移动型(双指针/滑窗) ∪ 自动机型(KMP/AC/Trie) ∪ DP型(回文/编辑)。先判断属于哪一类,再选算法。**

---

## 一、识别信号

| 题目特征 | 推荐技法 |
|---|---|
| "最长/最短子串"且带"满足某条件" | **滑动窗口** |
| "无重复字符""恰好 k 种" | 滑动窗口 + 计数 |
| "模式串匹配""是否包含" | **KMP** / Rabin-Karp |
| "最长重复子串""重复 DNA 序列" | **Rabin-Karp 滚动哈希** / 二分+哈希 |
| "最长回文""回文子串数" | **Manacher** / 区间 DP |
| "前缀匹配""单词查找""单词搜索" | **Trie** |
| "正则/通配符匹配""编辑距离""子序列" | **字符串 DP**(见 01) |
| "生成所有括号""合法括号" | **回溯 / 栈** |
| "表达式求值""基本计算器" | **栈 / 双栈** |
| "去除重复字母""移掉 K 位数字" | **单调栈(字符串版)** |
| "字符串转整数""简化路径" | 模拟 + 边界 |

---

## 二、心智模型 — 三大思维轴

| 思维轴 | 代表算法 | 适用 |
|---|---|---|
| **指针移动型** | 双指针、滑动窗口 | 子串最值、覆盖、去重 |
| **自动机型** | KMP、AC自动机、Trie | 匹配、前缀、多模式 |
| **DP 型** | 回文 DP、编辑距离 | 子序列、回文、匹配 |

判断顺序:**先看是不是"子串最值"→ 滑窗;再看是不是"匹配/前缀"→ KMP/Trie;最后考虑 DP**。字符串 DP 在 `01-dynamic-programming.md` 已有详解,本文只点题号。

---

## 三、子模式全家桶

### 3.1 双指针

**识别**:反转、回文判定、元音交换 — 两个指针从两端/同端走。

**模板 — 反转字符串中的元音字母(345)**:
```python
def reverseVowels(s):
    vowels = set('aeiouAEIOU')
    s = list(s)
    l, r = 0, len(s) - 1
    while l < r:
        while l < r and s[l] not in vowels: l += 1
        while l < r and s[r] not in vowels: r -= 1
        s[l], s[r] = s[r], s[l]
        l, r = l + 1, r - 1
    return ''.join(s)
```
**Hot 150 真题**:344 反转字符串、125 验证回文串、345 元音交换、392 判断子序列(双指针同向)。

### 3.2 滑动窗口(CRITICAL)

**识别**:子串 + "最长/最短" + 约束(无重复/k 种字符/覆盖目标)。

**通用模板(可变长,求最长)**:
```python
from collections import Counter, defaultdict
def sliding_window_longest(s, target):
    """求满足条件的最长子串。框架:右扩左缩"""
    need = Counter(target)
    cnt = defaultdict(int)
    valid = 0                       # 已满足条件的字符数
    left = 0
    best = 0
    for right, ch in enumerate(s):
        cnt[ch] += 1                # 右端入窗
        if ch in need and cnt[ch] == need[ch]:
            valid += 1
        while valid == len(need):  # 满足 → 收缩左端(求最长要边缩边更新)
            best = max(best, right - left + 1)
            cnt[s[left]] -= 1
            if s[left] in need and cnt[s[left]] == need[s[left]] - 1:
                valid -= 1
            left += 1
    return best
```
⚠️ **求最短** vs **求最长**:更新答案的位置不同。
- 求最长:在 `while 满足` **内部**收缩时更新(收缩前窗口满足)。
- 求最短:在 `while 满足` **退出后**更新(刚不满足时窗口曾最短)。

**Hot 150 真题**:
- 3 无重复字符的最长子串:`need` 退化为"所有字符 ≤ 1"
- 76 最小覆盖子串:求最短 + 覆盖 target
- 438 找到所有字母异位词:**定长窗口**,每滑一格比较 Counter
- 209 长度最小的子数组:求最短 + 和 ≥ target(也可前缀和 + 二分)

### 3.3 KMP(CRITICAL — 最薄弱)

**识别**:模式串匹配、判断"是否由子串重复构成"。

**核心两个数组**(命名易混,本文统一用 `lps` = Longest Proper Prefix which is also Suffix):
- `lps[i]` = `pattern[0..i]` 的"最长相等前后缀"长度。
- 失配时,模式串指针 `j` 跳到 `lps[j-1]`,**不回退主串指针 `i`** → 这是 KMP `O(n+m)` 的关键。

**模板 — 构建 lps + 匹配**:
```python
def build_lps(p):
    """构建 lps 数组。O(m)"""
    m = len(p)
    lps = [0] * m
    length = 0                  # 当前最长相等前后缀长度
    i = 1
    while i < m:
        if p[i] == p[length]:
            length += 1
            lps[i] = length
            i += 1
        else:
            if length != 0:
                length = lps[length - 1]    # 关键:失配回跳,不增 i
            else:
                lps[i] = 0
                i += 1
    return lps

def kmp_search(text, pattern):
    """返回首次匹配位置,无则 -1。O(n+m)"""
    if not pattern: return 0
    lps = build_lps(pattern)
    i = j = 0                    # i=主串, j=模式串
    while i < len(text):
        if text[i] == pattern[j]:
            i += 1; j += 1
            if j == len(pattern):
                return i - j     # 找到
        else:
            if j != 0:
                j = lps[j - 1]    # 模式串回跳,主串不动
            else:
                i += 1
    return -1
```

**为什么 `j = lps[j-1]` 而不是 `j = 0`?**
因为 `pattern[0..j-1]` 已经匹配上了,而 `lps[j-1]` 是这段的"最长相等前后缀"——意味着前 `lps[j-1]` 个字符和后 `lps[j-1]` 个字符相同,所以下次比较可以从 `pattern[lps[j-1]]` 开始,前缀那部分不用再比。这就是 KMP 不回退主串的本质。

**Hot 150 真题**:
- 28 strStr:`kmp_search` 直接用
- 459 重复的子字符串:`s` 长度为 `n - lps[n-1]` 的子串是否重复构成 `s`(利用 `lps` 性质)
- 214 最短回文串:在 `s + '#' + reverse(s)` 上跑 KMP 的 lps,末尾 lps 即"最长回文前缀"长度

### 3.4 Rabin-Karp 滚动哈希

**识别**:找重复子串、DNA 序列、`n ≤ 1e5` 的字符串匹配。

**模板 — 重复的 DNA 序列(187)**:
```python
def findRepeatedDnaSequences(s):
    """找所有长度 10 且出现 ≥ 2 次的子串"""
    seen = set()
    ans = set()
    base, mod = 4, (1 << 31) - 1      # DNA 用 4 进制;大质数防碰撞
    mapping = {'A':0, 'C':1, 'G':2, 'T':3}
    if len(s) < 10: return []
    h = 0
    for i in range(10):               # 第一个窗口哈希
        h = (h * base + mapping[s[i]]) % mod
    seen.add(h)
    power = pow(base, 9, mod)         # base^(L-1),用于滚动时消最高位
    for i in range(10, len(s)):
        # 滚动:去掉最高位,加上最低位
        h = (h - mapping[s[i-10]] * power) % mod
        h = (h * base + mapping[s[i]]) % mod
        if h in seen:
            ans.add(s[i-9:i+1])       # 哈希碰撞时用字符串二次验证
        else:
            seen.add(h)
    return list(ans)
```
**为什么 `O(n)`?** 每次滑动窗口,哈希 `O(1)` 更新(去高位 + 加低位),不用重新算整个子串。

⚠️ **避坑**:
- 哈希可能碰撞 → 用大质数双模(`mod1=1e9+7, mod2=1e9+9`)或存字符串二次验证。
- `h - ... * power` 可能负 → `(h - ... ) % mod` 在 Python 自动取正(Python `%` 结果非负),C++ 要 `+mod`。

**Hot 150 真题**:187 重复 DNA 序列、1044 最长重复子串(二分长度 + 滚动哈希验证)、718 最长重复子数组(也可 DP)。

### 3.5 Manacher(CRITICAL — 最薄弱)

**识别**:回文子串 + `O(n)` 要求 → Manacher(否则用区间 DP `O(n²)`)。

**核心思想**:利用回文的对称性,避免对每个中心都从 0 开始扩展。

**三步**:
1. **插值**:把 `"abba"` → `"#a#b#b#a#"`,统一奇偶中心(都变奇数长度)。
2. **`p[i]`**:以 `i` 为中心的最长回文半径(含中心),则原串回文长度 = `p[i]//2 * 2`... 实际:`p[i]` 是变换串的半径,原串对应回文长度 = `p[i] - 1`。
3. **镜像优化**:维护当前最右回文边界 `R` 和中心 `C`,若 `i < R`,则 `p[i]` 初值取 `min(p[2*C - i], R - i)`,再尝试扩展。

**模板 — 最长回文子串(5)**:
```python
def longestPalindrome(s):
    # 1. 插值
    t = '#' + '#'.join(s) + '#'
    n = len(t)
    p = [0] * n                     # p[i] = 以 i 为中心的最长回文半径(含中心)
    C = R = 0                       # 当前最右回文的中心与右边界
    max_len = 0
    center = 0
    for i in range(n):
        # 镜像:若 i 在最右回文内,利用对称性取初值
        mirror = 2 * C - i
        if i < R:
            p[i] = min(R - i, p[mirror])
        # 尝试扩展
        while (i - p[i] - 1 >= 0 and i + p[i] + 1 < n
               and t[i - p[i] - 1] == t[i + p[i] + 1]):
            p[i] += 1
        # 更新最右回文
        if i + p[i] > R:
            C, R = i, i + p[i]
        # 更新答案(原串回文长度 = p[i])
        if p[i] > max_len:
            max_len = p[i]
            center = i
    start = (center - max_len) // 2     # 映射回原串下标
    return s[start:start + max_len]
```
复杂度 `O(n)`。**关键**:`p[i]` 初值用镜像省掉重复扩展,但 while 仍可能扩展——总扩展次数被 `R` 的推进均摊为 `O(n)`。

⚠️ **避坑**:`p[i]` 含中心,原串回文长度 = `p[i]`(因为插值后 `#` 比字符多一个);下标映射 `(center - p[i]) // 2` 容易写错,建议背熟这一行。

**Hot 150 真题**:5 最长回文子串、647 回文子串数(累加 `(p[i]+1)//2`)、131 分割回文串(回溯 + Manacher 预处理)。

### 3.6 Z 函数(简述)

`z[i]` = `s[i..]` 与 `s` 的最长公共前缀长度。用途类似 KMP 但有时更直观(如拼接 `pattern + '#' + text` 后 `z` 值 = 匹配长度)。
```python
def z_function(s):
    n = len(s)
    z = [0] * n
    l = r = 0
    for i in range(1, n):
        if i < r:
            z[i] = min(r - i, z[i - l])
        while i + z[i] < n and s[z[i]] == s[i + z[i]]:
            z[i] += 1
        if i + z[i] > r:
            l, r = i, i + z[i]
    return z
```

### 3.7 Trie

**识别**:前缀匹配、单词查找、单词搜索 II、自动补全。

**模板**(完整版见 `00-thinking-framework-and-templates.md` 4.14,这里给搜索带通配符的扩展):
```python
class WordDictionary:
    """211 题:支持 '.' 通配符"""
    def __init__(self):
        self.root = TrieNode()

    def addWord(self, word):
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, TrieNode())
        node.end = True

    def search(self, word):
        def dfs(node, i):
            if i == len(word):
                return node.end
            ch = word[i]
            if ch == '.':
                return any(dfs(child, i + 1) for child in node.children.values())
            if ch not in node.children:
                return False
            return dfs(node.children[ch], i + 1)
        return dfs(self.root, 0)
```
⚠️ `.` 通配符要 DFS 所有子节点 → 注意剪枝(Trie 结构本身就剪了不存在的前缀)。

**Hot 150 真题**:208 实现 Trie、211 添加与搜索单词(通配)、212 单词搜索 II(Trie + 网格回溯)、648 单词替换(找最短前缀)。

### 3.8 字符串 DP(详见 01-dynamic-programming.md)

只列题号与状态定义,代码见 01:
- 5 最长回文子串:`f[i][j]` 表示 `s[i..j]` 是否回文
- 72 编辑距离:`f[i][j]` = `s1[:i]` 与 `s2[:j]` 的最小编辑距离
- 10 正则表达式匹配:`f[i][j]` = `s[:i]` 是否匹配 `p[:j]`(`*` 处理是难点)
- 44 通配符匹配:类似 10,`*` 匹配任意序列
- 115 不同的子序列:`f[i][j]` = `s[:i]` 中 `t[:j]` 出现次数
- 97 交错字符串:`f[i][j]` = `s1[:i]+s2[:j]` 能否交错成 `s3[:i+j]`

### 3.9 括号问题

**识别**:合法括号、生成括号、最长有效括号。

| 题 | 解法 |
|---|---|
| 20 有效的括号 | 栈匹配 |
| 22 括号生成 | 回溯(左<右可加左,右<左可加右) |
| 32 最长有效括号 | **DP** `f[i]` = 以 i 结尾的最长有效长度;或栈存下标 |
| 301 删除无效括号 | BFS 去括号搜索(最少删除数) |
| 856 括号的分数 | 栈:遇到 `(` 压 0,`)` 弹出累加 |

**模板 — 32 最长有效括号(DP)**:
```python
def longestValidParentheses(s):
    f = [0] * len(s)     # f[i] = 以 s[i] 结尾的最长有效括号长度
    ans = 0
    for i in range(1, len(s)):
        if s[i] == ')':
            if s[i-1] == '(':           # ...()
                f[i] = (f[i-2] if i >= 2 else 0) + 2
            elif i - f[i-1] - 1 >= 0 and s[i - f[i-1] - 1] == '(':  # ...))
                f[i] = f[i-1] + 2 + (f[i - f[i-1] - 2] if i - f[i-1] - 2 >= 0 else 0)
            ans = max(ans, f[i])
    return ans
```

### 3.10 栈式处理(计算器 / 单调栈字符串版)

**识别**:表达式求值、移掉 K 位数字、去除重复字母。

**模板 — 基本计算器 II(227)**:
```python
def calculate(s):
    """支持 + - * / 和空格。用栈处理乘除优先"""
    stack = []
    num = 0
    op = '+'
    for i, ch in enumerate(s):
        if ch.isdigit():
            num = num * 10 + int(ch)
        if ch in '+-*/' or i == len(s) - 1:
            if op == '+': stack.append(num)
            elif op == '-': stack.append(-num)
            elif op == '*': stack.append(stack.pop() * num)
            elif op == '/': stack.append(int(stack.pop() / num))   # Python 向下取整要对负数处理
            op, num = ch, 0
    return sum(stack)
```
⚠️ Python `//` 对负数向下取整(如 `-3//2 = -2`),而题目要"向 0 取整" → 用 `int(a / b)`。

**模板 — 移掉 K 位数字(402)**:
```python
def removeKdigits(num, k):
    """单调栈:保留升序,栈顶比当前大就弹掉"""
    stack = []
    for ch in num:
        while k > 0 and stack and stack[-1] > ch:
            stack.pop()
            k -= 1
        stack.append(ch)
    # k 没用完,删尾部
    stack = stack[:-k] if k else stack
    res = ''.join(stack).lstrip('0')
    return res if res else '0'
```

**Hot 150 真题**:224/227 计算器、394 字符串解码、402 移掉 K 位数字、316 去除重复字母(单调栈 + 出现计数)、739 用栈看下一个更大。

### 3.11 字符串处理杂项

- 8 字符串转整数 atoi:状态机(空格 → 符号 → 数字 → 溢出处理)
- 71 简化路径:按 `/` split,栈处理 `..` 和 `.`
- 468 验证 IP 地址:分 v4/v6 逐段校验

---

## 四、高频避坑清单

1. **滑窗收缩条件错位**:求最长在收缩**前**更新,求最短在收缩**后**更新。
2. **KMP 命名混淆**:`next` / `lps` / `PMT` 是同一个数组的不同叫法,本文统一 `lps`。
3. **KMP 失配回跳**:`j = lps[j-1]`(不是 `j=0`),且**不增主串 `i`**。
4. **滚动哈希负数取模**:Python `%` 自动非负,C++ 要 `+mod`;双模防碰撞。
5. **Manacher 奇偶中心**:必须用 `#` 插值统一,否则要分奇偶两套代码。
6. **Manacher 下标映射**:`p[i]` 是变换串半径,原串回文长度 = `p[i]`,起点 = `(center - p[i]) // 2`。
7. **Trie 删除节点**:要递归删且检查子节点是否为空,漏标记 `end=False` 会误判。
8. **回溯忘记撤销选择**:`path.pop()` 必须和 `path.append()` 成对。
9. **字符串 DP 下标含义**:`f[i][j]` 用"前 i 和前 j"(更易写边界)还是"`s[i..j]`"(区间 DP),全篇统一。
10. **计算器优先级**:`* /` 立即算入栈,`+ -` 入栈延迟到 `sum`,这样最后 `sum(stack)` 自动正确。
11. **Python 字符串不可变**:看似"修改"实则新建,大量拼接用 `''.join(list)` 而非 `+=`。
12. **通配符 DFS 不剪枝**:Trie 通配符 `.` 要遍历所有子节点,但 Trie 结构已天然剪去不存在前缀。

---

## 五、速记口诀 + 对比表

**口诀**:"子串想滑窗(右扩左缩),匹配想 KMP(失配回跳 lps),回文 Manacher(插值镜像),前缀 Trie 树,括号用栈/回溯,计算器乘除即算。"

| 维度 | 双指针 | 滑动窗口 | KMP |
|---|---|---|---|
| 复杂度 | O(n) | O(n) | O(n+m) |
| 适用 | 回文/反转/子序列 | 子串最值+约束 | 模式匹配 |
| 关键 | 两端或同向 | 右扩左缩 | lps 失配回跳 |

| 维度 | 滚动哈希 | KMP | Manacher |
|---|---|---|---|
| 适用 | 重复子串/匹配 | 单模式匹配 | 回文子串 |
| 复杂度 | O(n) 期望 | O(n+m) 确定性 | O(n) 确定性 |
| 风险 | 哈希碰撞 | 无 | 边界映射易错 |

| 维度 | 子串 | 子序列 |
|---|---|---|
| 定义 | 连续 | 可不连续 |
| 求最长 | 滑窗/后缀数组 | LIS / LCS DP |
| 求个数 | 滑窗计数 | DP 计数 |

---

## 六、自测清单

- [ ] 默写滑动窗口模板,**说清"求最长 vs 求最短"更新答案位置的差异**
- [ ] 默写 KMP 的 `build_lps` + `kmp_search`,**解释 `j = lps[j-1]` 为什么不增 `i`**
- [ ] 默写滚动哈希,**说清 `power = base^(L-1)` 的作用和碰撞处理**
- [ ] 默写 Manacher,**说清 `#` 插值为什么能统一奇偶中心、`p[i]` 与原串长度的关系**
- [ ] 默写 Trie + 通配符 DFS
- [ ] 默写基本计算器 II(`* /` 即算入栈,`+ -` 入栈符号)
- [ ] 默写移掉 K 位数字(单调栈 + 删尾部 + 去前导零)

> 任何一项卡壳 → 回到对应小节,**手抄一遍模板再默写**。字符串的薄弱主要在 KMP/Manacher 的边界细节,这两块务必手敲验证。
