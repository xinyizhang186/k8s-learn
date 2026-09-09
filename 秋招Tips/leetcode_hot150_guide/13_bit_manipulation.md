# 13. 位运算

## 核心概念

Python 原生支持任意精度的整数（无溢出）。常用位操作：

- `x & y`, `x | y`, `x ^ y` —— 与、或、异或。
- `~x` —— 按位取反（Python 中 `~x == -x - 1`，小心符号位）。
- `x << k`, `x >> k` —— 移位。
- `x.bit_count()`（Python 3.10+）—— 1 的个数（popcount）。
- `x.bit_length()` —— 表示 `x` 所需的位数（即 `ceil(log2(x+1))`）。
- `bin(x)` —— 带 `'0b'` 前缀的字符串。
- `int(s, 2)` —— 解析二进制字符串。

## 模式与模板

### 1. 异或技巧

**所有元素做异或**可以在其他元素都出现两次时找出唯一的那个：

```python
def single_number(nums: list[int]) -> int:
    ans = 0
    for x in nums: ans ^= x
    return ans
```

**两个唯一元素（其他都出现两次）：**

```python
def single_number_iii(nums: list[int]) -> list[int]:
    xor = 0
    for x in nums: xor ^= x
    # xor == a ^ b。任选一个为 1 的位（取最低位）。
    diff = xor & (-xor)
    a = b = 0
    for x in nums:
        if x & diff: a ^= x
        else: b ^= x
    return [a, b]
```

**唯一元素（其他都出现三次）：** 统计每个位置 1 的个数，然后对 3 取模。

### 2. 提取最低位的 1

```python
lowest_bit = x & (-x)        # 例如：12 (1100) -> 4 (0100)
```

`-x` 在二进制补码下相当于把 `x` 全部位取反再加 1，所以 `x & -x` 只保留最低位的那个 1。

### 3. 清掉最低位的 1

```python
x = x & (x - 1)              # 1100 -> 1000（清掉第 2 位）
```

常用来遍历所有为 1 的位：

```python
def bits_set(x: int) -> list[int]:
    out = []
    while x:
        b = x & -x                            # 最低位
        out.append(b.bit_length() - 1)        # 位位置
        x &= x - 1                            # 清掉它
    return out
```

### 4. 不使用 + 或 - 实现加法

```python
def get_sum(a: int, b: int) -> int:
    mask = 0xFFFFFFFF
    while b:
        carry = (a & b) << 1
        a = (a ^ b) & mask
        b = carry & mask
    # 处理负数：从 32 位补码转换回来
    return a if a <= 0x7FFFFFFF else ~(a ^ mask)
```

### 5. 翻转二进制位

```python
def reverse_bits(n: int) -> int:
    ans = 0
    for _ in range(32):
        ans = (ans << 1) | (n & 1)
        n >>= 1
    return ans
```

### 6. 计数位 —— 借助前缀的 DP

```python
def count_bits(n: int) -> list[int]:
    ans = [0] * (n + 1)
    for i in range(1, n + 1):
        ans[i] = ans[i >> 1] + (i & 1)              # ans[i // 2] + 最低位
    return ans
```

`i >> 1` 就是去掉最低位的 `i`，所以 `ans[i] = ans[i >> 1] + (i 的最低位)`。

### 7. 枚举子集 —— 遍历所有位掩码

```python
def subsets_via_bitmask(arr: list[int]) -> list[list[int]]:
    n = len(arr)
    out: list[list[int]] = []
    for mask in range(1 << n):
        sub = [arr[i] for i in range(n) if mask & (1 << i)]
        out.append(sub)
    return out
```

### 8. 遍历某个掩码的子集

用于 DP over subsets（TSP 类问题很常用）：

```python
def submasks(mask: int):
    sub = mask
    while sub:
        yield sub
        sub = (sub - 1) & mask
    # sub == 0 也是它的一个子集
```

每次循环都产出 `mask` 的一个子集。除非显式 yield，否则会跳过空集。

### 9. 缺失的数字 —— 异或

```python
def missing_number(nums: list[int]) -> int:
    n = len(nums)
    ans = n                                     # 从最大的那个开始
    for i, x in enumerate(nums):
        ans ^= i ^ x
    return ans
```

`0..n` 的异或 与 `nums` 的异或 异或起来，剩下的就是缺失的那个值。

## 识别信号

- "只出现一次的数字"、"缺失的数字"、"其他都出现两次/三次" → 异或。
- "不用加法求和"、"不用除法做除法" → 位操作。
- "翻转二进制位"、"1 的个数" → 逐位处理。
- "小集合的子集" → 位掩码枚举。
- "格雷码"、"哈夫曼" → 位模式。
- "2 的幂" → `x > 0 and (x & (x - 1)) == 0`。

## 思考框架

1. **每一位代表什么？** 一个标志位、小枚举里的一个位置、或一个累加器。
2. **有没有位级别的不变量？** 异或满足结合律和交换律；进位会逐位传递。
3. **Python 里的溢出 / 符号？** Python 整数是任意精度的——没有溢出。若要 32 位语义，用 `& 0xFFFFFFFF`，并自己检查符号位。
4. **小集合的位掩码？** 当 n ≤ 20 时，状态就是掩码本身。

## Hot 150 例题

- **136. Single Number** —— 模式 1。
- **137. Single Number II** —— 各位计数 mod 3，或用"ones/twos"技巧。
- **260. Single Number III** —— 模式 1（两个唯一）。
- **191. Number of 1 Bits** —— `x.bit_count()` 或 `x &= x - 1` 循环。
- **338. Counting Bits** —— 模式 6。
- **190. Reverse Bits** —— 模式 5。
- **268. Missing Number** —— 模式 9（也可用求和公式）。
- **371. Sum of Two Integers** —— 模式 4。
- **7. Reverse Integer** —— 位移位，小心溢出。
- **9. Palindrome Number** —— 翻转一半再比较（不用字符串）。
- **67. Add Binary** —— 逐位加并处理进位。
- **78. Subsets** —— 模式 7 或回溯（第 11 章）。
- **90. Subsets II** —— 模式 7 + 去重。

## 易错点

- **`bin(-x)` 会带上 `-` 号** —— 若需要固定宽度，用 `bin(x & 0xFFFFFFFF)`。
- **Python 的 `~x == -x - 1`**，不是无符号整数的按位取反。任何时候都记得掩码到固定宽度。
- **`x >> k`，当 `x` 为负数时** —— Python 对负数的右移是**算术移位**（符号位扩展）。若要无符号行为，用 `x & 0xFFFFFFFF >> k`。
- **`1 << 32`** —— Python 没问题，但若题目指定 32 位，记得给结果加掩码。
- **`x & (x - 1) == 0`** —— 用来判断 2 的幂（也会把 0 判为 true）。要排除 0，需要加上 `x > 0`。
- **枚举子集的顺序：** `mask = 0 .. 2^n - 1` 这种遍历并不会按大小给你子集。若要"按大小"，用组合生成（第 11 章）。
- **遍历子集会跳过 0** —— 若需要空集，要显式处理。
- **`1 << 30` 的位计数是 1，不是 30。** 别把"位位置"和"数值"混淆。

(End of file - total 188 lines)
