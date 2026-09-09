# 16. 数学与几何

## 核心概念

下列常用模板应该能闭着眼睛写出来：

- **最大公约数 / 最小公倍数：** 欧几里得算法。
- **素数筛：** 埃氏筛，用于求出 N 以内的素数。
- **模运算：** 通过快速幂求 `a^b mod m`。
- **向量运算：** 叉积（用于判断方向、求面积）、点积（用于投影）、距离。
- **旋转：** 按角度 θ 逆时针旋转，或用矩阵做 90° 旋转。
- **进制转换：** 从任意进制 `b` 转十进制，反之亦然。

## 模式与模板

### 1. 最大公约数、最小公倍数

```python
from math import gcd
def lcm(a: int, b: int) -> int:
    return a // gcd(a, b) * b if a and b else 0
```

Python 3.9+ 自带 `math.lcm`。如果有可变数量的参数，可以用 `functools.reduce(lcm, nums)`。

### 2. 快速模幂

```python
def pow_mod(base: int, exp: int, mod: int) -> int:
    result = 1
    base %= mod
    while exp:
        if exp & 1: result = result * base % mod
        base = base * base % mod
        exp >>= 1
    return result
```

Python 内置的 `pow(base, exp, mod)` 就是这个功能，直接用就行。

### 3. 埃氏筛

```python
def primes_up_to(n: int) -> list[int]:
    if n < 2: return []
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return [i for i, is_p in enumerate(sieve) if is_p]
```

要做因式分解，可以用**最小素因子（SPF）筛**：

```python
def smallest_prime_factors(n: int) -> list[int]:
    spf = list(range(n + 1))
    for i in range(2, int(n**0.5) + 1):
        if spf[i] == i:                            # i 是素数
            for j in range(i * i, n + 1, i):
                if spf[j] == j: spf[j] = i
    return spf

def factorize(x: int, spf: list[int]) -> dict[int, int]:
    factors: dict[int, int] = {}
    while x > 1:
        p = spf[x]
        factors[p] = factors.get(p, 0) + 1
        x //= p
    return factors
```

### 4. 快乐数 / 各位数字提取

```python
def happy(n: int) -> bool:
    seen = set()
    while n != 1 and n not in seen:
        seen.add(n)
        n = sum(int(d) * int(d) for d in str(n))
    return n == 1
```

如果要求 O(1) 空间，用 Floyd 判环算法（见文件 02 / 文件 05）。

### 5. 罗马数字与整数互转

```python
def roman_to_int(s: str) -> int:
    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    prev = 0
    for ch in reversed(s):
        v = values[ch]
        total += -v if v < prev else v
        prev = v
    return total

def int_to_roman(num: int) -> str:
    table = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
             (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
             (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    out: list[str] = []
    for v, s in table:
        while num >= v:
            out.append(s); num -= v
    return ''.join(out)
```

### 6. 方向 / 叉积

对于三个点 `A, B, C`，`AB` 与 `AC` 的叉积可以判断它们的方向：

```python
def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
```

- `> 0`：A→B→C 逆时针。
- `< 0`：顺时针。
- `0`：三点共线。

常用于：凸包（Graham 扫描）、判断线段是否相交、判断点是否在多边形内。

### 7. 线段相交

```python
def segments_intersect(p1, p2, p3, p4) -> bool:
    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    # 共线的情况 —— 需要额外判断是否有重叠（不需要时跳过）
    return False
```

### 8. 矩阵原地顺时针旋转 90°

```python
def rotate(matrix: list[list[int]]) -> None:
    n = len(matrix)
    # 转置
    for i in range(n):
        for j in range(i + 1, n):
            matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]
    # 每行反转
    for row in matrix:
        row.reverse()
```

转置 + 每行反转 = 顺时针 90°。转置 + 每列反转 = 逆时针 90°。

### 9. 矩阵置零 —— O(1) 额外空间

```python
def set_zeroes(matrix: list[list[int]]) -> None:
    m, n = len(matrix), len(matrix[0])
    first_row_zero = any(matrix[0][j] == 0 for j in range(n))
    first_col_zero = any(matrix[i][0] == 0 for i in range(m))
    # 用第一行和第一列做标记
    for i in range(1, m):
        for j in range(1, n):
            if matrix[i][j] == 0:
                matrix[i][0] = 0
                matrix[0][j] = 0
    for i in range(1, m):
        for j in range(1, n):
            if matrix[i][0] == 0 or matrix[0][j] == 0:
                matrix[i][j] = 0
    if first_row_zero:
        for j in range(n): matrix[0][j] = 0
    if first_col_zero:
        for i in range(m): matrix[i][0] = 0
```

