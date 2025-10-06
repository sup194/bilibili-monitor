# Bilibili 动态通知脚本

一个简单的 Python 工具，用于定时轮询 Bilibili 指定 up 主的动态、视频投稿、专栏文章，并通过 Telegram、邮件或 Server 酱通知。

## 快速开始

1. 安装依赖：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 复制配置模板并填写：

   ```bash
   cp config.example.yaml config.yaml
   ```

   - `bilibili_users`：填写需要关注的 up 主 `mid`，可选配置 `name` 方便日志阅读。
   - `fetch`：控制是否拉取动态/视频/专栏。
   - `notifications.telegram`：启用后需要设置 Telegram Bot Token 和 Chat ID，默认读取 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量，也可通过 `proxy_env_var` 指定其他代理变量（值形如 `socks5://127.0.0.1:1080`）。
   - `notifications.email`：启用后需要设置 SMTP 的登录信息。
   - `notifications.serverchan`：启用 Server 酱 Turbo 通知时填写 SendKey（如 `SCTxxxxxxxx...`）。
   - `auth_cookies.sessdata`：如需访问受限接口，可填写从浏览器复制的 `SESSDATA`（注意风险，勿泄露）。
   - 本地运行建议将 `state_file` 指向 `state/state.json`（记得创建目录）；容器模式可改为 `/data/state.json` 并挂载到宿主机目录。

3. 运行脚本：

   ```bash
   python main.py --config config.yaml
   ```

   - 默认会每隔 `poll_interval_seconds` 轮询一次。
   - 调试时可添加 `--once --log-level INFO` 仅执行一次轮询。

### Docker 运行

1. 构建镜像：

   ```bash
   docker build -t bilibili-monitor .
   ```

2. 准备配置并指定状态文件挂载到容器。例如将 `config.yaml` 中的 `state_file` 调整为 `/data/state.json`：

   ```yaml
   state_file: /data/state.json
   ```

3. 启动容器（把当前目录中的配置和状态目录挂载进去）：

   ```bash
   make run
   ```

   - `make run` 会构建镜像并通过 Compose 以宿主机网络模式启动服务，`HTTP_PROXY_URL` 可在命令前覆盖或在 `Makefile` 中修改默认值。停止服务可使用 `make down`。

### Docker Compose 运行

1. （推荐）直接使用 `make run` 构建并启动，命令会自动创建 `state/` 与默认 `config.yaml`（如不存在）。

2. 手动操作时，可执行下列命令（需要 Docker 引擎支持 `network_mode: host`，在 Linux 上可用）：

   ```bash
   docker compose up -d
   ```

   - 默认会构建镜像并在容器内使用宿主机网络，方便访问本地代理。
   - 如需调整代理地址，可在命令前设置 `HTTP_PROXY_URL=http://your-proxy:port`，或在运行时设置 `HTTP_PROXY`/`HTTPS_PROXY`。
   - 停止服务：`docker compose down` 或 `make down`。

## 设计说明

- 使用 Bilibili 的公开 Web API 拉取各类数据，不需要登录。
- `state_file` 用于记录已经通知过的内容，避免重复推送。
- 如需抓取需要登录的接口（例如部分动态），可以在配置中填写 `auth_cookies.sessdata`。建议定期更新该 Cookie 并确保配置文件安全。
- Telegram 通知通过直接调用 Bot API 的 `sendMessage` 实现。
- 邮件推送使用标准的 `smtplib`，支持 TLS。
- Server 酱 Turbo 推送基于官方 HTTP API，可以在微信内实时接收更新。
- 数据抓取基于 `curl_cffi` 模拟 Chrome 指纹，自动获取 buvid、bili_ticket，并为需要的接口附加 WBI/WBI2 参数，尽量降低 B 站风控命中率。
