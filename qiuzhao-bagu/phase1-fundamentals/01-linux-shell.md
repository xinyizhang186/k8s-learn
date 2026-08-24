# Linux 开发与 Shell 基础 - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / vLLM / 大模型推理方向）
> 使用方式：每节先记结论加粗部分，再向下展开证据。面试时按"是什么 → 为什么 → 怎么做 → 注意点"四段式回答。

AI Infra = AI 基础设施（AI Infrastructure），负责让 AI 模型能够高效、稳定、大规模地训练和运行。
---

## 一、文件与目录

### Q1. `cp / mv / rm` 的常见坑？
- `cp -a` 保留权限/属主/时间戳，**目录拷贝必须加 `-a` 或 `-r`**。  
  -r = 递归复制目录 `cp -r source_dir target_dir`
  -a = archive 档案，递归 + 尽可能完整保留属性
- `mv` 跨文件系统会退化为 `cp + rm`（inode 改变，不能保证原子）。
  mv —— 移动 / 重命名  
  基本格式：`mv [选项] 源文件 目标位置`
    移动：`mv a.txt /tmp/` -> 当前目录/a.txt： /tmp/a.txt
    重命名：mv old.txt new.txt
  inode 是文件系统内部的数据结构。
  mv /data/a /mnt/a
- `rm -rf` 通配符：**绝对不要写 `rm -rf $FOO/*`，若 `$FOO` 为空，会展开成 `rm -rf /*`**，应写 `rm -rf "${FOO:?unset}"/*`。
  rm —— 删除
  基本格式：rm [选项] 文件
    删除多个文件：rm a.txt b.txt c.txt
    删除目录： rm -r dir/

### Q2. 软链接 vs 硬链接？
| 维度 | 硬链接 (hard link) | 软链接 (symbolic link) |
|---|---|---|
| 本质 | 同一 inode 多个 dentry | 一个新文件，存路径 |
| 跨文件系统 | 不可以 | 可以 |
| 删除原文件 | 仍可用 | 失效（dangling） |
| 命令 | `ln src dst` | `ln -s src dst` |
| inode | 与原文件相同 | 不同 |
ln : 创建链接的命令
dentry是 Linux VFS(Virtual File System，虚拟文件系统) 中用于表示目录项的结构，建立文件名与 inode 之间的关联，并参与路径名解析；

**面试要点**：`ls -i file` 看 inode；硬链接计数用 `ls -l file` 第二列。

### Q3. 权限 `rwxr-xr-x` 的数字？
- `r=4 w=2 x=1`，三组（owner/group/other）累加。
- `chmod 755 file` = `rwxr-xr-x`。
- 目录的 `x` 含义是"可进入"（cd 进去），不是执行。
  chmod 就是修改文件权限。基本语法：`chmod 权限 文件`

### Q4. `umask 022` 含义？
- 默认目录权限 = `777 & ~022 = 755`。
- 默认文件权限 = `666 & ~022 = 644`。
- **关键**：文件默认不带 `x`，避免代码自动可执行。
  umask = 创建文件时，默认要去掉哪些权限。  

### Q5. `find` 常用组合？
```bash
# 1. 按时间清理：7 天前修改的 .log 删除
find /var/log -name '*.log' -mtime +7 -delete
  mtime = 文件内容最后一次修改的时间 
  m = modification（修改）
  time = 时间

# 2. 按大小找：>100M 的文件
find / -type f -size +100M 2>/dev/null
  -type f：只找普通文件
  2>/dev/null = 把 stderr（错误信息）扔进 /dev/null，也就是不显示错误。

# 3. 按权限找 SUID（安全审计）
find / -perm -4000 -type f 2>/dev/null
  SUID 特殊权限位 → 数字：4000 → 作用：程序以“文件所有者”的有效身份运行

# 4. -exec 安全版（处理文件名带空格/换行）：用 -print0 + xargs -0
find . -name '*.py' -print0 | xargs -0 wc -l
  -print0：找到文件后，不用换行分隔，而使用 NUL（空字符）分隔。 -print0 = 安全地输出文件名
  |：管道（pipe）, 作用是 左边命令的输出,传给右边命令
  xargs：把前面传过来的文件名，转换成后面命令的参数。
  -print0 使用 NUL 分隔文件名；xargs -0 按照 NUL 分隔读取
  wc：word count，统计数量
  -l：统计行数（line）

``` 
  find 基本语法：find [路径] [条件]
    find → 从哪里开始找 → 按照什么条件找
  加条件 -name： find [路径] -name [文件名]  
    find . -name "*.txt"  从当前目录开始，寻找名字匹配 *.txt 的文件。
  加操作  find [路径] [条件] [操作] 
    find . -name "*.txt" -delete  从当前目录找, 找 txt 文件, 找到后删除