### 10. 加一 / 字符串加法

```python
def plus_one(digits: list[int]) -> list[int]:
    carry = 1
    for i in range(len(digits) - 1, -1, -1):
        carry, digits[i] = divmod(digits[i] + carry, 10)
        if carry == 0: break
    if carry: digits.insert(0, carry)
    return digits
```

### 11. 判断字符串是否是合法数字（有限状态机）

"Valid number" 这种题，要把所有合法状态和转移枚举出来。模板太长，建议在纸上画出状态图。

## 识别信号

- "gcd"、"lcm"、"公倍数" → 欧几里得算法。
- "素数"、"is prime"、"因式分解" → 筛法或试除。
- "power (x, n)"、"模幂" → 快速幂。
- "roman to integer"、"integer to roman" → 直接转换。
- "rotate image"、"矩阵转置" → 原地矩阵操作。
- "原地置零" → 标记行 / 标记列。
- "快乐数"、"丑数" → 各位提取 + 判环。
- "两条直线交点"、"线段是否相交" → 叉积。
- "凸包" → Graham 扫描或 Andrew 单调链。
- "检测正方形"、"直线对称" → 坐标对 + 哈希。

## 思考框架

1. **是否存在闭合公式？** 有时候是有的（等差数列求和、模逆元等）。
2. **要枚举素数吗？** N ≤ 10^7 用筛法；输入数量少但 N 大（> 10^7）用试除。
3. **涉及坐标几何？** 用叉积判断方向，点积做投影，距离用作半径。
4. **原地修改矩阵？** 用第一行 / 第一列做标记，最后再做清理。
5. **溢出问题？** Python 原生支持大整数，但也要留意题目对时间空间的要求。

## Hot 150 例题

- **9. Palindrome Number** —— 反转一半数字，不要转成字符串。
- **48. Rotate Image** —— 模式 8。
- **54. Spiral Matrix** —— 用方向控制移动并更新边界。
- **73. Set Matrix Zeroes** —— 模式 9。
- **50. Pow(x, n)** —— 快速幂；要正确处理负指数。
- **202. Happy Number** —— 模式 4。
- **66. Plus One** —— 模式 10。
- **13. Roman to Integer** —— 模式 5。
- **12. Integer to Roman** —— 模式 5。
- **7. Reverse Integer** —— 注意溢出；Python 里直接转字符串再判断范围就行。
- **172. Factorial Trailing Zeroes** —— 统计 5 的因子个数。
- **149. Max Points on a Line** —— 对每个点，用斜率分组（用约分后的分数避免浮点精度问题）。
- **224. Basic Calculator** —— 用两个栈（见文件 04）。
- **227. Basic Calculator II** —— 见文件 04。
- **43. Multiply Strings** —— 按位做小学竖式乘法。
- **69. Sqrt(x)** —— 在答案上做二分（见文件 10）。
- **168/171. Excel Sheet Column Title/Number** —— 26 进制（注意没有 0 这个数字！）。
- **31. Next Permutation** —— 从右往左找第一个 `nums[i] < nums[i+1]` 的位置 i，再从右往左找第一个比 nums[i] 大的元素交换，最后反转 i 之后的子数组。
- **1822. Sign of the Product of an Array** —— 统计负数和零的个数。

## 常见陷阱

- **`math.gcd(0, 0)`** 在较老版本的 Python 会抛 ValueError；要加 `if not a and not b: return 0` 保护。
- **负数取模：** Python 里 `(-3) % 7 == 4`，但移植到其他语言时要小心。
- **斜率分组时的浮点精度：** 永远不要直接用浮点数表示斜率。应当把 `(dy, dx)` 用 `gcd` 约分，再用 `(符号, dy // g, dx // g)` 作为 key。
- **`x ** 0.5`** 开平方会丢精度——用 `math.isqrt(x)`（整数平方根）或二分搜索。
- **模逆元**需要模数为素数；如果是合数模，用扩展欧几里得。
- **素数判定：** 对于单个 `n`，试除到 `sqrt(n)` 就够了。除非有多次查询，否则没必要筛。
- **Excel 列号：** 是 26 进制但数字范围是 1-26（不是 0-25）。要小心处理"没有 0"：先 `n -= 1; digit = n % 26; n //= 26`。
- **矩阵旋转方向：** 转置 + 行反转 = 顺时针。先反转列 = 逆时针。
- **矩阵置零：先标记再清理** —— 否则标记本身会污染未标记的格子。
- **阶乘尾零：** 每个 5 的因子贡献一个零。统计 `n//5 + n//25 + n//125 + ...`。
