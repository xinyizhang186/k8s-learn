# Ollama 本地部署说明

## 1. 安装 Ollama

Windows 安装 Ollama 后，确认命令可用：

```powershell
ollama --version
```

## 2. 下载中文能力较好的模型

默认配置使用：

```powershell
ollama pull qwen2.5:7b
```

机器显存或内存较小，可以改用：

```powershell
ollama pull qwen2.5:3b
```

然后设置环境变量：

```powershell
$env:KP_OLLAMA_MODEL="qwen2.5:3b"
```

## 3. 启动 Ollama

一般安装后 Ollama 会作为本地服务运行，默认地址：

```text
http://127.0.0.1:11434
```

如果没有启动，可以执行：

```powershell
ollama serve
```

## 4. 检查 KnowledgePilot 是否识别到模型

```powershell
cd KnowledgePilot
python scripts/check_ollama.py
```

或者启动 API 后访问：

```text
http://127.0.0.1:8000/api/model/status
```

## 5. 启动项目

终端 1：

```powershell
cd KnowledgePilot
.\scripts\run_api.ps1
```

终端 2：

```powershell
cd KnowledgePilot
.\scripts\run_ui.ps1
```

浏览器打开：

```text
http://127.0.0.1:8501
```

## 6. 降级策略

如果 Ollama 没有安装、模型未下载或服务不可用，KnowledgePilot 不会崩溃，会自动回退到规则生成器。页面侧边栏会显示模型状态，Agent Trace 中也会显示 `LLM Generator used=false`。

