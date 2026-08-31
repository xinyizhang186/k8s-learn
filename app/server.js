// =============================================================================
// 访客计数器微服务 — K8s 入门学习项目
// -----------------------------------------------------------------------------
// 这是一个【零第三方依赖】的 Node.js HTTP 服务，用于演示 Kubernetes 各核心概念。
// 不使用 express / ioredis，仅用 Node 内置模块，便于阅读与构建最小镜像。
//
// 演示的 K8s 知识点（通过环境变量 / 运行时行为体现）：
//   - Pod 身份：通过 os.hostname() / os.networkInterfaces() 展示 Pod 名与 IP
//   - ConfigMap：TITLE / THEME 环境变量由 ConfigMap 注入
//   - Secret：DB_PASSWORD 由 Secret 注入（只判断是否配置，不回显明文）
//   - 探针：/healthz (liveness) /readyz (readiness) 分离
//   - StatefulSet + Redis：计数持久化到 Redis (StatefulSet + PVC)
//   - 指标：/metrics 暴露 Prometheus 文本格式
// =============================================================================

import http from 'node:http';
import os from 'node:os';
import net from 'node:net';
import fs from 'node:fs';

// ---- 配置（来自环境变量，对应 ConfigMap / Secret / k8s Downward API） ----
const PORT = Number(process.env.PORT ?? 8080);
const TITLE = process.env.TITLE ?? 'K8s 访客计数器';
const THEME = process.env.THEME ?? 'dark';
// Secret 注入：这里只演示"是否配置"，绝不回显明文
const HAS_DB_PASSWORD = Boolean(process.env.DB_PASSWORD);
const POD_NAME = process.env.POD_NAME ?? os.hostname();
const POD_NAMESPACE = process.env.POD_NAMESPACE ?? 'default';
const NODE_NAME = process.env.NODE_NAME ?? 'unknown';
// Downward API 注入的 CPU/Memory 请求（见 deployment 中的 envFrom downwardAPI）
const CPU_REQUEST = process.env.CPU_REQUEST ?? 'n/a';
const MEM_REQUEST = process.env.MEM_REQUEST ?? 'n/a';

// ---- 一个极简的 Redis 客户端（用 RESP 协议 over TCP，零依赖） ----
// 仅实现本项目用到的 INCR / GET 命令，用于演示与 StatefulSet 中的 Redis 通信。
class TinyRedis {
  constructor(url) {
    this.url = url; // 形如 redis://host:port
    this.sock = null;
    this.queue = []; // 命令响应等待队列
    this.buf = '';
    this.connected = false;
  }
  connect() {
    return new Promise((resolve, reject) => {
      if (!this.url) return resolve(false); // 无 REDIS_URL -> 内存模式
      const m = this.url.match(/^redis:\/\/([^:]+):(\d+)/);
      if (!m) return resolve(false);
      const sock = net.connect(Number(m[2]), m[1]);
      sock.setNoDelay(true);
      sock.on('error', () => { this.connected = false; });
      sock.on('connect', () => { this.connected = true; resolve(true); });
      sock.on('data', (chunk) => {
        this.buf += chunk.toString();
        // RESP 以 \r\n 分隔，逐行解析简单整数/批量回复
        while (this.buf.includes('\r\n')) {
          const idx = this.buf.indexOf('\r\n');
          const line = this.buf.slice(0, idx);
          this.buf = this.buf.slice(idx + 2);
          const waiter = this.queue.shift();
          if (!waiter) continue;
          if (line[0] === ':') waiter.resolve(Number(line.slice(1)));
          else if (line[0] === '$') {
            // 批量字符串：下一行是数据
            const len = Number(line.slice(1));
            if (len < 0) { waiter.resolve(null); continue; }
            const dataEnd = this.buf.indexOf('\r\n');
            waiter.resolve(this.buf.slice(0, dataEnd));
            this.buf = this.buf.slice(dataEnd + 2);
          } else waiter.resolve(line);
        }
      });
      // 连接超时
      setTimeout(() => { if (!this.connected) { sock.destroy(); reject(new Error('redis timeout')); } }, 1500);
      this.sock = sock;
    }).catch(() => false);
  }
  cmd(...args) {
    return new Promise((resolve, reject) => {
      if (!this.connected) return reject(new Error('redis not connected'));
      // 编码为 RESP 数组：*N\r\n$len\r\narg\r\n...
      let payload = `*${args.length}\r\n`;
      for (const a of args) { payload += `$${Buffer.byteLength(a)}\r\n${a}\r\n`; }
      this.queue.push({ resolve, reject });
      this.sock.write(payload);
      setTimeout(() => reject(new Error('redis cmd timeout')), 1500);
    });
  }
  close() { this.sock?.destroy(); }
}

// ---- 初始化 Redis（失败则降级为内存计数，保证服务可用） ----
const redis = new TinyRedis(process.env.REDIS_URL);
let redisReady = false;
let memCounter = 0; // 降级用内存计数器

const ready = await redis.connect();
redisReady = ready;
if (redisReady) console.log('[app] 已连接 Redis:', process.env.REDIS_URL);
else console.log('[app] Redis 不可用，降级为内存计数');