---

## 二、文本处理三剑客（grep/sed/awk）

### Q6. `grep` 与 `egrep` 区别？常用参数？
- `egrep` = `grep -E`，支持扩展正则（`+`、`|`、`()`）。
  -E：使用扩展正则表达式（Extended Regular Expression）。
- 常用：`-i` 忽略大小写、`-v` 反选（不匹配的行）、`-n` 显示行号、`-r` 递归、`-c` 计数（统计匹配的行数（count））、`-A/-B/-C N` 上下文。
- `grep -P` 启用 PCRE（支持 `\d` `\s` 等）。
- `grep -l` 只列出匹配文件名（用于跨文件批量定位）。
  grep：在文本中搜索指定的内容。
  基本语法： grep [选项] "要搜索的内容" 文件
  -A 2：显示匹配行 以及后面 2 行。-A = After   后面
  -B 2：显示匹配行 以及前面 2 行。-B = Before  前面
  -C 2：显示匹配行前后各 2 行。   -C = Context 上下文


### Q7. `sed` 替换、原地修改、行范围？
```bash
# 替换每行第一个 foo 为 bar
sed 's/foo/bar/'  # 默认每一行只替换第一个 foo。
    s / foo / bar /
    │   │     │
    │   │     └── 替换成什么
    │   └──────── 找什么
    └──────────── substitute（替换）

# 全局替换
sed 's/foo/bar/g'
  g = global：每一行中所有匹配的 foo 都替换。

# 原地修改（GNU sed），等价 mac 上 sed -i ''
sed -i 's/foo/bar/g' file
  sed 默认不会修改原文件
  读取 file → 处理 → 把结果显示到终端。原来的 file 通常不会被修改。
  -i = in-place：直接修改原文件。

# 只对 10-20 行处理
sed '10,20s/foo/bar/g' file
  10,20：指定行范围

# 删除空行
sed '/^$/d' file
  ^表示：行的开头；$表示：行的结尾
  ^$表示：从行开头直接到行结尾，中间什么都没有。（即 空行）
  d表示：delete，删除。

# 第 5 行后插入
sed '5a\hello' file
  a表示：append，追加
```
  sed (stream editor,流编辑器)：一个用于处理文本的命令行工具，特别常用于查找、替换、删除、插入文本。
  基本语法: sed '操作' 文件
  s = substitute（替换）
  g = global（全部）
  -i = 原地修改
  d = delete（删除）
  a = append（追加）


