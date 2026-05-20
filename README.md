# Portal Hub

一个本地 portal 管理平台。前端使用 Vue，后端使用 Python 标准库。

## 功能

- 检测当前本机已经启动的 localhost HTTP 服务，并写入工作空间。
- 展示工具链接、端口、PID、进程名、项目路径、启动命令和状态。
- 对配置过启动命令的工具执行启动、停止、重启。
- 手动添加新的工具链接和启动命令。
- 工作空间持久化到 `data/workspace.json`。
- 后端启动的进程日志保存在 `logs/`。

## 启动

```bash
python3 server.py
```

然后打开：

```text
http://localhost:4173
```

也可以指定端口：

```bash
PORT=4180 python3 server.py
```

## 说明

自动检测依赖 macOS/Linux 常见的 `lsof` 命令，并只会收录能通过 HTTP 探测访问的 localhost 服务。停止外部已启动服务时，会根据端口找到对应 PID 并发送 `SIGTERM`。