async function incrCounter() {
  if (redisReady) {
    try { return await redis.cmd('INCR', 'visits'); }
    catch { /* 跌回内存 */ }
  }
  return ++memCounter;
}
async function getCounter() {
  if (redisReady) {
    try { return await redis.cmd('GET', 'visits'); }
    catch { /* 跌回内存 */ }
  }
  return memCounter;
}

// ---- HTTP 服务 ----
const startTime = Date.now();
let totalRequests = 0;

const ACCESS_LOG = '/var/log/app/access.log';
function writeAccessLog(method, url) {
  try { fs.appendFileSync(ACCESS_LOG, `${new Date().toISOString()} ${method} ${url}\n`); } catch {}
}

function podIp() {
  const ifs = os.networkInterfaces();
  for (const name of Object.keys(ifs)) {
    for (const it of ifs[name]) {
      if (it.family === 'IPv4' && !it.internal) return it.address;
    }
  }
  return 'unknown';
}

function renderHtml(count) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${TITLE}</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0;padding:0;display:flex;justify-content:center;align-items:center;min-height:100vh;
    background:${THEME === 'light' ? '#f5f5f5' : '#0b1020'};color:${THEME === 'light' ? '#222' : '#e5e7eb'}}
  .card{background:${THEME === 'light' ? '#fff' : '#151c2c'};border-radius:16px;padding:32px 40px;box-shadow:0 10px 40px rgba(0,0,0,.3);max-width:560px;width:90%}
  h1{margin:0 0 8px;font-size:22px}
  .count{font-size:56px;font-weight:800;color:#60a5fa;margin:12px 0}
  .meta{font-size:13px;color:#9ca3af;line-height:1.8}
  .tag{display:inline-block;background:rgba(96,165,250,.15);color:#93c5fd;padding:2px 8px;border-radius:6px;margin:2px;font-size:12px}
  .ok{color:#34d399}.warn{color:#fbbf24}
</style></head>
<body><div class="card">
  <h1>${TITLE}</h1>
  <div>你是第 <span class="count">${count}</span> 位访客 🎉</div>
  <div class="meta">
    <div>当前计数后端：<span class="${redisReady ? 'ok' : 'warn'}">${redisReady ? 'Redis (StatefulSet)' : '内存 (降级)'}</span></div>
    <div>数据库密码：<span class="${HAS_DB_PASSWORD ? 'ok' : 'warn'}">${HAS_DB_PASSWORD ? '已配置 (Secret)' : '未配置'}</span></div>
    <hr style="border:0;border-top:1px solid #2d3748;margin:14px 0">
    <div><b>Pod 信息</b> (展示 K8s Pod 身份)</div>
    <span class="tag">Pod: ${POD_NAME}</span>
    <span class="tag">NS: ${POD_NAMESPACE}</span>
    <span class="tag">Node: ${NODE_NAME}</span>
    <span class="tag">IP: ${podIp()}</span>
    <div style="margin-top:10px"><b>资源请求</b> (Downward API)</div>
    <span class="tag">CPU: ${CPU_REQUEST}</span>
    <span class="tag">Mem: ${MEM_REQUEST}</span>
  </div>
</div></body></html>`;
}

const server = http.createServer(async (req, res) => {
  totalRequests++;
  writeAccessLog(req.method, req.url);
  const url = new URL(req.url, `http://${req.headers.host}`);

  // ---- 存活探针 (liveness)：只要进程在跑就 200 ----
  if (url.pathname === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ status: 'alive', uptime: Math.floor((Date.now() - startTime) / 1000) }));
  }
  // ---- 就绪探针 (readiness)：Redis 连通才接流量 ----
  if (url.pathname === '/readyz') {
    const ok = redisReady;
    res.writeHead(ok ? 200 : 503, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ status: ok ? 'ready' : 'not_ready', redis: redisReady }));
  }
  // ---- Prometheus 指标 ----
  if (url.pathname === '/metrics') {
    const count = await getCounter();
    res.writeHead(200, { 'content-type': 'text/plain; version=0.0.4' });
    return res.end(
      `# HELP learn_visits_total 访客总数\n# TYPE learn_visits_total counter\nlearn_visits_total ${count}\n` +
      `# HELP learn_http_requests_total HTTP 请求总数\n# TYPE learn_http_requests_total counter\nlearn_http_requests_total ${totalRequests}\n`,
    );
  }

  // ---- 主页：自增计数并展示 ----
  if (url.pathname === '/' || url.pathname === '/index.html') {
    const count = await incrCounter();
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    return res.end(renderHtml(count));
  }

  res.writeHead(404, { 'content-type': 'text/plain' });
  res.end('404 Not Found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[app] 访客计数器已启动 → http://0.0.0.0:${PORT}`);
  console.log(`[app] Pod=${POD_NAME} NS=${POD_NAMESPACE} Node=${NODE_NAME} IP=${podIp()}`);
  console.log('[app] 路由: / (主页) /healthz (存活) /readyz (就绪) /metrics (指标)');
});

// ---- 优雅关闭：收到信号先停止接收新连接 ----
function shutdown(sig) {
  console.log(`[app] 收到 ${sig}，开始优雅关闭...`);
  server.close(() => { redis.close(); console.log('[app] 已关闭'); process.exit(0); });
  setTimeout(() => process.exit(0), 3000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