### Q8. `awk` 基本范式与内建变量？
- 内建变量：`NR`（行号）、`NF`（字段数）、`$0`（整行）、`$1..$N`（字段）、`FS`（字段分隔符）、`OFS`（输出分隔符）。
- 结构：`BEGIN {} 主循环{} END {}`。
  awk '
    BEGIN { # 开始处理之前执行一次}
    {
        # 每读取一行执行一次
    }
    END { # 全部处理完之后执行一次}
  ' file
      开始
      ↓
      BEGIN
      ↓
      读取第1行 → 主循环
      ↓
      读取第2行 → 主循环
      ↓
      读取第3行 → 主循环
      ↓
      ...
      ↓
      全部结束
      ↓
      END
- 例：统计 access.log 每个 IP 出现次数并排序
```bash
awk '{ip_cnt[$1]++} END {for (ip in ip_cnt) print ip_cnt[ip], ip}' access.log | sort -rn | head
  ip_cnt[$1]++： awk 的数组计数。
``` 
  awk 处理“按列排列的文本数据”的命令。awk：把文本按行读取，再把每一行切成多个字段（列），然后对这些字段进行处理。awk = 按行读取 → 按列拆分 → 对列进行处理。
  awk 基本语法：awk '条件 {操作}' 文件
  $0 表示：当前整行内容。
  NF：Number of Fields，当前行有多少个字段。
  NR：Number of Records，当前是第几行。
  FS：Field Separator。告诉 awk：一行数据应该按照什么东西切成不同的列。默认情况下，awk 通常按照空白字符分隔。
  OFS：Output Field Separator，输出字段分隔符。
  head：默认取前 10 行。

### Q9. `sort` `uniq` `cut` `tr` `xargs` 组合？
```bash
# 取 top 10 IP
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head

# cut 按列：取 /etc/passwd 第 1 列
cut -d: -f1 /etc/passwd

# tr 转换/删除字符：把 \r 删掉
tr -d '\r' < win.txt > unix.txt

# xargs 把 stdin 当作参数：批量删除
find . -name '*.pyc' | xargs rm -f
# 安全版（文件名带空格）
find . -name '*.pyc' -print0 | xargs -0 rm -f
```
  sort：排序  sort 文件 # 默认按照字典序排序。
    -n：按数字大小排序。
    -r：反向排序。
  uniq：去除连续重复行。uniq 只处理相邻的重复行。
    sort file | uniq 先排序，再uniq。才能真正合并重复项。
    -c：统计每行出现次数。
  cut：截取列  cut 适合处理固定分隔符的文本。
  基本语法：cut -d分隔符 -f列号 文件
  tr：转换或删除字符。   tr 用途：把字符替换成另一个字符，或者删除字符。
  xargs：把输入变成参数。xargs：把 stdin（标准输入）中的内容，转换成后面命令的参数。
    echo "a.txt b.txt" | xargs rm  等价于 rm a.txt b.txt

---

## 三、进程与信号

### Q10. `&`、`nohup`、`disown`、`setsid` 的区别？
| 方式 | 后台运行 | 挂断（SIGHUP）后存活 | 脱离父进程组 |
|---|---|---|---|
| `cmd &` | 是 | 否 | 否 |
| `nohup cmd &` | 是 | **是** | 否 |
| `disown`（已运行 job） | 不变 | 是 | 否 |
| `setsid cmd` | 是 | 是 | **是**（变孤儿进程） |

**关键**：`nohup` 仅屏蔽 SIGHUP，输出仍需重定向（默认 `nohup.out`）。要让进程真正脱离终端控制（防 tty 关闭时被杀），用 `setsid` 或 `nohup ... &` + `disown`。

### Q11. `kill` / `kill -9` / `kill -15` 区别？
- `kill <pid>` 默认发 `SIGTERM`（15），进程可捕获后清理（关闭 fd、flush）。
- `kill -9 <pid>` 发 `SIGKILL`，**不可捕获、不可阻塞**，立即清理内核态资源，但用户态 buffer 可能丢失。
- `kill -15` = `SIGTERM`，"优雅关闭"。
- `kill -HUP` 常用于让 daemon 重读配置。
- `kill -0 <pid>` 不发信号，只探测进程是否存在。

### Q12. 僵尸进程（Z 状态）vs 孤儿进程？
- **僵尸 (Z)**：子进程已退出，但父进程未 `wait()`，内核保留 task_struct 等待回收。修复：让父进程 `wait`，或杀掉父进程让 init 接管。
- **孤儿**：父进程先退出，子进程被 init (PID 1) 收养，正常运行不受影响。
- **长时间 D 状态**（不可中断睡眠）：通常是 IO 等待，`kill -9` 也无效；用 `iotop` / `iostat` 排查。

### Q13. `top` 关键字段含义？load average？
- `load average: 1.23, 1.10, 0.95` = 1/5/15 分钟**运行队列平均长度**（含 D 状态）。8 核机器上 >8 才算过载。
- `us`（用户 CPU）、`sy`（内核 CPU）、`wa`（IO wait）、`id`（idle）、`ni`（nice 调整过）。
- `PR` = priority，`NI` = nice（-20 到 19，**值越小优先级越高**）。
- `VIRT` 虚拟地址空间（含 swap、未映射部分），`RES` 物理内存实际占用，`SHR` 共享内存。

### Q14. `ps` 常见组合？
```bash
ps -ef            # 全格式，看 PPID
ps aux --sort=-%cpu | head   # 按 CPU 降序
ps -L <pid> -o pid,tid,psr,comm   # 查看进程线程及所在 CPU
```

### Q15. `nohup` 后台进程怎样查看日志输出？
- `nohup cmd > out.log 2>&1 &` ：stdout 和 stderr 都进 out.log。
- `2>&1` 必须放在 `>` 之后，因为 shell 从左到右解析重定向。
- 实时跟踪：`tail -f out.log`。

---

## 四、IO、磁盘、性能

### Q16. `df -h` 与 `du -sh` 区别？
- `df` 看文件系统整体使用（含 inode 耗尽情况：`df -i`）。
- `du` 看目录实际占用。两者差异：被删除但 fd 还打开的文件，`df` 还算占用，`du` 不算。
- **常见排错**：磁盘满但 `du` 找不到文件 → `lsof | grep deleted`，重启持有 fd 的进程或 `kill`。

### Q17. `iostat` `vmstat` 关键指标？
- `iostat -x 1`：%util（>80% 接近饱和）、await（IO 响应时间，毫秒级正常）、svctm。
- `vmstat 1`：`r`（运行队列，>CPU 数说明饱和）、`b`（D 状态进程）、`bi/bo`（块 IO）、`si/so`（swap in/out，非 0 说明内存压力）。

### Q18. `free -h` 各字段含义？buffer/cache 是什么？
- `total` 物理内存总量；`used` = total - free - buffer/cache；`free` 完全空闲；`buff/cache` 内核 buffer+page cache；`available` 应用可用（≈ free + reclaimable cache）。
- **关键**：判断内存压力看 `available`，不是 `free`。Linux 倾向"内存闲着也是浪费"，主动用 page cache。

### Q19. `lsof` 常用？
```bash
lsof -i:8080            # 看端口 8080 被哪个进程占用
lsof -p 1234            # 看进程 1234 打开的所有文件
lsof +D /var/log        # 看目录下被打开的文件
lsof | grep deleted     # 找被删但 fd 仍占用的（解释 df vs du 不一致）
```

### Q20. CPU 性能分析工具栈？
- `top/htop`：宏观概览。
- `pidstat -d/-r/-u 1`：每进程 CPU/内存/IO。
- `perf top` / `perf record -g -p <pid> && perf report`：函数级 CPU 采样（火焰图基础）。
- `strace -p <pid> -c`：系统调用统计。
- `flamegraph`：Brendan Gregg 的火焰图工具，`perf script | stackcollapse-perf.pl | flamegraph.pl > flame.svg`。

---

## 五、网络

### Q21. `tcpdump` 与 `ss` 常用？
```bash
ss -tnp                # 当前 TCP 连接 + 进程
ss -ltnp               # 仅监听端口
tcpdump -i eth0 -nn -s0 -w out.pcap 'port 80 and host 10.0.0.1'
tcpdump -r out.pcap -A # 回放并以 ASCII 显示
```

### Q22. `curl` 常用选项？
```bash
curl -v https://api.example.com/        # 显示完整请求/响应
curl -X POST -H 'Content-Type: application/json' -d '{"k":1}' url
curl -w '%{http_code} %{time_total}\n' -o /dev/null -s url   # 仅看状态码和耗时
curl --resolve api.example.com:443:1.2.3.4 https://api.example.com/   # 跳过 DNS
```

### Q23. 排查"连不上"网络问题四步？
1. `ping` 测三层连通（注意 ICMP 可能被禁）。
2. `traceroute -T -p 80 host` 或 `mtr -T -P 80 host` 看路径。
3. `telnet host 80` 或 `nc -zv host 80` 看四层端口。
4. `tcpdump` 看握手包：是否 SYN 没回、RST 还是 timeout。

### Q24. `iptables` / `nftables` 默认链？
- 五链：`PREROUTING`、`INPUT`、`FORWARD`、`OUTPUT`、`POSTROUTING`。
- 四表：`raw`（连接追踪前）、`mangle`（修改包）、`nat`（地址转换）、`filter`（过滤）。
- Docker 依赖 `nat` 表 + `FORWARD` 链放行。

---

## 六、Shell 脚本与 Bash

### Q25. 单引号、双引号、反引号区别？
- 单引号 `'$VAR'`：完全字面，无变量展开、无转义。
- 双引号 `"$VAR"`：变量展开、命令替换（`` `cmd` `` 或 `$(cmd)`）、转义保留。
- 反引号 `` `cmd` ``：命令替换，**已被 `$(cmd)` 取代**（可读性、嵌套性更好）。
- **建议**：变量永远加双引号 `"$VAR"`，防 word splitting + globbing。

### Q26. `${var:-default}` `${var:=default}` `${var:?err}` 区别？
- `:-` 仅当 var 为空时使用 default，**不赋值**。
- `:=` 当 var 为空时把 default 赋值给 var。
- `:?` 当 var 为空时报错并退出，提示信息为 err。
- `:+` 当 var **非空**时使用 alt。

### Q27. `set -euo pipefail` 含义？
- `set -e`：任何命令失败立即退出（含管道非末尾命令，但默认仅看管道最后）。
- `set -u`：使用未定义变量报错。
- `set -o pipefail`：管道任一阶段失败即整体失败。
- 三者合写：`set -euo pipefail`，**生产脚本必备**。
- 注意：`local x=$(false)` 会触发 `set -e` 退出，要写 `local x; x=$(false)`。

### Q28. Bash 数组、关联数组、mapfile？
```bash
arr=(a b c)                       # 普通数组
echo "${arr[@]}" "${#arr[@]}"     # 全部元素 + 个数
arr[2]=x                          # 单元素赋值

declare -A m=([k1]=v1 [k2]=v2)   # 关联数组（需 bash 4+）
for k in "${!m[@]}"; do echo "$k=${m[$k]}"; done

mapfile -t lines < file           # 把文件每行作为元素读入数组
```

### Q29. Here-doc、Here-string、子 shell？
```bash
# Here-doc：多行输入，结尾标记顶格
cat <<EOF
line1
EOF

# Here-string：单行喂给 stdin
grep foo <<<"$myvar"

# 子 shell：() 在新进程中执行，不影响当前 shell 变量
(cd /tmp && do_something)        # 当前 shell 仍在原目录
```

### Q30. `&&` `||` `;` 的优先级？
- Bash 中 `&&` 和 `||` **优先级相同，从左到右结合**。
- `a && b || c` 的坑：当 `a` 成功但 `b` 失败时，会执行 `c`，而非"a 失败时才 c"。
- 正确写法：`a && b || { c; }` 或用 `if a; then b; else c; fi`。

### Q31. 函数、局部变量、return vs exit？
```bash
add() {
  local x=$1 y=$2     # local 必须显式，否则污染全局
  echo $((x + y))     # 函数 stdout 是返回值
  return 0            # 0-255 是 exit code
}
result=$(add 3 4)     # 捕获 stdout
```
- `exit` 终止整个脚本；`return` 仅终止函数。函数没有"返回值对象"，靠 stdout + exit code 传值。

### Q32. `xargs` 的 `-I` 占位符与并行？
```bash
# 每行作为参数，并行 8 个进程
find . -name '*.py' -print0 | xargs -0 -P 8 -I {} pylint {}

# 默认是把 stdin 接到命令末尾，等价于
find . -name '*.py' -print0 | xargs -0 -P 8 pylint
```

---

## 七、系统启动与服务管理

### Q33. systemd vs sysvinit 关键差异？
- systemd 启动并行（依赖图），sysvinit 串行。
- 配置单元 `unit` 文件位于 `/etc/systemd/system/`、`/usr/lib/systemd/system/`。
- 服务管理：`systemctl status/restart/start/stop/enable/disable <svc>`。
- 日志：`journalctl -u <svc> -f`（不再依赖 `/var/log/messages`）。
- 自启：`systemctl enable <svc>` 创建 symlink，`systemctl disable` 撤销。

### Q34. 运行级别 / target？
- sysvinit：`0` 关机、`1` 单用户、`3` 多用户文本、`5` 图形、`6` 重启。
- systemd target：`poweroff.target` / `rescue.target` / `multi-user.target` / `graphical.target` / `reboot.target`。
- `systemctl get-default` 看默认 target，`systemctl set-default multi-user.target` 切到文本。

### Q35. Cron 与 systemd timer？
- cron 表达式：`分 时 日 月 周 命令`。`*/5` 每 5 分钟。`5,15,25` 枚举。
- cron 环境变量受限，**PATH 不含 /usr/local/bin**，写绝对路径更安全。
- systemd timer 比 cron 更精准（精确到 ms）、自带日志（journal）、可设依赖关系。

---

## 八、其他高频小知识

### Q36. `/proc` 与 `/sys` 区别？
- `/proc`：进程与内核运行时信息（`/proc/<pid>/`、`/proc/cpuinfo`、`/proc/meminfo`、`/proc/loadavg`），偏"控制 + 状态"。
- `/sys`：设备树、内核模块、driver 控制（`/sys/class/net/`、`/sys/devices/`），偏"硬件抽象"。

### Q37. ulimit 与 cgroup 的关系？
- `ulimit` (PAM 模块)：对**单个 shell 会话**的进程数、文件数、内存等做软限制。
- cgroup：对**一组进程**做 CPU/内存/IO/设备访问控制，是 Docker/k8s 资源限制的基础。
- Docker `--memory`/`--cpus` 底层即 cgroup v1/v2。

### Q38. stdin/stdout/stderr 的 fd 编号？
- 0=stdin、1=stdout、2=stderr。
- 重定向 `2>&1` 含义：把 stderr 重定向到 stdout 当前指向的文件描述符。
- 顺序敏感：`cmd > f 2>&1`（合并）；`cmd 2>&1 > f`（stderr 仍指向终端）。

### Q39. 管道（`|`）的本质？
- 内核调用 `pipe()` 创建一对 fd，左命令 stdout 接右命令 stdin。
- 每个 `|` 启动**子 shell**，所以管道内变量赋值不会影响外层。
- 管道默认 buffer 64KB（Linux），`stdbuf -oL` 可改成行缓冲。
- 若右命令慢，左命令会在 `write` 处阻塞（生产者-消费者模式）。

### Q40. `time cmd` 的三种 time？
- **shell 内建 time**：`time cmd`（输出 real/user/sys，但格式不可控）。
- **/usr/bin/time**：`/usr/bin/time -v cmd`（详细，含 max RSS、page fault）。
- **GNU time**：可输出格式化字符串 `-f "%e %P %M"`。

---

## 九、AI Infra 高频面试题

### Q41. 大模型训练/推理场景常用 shell 一行命令？
```bash
# 1. 看 GPU/NPU 利用率（NVIDIA）
nvidia-smi --query-gpu=index,utilization.gpu,memory.used,temperature.gpu --format=csv -l 1
# 昇腾
watch -n 1 npu-smi info

# 2. 查显存占用 top 5 进程
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | sort -k2 -n -r | head -5

# 3. 持续打流压测
seq 1 1000 | xargs -P 20 -I{} curl -s -w '%{http_code} %{time_total}\n' -o /dev/null http://localhost:8000/v1/completions -d '{"prompt":"hello"}'

# 4. 找最大的 ckpt 文件
find /models -name '*.safetensors' -printf '%s %p\n' | sort -rn | head

# 5. 一行统计某目录所有 .py 行数（排除 venv）
find . -name '*.py' -not -path './venv/*' -print0 | xargs -0 wc -l | tail -1
```

### Q42. 如何快速排查"训练脚本卡住不动"？
1. `nvidia-smi` / `npu-smi info` 看 GPU/NPU 利用率是否为 0。
2. `py-spy dump --pid <pid>` 看 Python 调用栈（不需要修改代码）。
3. `top -H -p <pid>` 找最忙线程，`py-spy top --pid <pid>` 看实时函数热点。
4. `cat /proc/<pid>/wchan` 看内核态等待点（如 `futex_wait` → 锁竞争）。
5. `tcpdump` 或 `nsenter` 看 NCCL/HCCL 通信是否在等待某 rank。
6. 多卡训练卡死通常是 rank 0/1 通信 hang，检查 `NCCL_DEBUG=INFO` 日志。

### Q43. `LD_LIBRARY_PATH` 的作用与坑？
- 指定动态链接器额外搜索路径，CANN / CUDA / NCCL 安装常依赖。
- **坑**：永久写入 `/etc/profile` 会让所有程序都优先用该路径下的 `.so`，可能让系统命令（如 python）链接到错误的库版本。
- 推荐做法：仅在启动脚本里 export；正式部署用 `ldconfig` 注册 `/etc/ld.so.conf.d/cann.conf` 后 `ldconfig`。
- 验证当前程序链接了哪些库：`ldd $(which python)` 或 `ldd /path/to/libxxx.so`。

### Q44. 容器内 `/dev/shm` 太小导致 NCCL 报错？
- Docker 默认 `/dev/shm` 只有 64MB，NCCL/HCCL 共享内存通信会失败。
- 解决：`docker run --shm-size=16g` 或挂载 `-v /tmp/shm:/dev/shm`。
- k8s：emptyDir + `medium: Memory` + `sizeLimit`。

### Q45. 信号集与进程组关系？
- 每个进程属于一个**进程组**（pgid），会话（sid）包含多个进程组。
- 终端按 Ctrl+C 发 `SIGINT` 给**前台进程组所有进程**。
- `kill -- -<pgid>` 给整个进程组发信号（注意前面的 `-`）。
- Python 多进程训练：spawn 出来的子进程默认与父进程同组，Ctrl+C 会全收到。

---

## 十、一页速记卡（面试前 30 分钟复习）

| 类别 | 必背 |
|---|---|
| 文件权限 | `r=4 w=2 x=1`；`4755`=SUID；`1777`=sticky |
| 链接 | 硬链接同 inode、不跨 fs；软链接存路径、跨 fs |
| 文本三剑客 | `grep -i -n -v -E`；`sed -i 's/a/b/g'`；`awk -F: '{print $1}'` |
| 后台 | `nohup cmd >out 2>&1 &`；`jobs`/`bg`/`fg` |
| 性能 | `top` 看 load、`iostat -x 1`、`free -h` 看 available、`iostat`/`vmstat` |
| 网络 | `ss -ltnp`、`tcpdump -i any -nn -w f.pcap`、`curl -w` |
| 脚本 | `set -euo pipefail`；变量加引号；`${var:-d}`；`mapfile -t` |
| 系统 | `systemctl status/journalctl -u`；`/proc` vs `/sys`；`ulimit` vs cgroup |
| AI infra | `nvidia-smi dmon` / `npu-smi info`；`py-spy dump/top`；`/dev/shm` |
| 重定向 | `> f 2>&1` 合并；`cmd >> f` 追加；`< <(cmd)` 进程替换 |
