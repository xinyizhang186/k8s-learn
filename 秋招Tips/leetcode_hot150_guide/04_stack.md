# 04. 栈

## 核心概念

栈提供 **LIFO**（后进先出）的访问方式。在 Hot 150 中反复出现的模式有：

1. **括号 / 表达式求值** —— 入栈左半部分，遇到右半部分时弹栈匹配；数字入栈，运算符作用于栈顶数字。
2. **单调栈** —— 用于"下一个更大元素"、"柱状图中最大的矩形"、"接雨水"。
3. **最值栈** —— 借助一个辅助栈记录当前的最小/最大值。
4. **后缀 / 中缀转换** —— 经典内容但 Hot 150 中很少考。
5. **迭代器模拟** —— 用于树、嵌套列表等结构。

## 模式与模板

### 1. 有效的括号

```python
def is_valid(s: str) -> bool:
    pairs = {')': '(', ']': '[', '}': '{'}
    stack: list[str] = []
    for c in s:
        if c in pairs:
            if not stack or stack.pop() != pairs[c]: return False
        else:
            stack.append(c)
    return not stack
```

### 2. 最值栈 —— 辅助栈

```python
class MinStack:
    def __init__(self):
        self.s: list[int] = []
        self.mn: list[int] = []                  # 平行的最小值栈

    def push(self, x: int) -> None:
        self.s.append(x)
        self.mn.append(x if not self.mn else min(x, self.mn[-1]))

    def pop(self) -> None:
        self.s.pop(); self.mn.pop()

    def top(self) -> int: return self.s[-1]
    def get_min(self) -> int: return self.mn[-1]
```

### 3. 单调栈 —— 下一个更大元素

```python
def next_greater_element(nums: list[int]) -> list[int]:
    n = len(nums)
    res = [-1] * n
    stack: list[int] = []                         # 存下标，对应值严格递减
    for i in range(n):
        while stack and nums[stack[-1]] < nums[i]:
            res[stack.pop()] = nums[i]
        stack.append(i)
    return res
```

**不变式：** 栈中保存的下标对应的值严格递减。当 `nums[i]` 到来时，它就是栈中所有较小元素的 *下一个更大元素*。

### 4. 柱状图中最大的矩形

```python
def largest_rectangle_area(heights: list[int]) -> int:
    stack: list[int] = []                         # 存递增高度的下标
    best = 0
    heights = heights + [0]                       # 哨兵，用于最后清空栈
    for i, h in enumerate(heights):
        while stack and heights[stack[-1]] > h:
            top = stack.pop()
            width = i if not stack else i - stack[-1] - 1
            best = max(best, heights[top] * width)
        stack.append(i)
    return best
```

哨兵 `[0]` 避免了最后再写一段"清空剩余栈"的代码。

### 5. 每日温度（带答案间距的单调栈）

```python
def daily_temperatures(temps: list[int]) -> list[int]:
    n = len(temps)
    res = [0] * n
    stack: list[int] = []
    for i in range(n):
        while stack and temps[stack[-1]] < temps[i]:
            j = stack.pop()
            res[j] = i - j
        stack.append(i)
    return res
```

### 6. 表达式求值 —— 双栈（数字栈与运算符栈）

```python
def calculate(s: str) -> int:
    def apply(op: str, b: int, a: int) -> int:
        return a + b if op == '+' else a - b
    prec = {'+': 1, '-': 1}
    nums: list[int] = []
    ops: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit(): j += 1
            nums.append(int(s[i:j]))
            i = j; continue
        if c in prec:
            while ops and ops[-1] in prec and prec[ops[-1]] >= prec[c]:
                nums.append(apply(ops.pop(), nums.pop(), nums.pop()))
            ops.append(c)
        i += 1
    while ops:
        nums.append(apply(ops.pop(), nums.pop(), nums.pop()))
    return nums[0]
```

如果需要处理括号，把 `(` 压入运算符栈，遇到 `)` 时则弹出直到遇到 `(` 为止。

## 识别信号

- "valid parentheses"、"balanced brackets"（有效括号、括号匹配）→ 用栈配合右括号映射。
- "next greater"、"next smaller"、"daily temperatures"（下一个更大/更小、每日温度）→ 单调栈。
- "largest rectangle in histogram"、"maximal rectangle"（柱状图最大矩形、最大矩形）→ 带哨兵的单调栈。
- "min/max stack"、"get minimum in O(1)"（最小/最大栈、O(1) 取最小值）→ 辅助最小/最大栈。
- "basic calculator"、"evaluate expression"（基本计算器、表达式求值）→ 双栈（或递归下降）。
- "asteroid collision"、"remove adjacent duplicates"（行星碰撞、删除相邻重复项）→ 栈模拟。
- "decode string `3[a2[c]]`"（解码字符串）→ 栈中保存 (字符串, 次数) 对。

## 思维框架

1. **问题是"匹配左括号与右括号"还是"按优先级求值"？** → 简单栈，或双栈计算器。
2. **是否在问"下一个更大/更小"或"柱状图面积"？** → 单调栈。栈中存下标，值保持单调。
3. **是否要求"在 push/pop 的同时维护最小值"？** → 辅助栈。
4. **是否要求"解码带重复次数的嵌套括号"？** → 栈中保存 (前缀字符串, 重复次数)。
5. **边界情况？** 空输入、单个元素、严格递增（栈永不弹出）、严格递减（每一步都要弹出）。

## Hot 150 例题

- **20. Valid Parentheses** —— 模式 1。
- **155. Min Stack** —— 模式 2。
- **150. Evaluate Reverse Polish Notation** —— 单栈：数字入栈，遇到运算符时弹出两个数运算。
- **227. Basic Calculator II** —— 模式 6。
- **739. Daily Temperatures** —— 模式 5。
- **84. Largest Rectangle in Histogram** —— 模式 4。
- **85. Maximal Rectangle** —— 对逐行累计的高度直方图套用 84 的方法。
- **71. Simplify Path** —— 按 `/` 切分，目录名入栈，遇到 `..` 弹栈。
- **394. Decode String** —— 栈中保存 (前缀字符串, 重复次数)。

## 常见陷阱

- **单调栈的循环顺序：** 从左到右处理元素；每来一个新元素，先在不变式被破坏时不断弹出，再压入新元素。不要先压入再弹出。
- **柱状图中的宽度计算：** 弹出 `top` 后，矩形的左边界是 `stack[-1] + 1`（若栈为空则为 `0`），右边界是 `i - 1`。宽度 = `i - stack[-1] - 1`（若栈非空），否则为 `i`。
- **哨兵技巧：** 在末尾追加一个比任何真实元素都小的哨兵（例如正高度情形下的 `0`），从而无需重复写清理循环就能在结束时清空栈。
- **栈中存的是下标而非值**：当需要计算距离或宽度时（例如每日温度、柱状图）。
- **严格 vs 非严格单调性：** 需要"下一个更大"时使用 `<` 或 `>`（严格）；当相等元素也需要被弹出时使用 `<=` 或 `>=`（非严格）。根据"等于算不算下一个更大"来选择。
- **计算器中的运算符优先级：** 在压入低优先级运算符之前，先把栈中更高优先级的运算符应用完。对于左结合运算符（`+ - * /`），弹出条件是 `prec[栈顶运算符] >= prec[当前运算符]`。