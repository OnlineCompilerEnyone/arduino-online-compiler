# Arduino Online Compiler

在浏览器里贴一份 `platformio.ini` 和一段 `src/main.cpp`，云端用 PlatformIO 编译，然后下载加密后的固件产物——本地不需要装任何工具链。

这个项目是从 [ESPHome 在线编译](../esphome-online-compiler-main) 改造而来：保留了 OAuth 登录、双 token 降级、Workflow 派发、状态轮询、产物代理下载这些基础设施，把编译侧换成了 **PlatformIO + Arduino 框架**，输入从「一份 YAML」换成「`platformio.ini` + `src/main.cpp`」两个文本框。

## 功能

- ✅ 极简输入区：`platformio.ini`（CodeMirror INI 高亮）+ `src/main.cpp`（C++ 高亮），首次进入自带可编译的示例工程；也可切换为工程包 URL（zip/tar.gz 由 Actions 下载解压，URL 非空时优先生效）。
- ✅ 本地自动保存草稿、压缩包密码、PlatformIO 版本与最近一次编译状态，刷新页面后自动恢复并继续轮询。
- ✅ 产物为加密 zip：`firmware-<request_id>-password.zip`，密码可在页面上自定义并本地保存。
- ✅ 编译失败自动拉取失败 job 的日志并抽取错误上下文，同时保留 GitHub Workflow 链接。
- ✅ 双 token 策略：平台 `GITHUB_SERVICE_TOKEN` 优先，遇到 401/403/429 自动降级到个人 OAuth 授权。
- ✅ 中英双语界面（默认跟随浏览器语言）。

## 支持范围

| 项目 | 支持情况 |
| --- | --- |
| 平台（`platform`） | PlatformIO Registry 中的任意平台，只要它支持 Arduino 框架：`espressif32`、`espressif8266`、`atmelavr`（Arduino UNO / Mega）、`ststm32`、`raspberrypi`（Pico）等；可带 `@版本`，如 `espressif32@6.9.0`、`atmelavr@^4.0` |
| 框架（`framework`） | 必须包含 `arduino` |
| 板卡（`board`） | 对应平台的任意合法 board id，例如 `esp32dev`、`nodemcuv2`、`uno`、`megaatmega2560`、`pico` |
| 网页输入体积上限 | `platformio.ini` ≤ 24KB，`main.cpp` ≤ 64KB |
| Actions 工程包体积上限 | 下载 ≤ 50 MiB，解压后 ≤ 200 MiB，最多 10000 个条目 |
| 明确不支持 | `extra_scripts`、`platform_packages`、远程平台/依赖地址（`http(s)://`）、平台与工具链的本地路径，以及非 Arduino 框架 |

> 注意：官方 `platformio/espressif32` 当前停在 6.9.0（对应 Arduino core 2.0.17）。想用 Arduino core 3.x 或 ESP32-C6/H2/P4 需要把 `platform` 换成 pioarduino 维护的 fork，本项目出于安全考虑只允许平台**名称**、不允许远程平台 URL 或本地路径。

Arduino UNO 的最小可用配置：

```ini
[env:uno]
platform = atmelavr
board = uno
framework = arduino
```

## 输入方式

前端顶部可切换「在线编辑 / 工程包 URL」，也可以在 Actions 页手动运行 **Arduino Compile** 并填写 `project_url`。两种入口最终都通过 `workflow_dispatch` 交给 GitHub Actions：

| 方式 | 传给工作流的输入 | 说明 |
| --- | --- | --- |
| 在线编辑 | `encoded_ini` + `encoded_sketch` | Base64 编码的 `platformio.ini` 与 `src/main.cpp` |
| 工程包 / Actions 手动 | `project_url` | HTTP/HTTPS 链接，工作流用 `scripts/download-project.py` 下载并解压 |

优先级：`project_url` 非空时忽略 `encoded_ini` / `encoded_sketch`；下载、解压或校验失败会直接终止，**不会回退**到 Base64 输入。

工程包要求：

- 仅支持 ZIP 或 tar.gz；
- 压缩包**根目录**必须有 `platformio.ini`（不会自动剥离顶层文件夹），完整工程中的 `src/`、`include/`、`lib/`、`data/`、`boards/`、`scripts/`、`test/` 等内容会原样保留，不限定入口文件名；
- 只接受普通文件和目录，符号链接、硬链接、特殊文件、绝对路径和 `..` 穿越都会被拒绝；
- 下载 ≤ 50 MiB，解压后 ≤ 200 MiB，最多 10000 个条目。

网页提交的 URL 仅允许 `https://`，并拒绝本机/内网地址；Actions 手动填写的链接允许 `http://` 和 `https://`（HTTP 传输不加密，风险自担）。解压后会执行防御检查：`[env:]`、`platform` 必填，`framework` 如果显式声明则必须包含 `arduino`，并禁止 `extra_scripts`、`platform_packages` 与远程 HTTP/HTTPS 地址。这些检查不是安全沙箱，工程包里的代码和依赖仍会在无 secret 的 runner 上执行。

## 目录结构

```
.
├── frontend/                     Vue 3 + Vite SPA（编辑器、状态轮询、下载）
│   └── src/components/
│       ├── CodeEditor.vue        CodeMirror 6 封装（cpp / ini 两种语言）
│       └── CompileForm.vue       表单 + 编译状态机
├── functions/[[path]].ts         Cloudflare Pages Function：OAuth、会话、GitHub API 代理
├── scripts/collect-artifacts.sh  CI 与本地共用的产物收集脚本（含 merged bin、flash 命令）
├── scripts/download-project.py   Actions 工程包下载与安全解压
├── scripts/test-download-project.py  工程包下载/解压单元测试
├── .github/workflows/pio-compile.yml  PlatformIO 编译工作流
└── .dev.vars.example             Wrangler 本地密钥模板
```

## 本地开发

```bash
# 1. 前端
npm install --prefix frontend
npm run typecheck --prefix frontend   # vue-tsc 类型检查（可选但推荐）
npm run dev --prefix frontend         # http://localhost:5173

# 验证 Actions 工程包下载/解压
python3 scripts/test-download-project.py

# 2. Pages Functions（另开一个终端，需要 wrangler）
cp .dev.vars.example .dev.vars        # 填入 OAuth / 仓库配置
npm run build --prefix frontend       # 生成 frontend/dist
wrangler pages dev frontend/dist --local --port 8787
```

Vite 已把 `/auth/*` 与 `/api/*` 代理到 `http://127.0.0.1:8787`。

## 部署到 Cloudflare Pages

1. 新建 Pages 项目并连接本仓库。
2. 构建配置：
   - Build Command：`npm install && npm run build --prefix frontend`
   - Build Output Directory：`frontend/dist`
   - Functions Directory：`functions`
3. 在 **Settings → Variables（Production & Preview）** 配置：

| 变量 | 说明 |
| --- | --- |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth App 凭据 |
| `GITHUB_OAUTH_REDIRECT_URI` | 必须与 OAuth App 回调地址一致，例如 `https://<你的域名>/auth/callback` |
| `SESSION_SECRET` | 32+ 字节随机串（会话 cookie 的 HMAC 密钥） |
| `GITHUB_REPO_OWNER` / `GITHUB_REPO_NAME` | 承载 Actions 的仓库 |
| `GITHUB_WORKFLOW_ID` | `pio-compile.yml` |
| `GITHUB_WORKFLOW_REF` | 默认 `main` |
| `FRONTEND_URL` | 授权完成后的跳转地址 |
| `ALLOWED_ORIGINS` | 允许的跨域来源，逗号分隔 |
| `GITHUB_REQUIRE_PRIVATE_REPO` | 访问私有仓库时设为 `true`（会申请 `repo` scope） |
| `GITHUB_SERVICE_TOKEN` | 可选，平台默认 Fine-grained PAT（仅需 `workflow` + `public_repo`） |

## 编译流水线

```
浏览器                      Pages Functions                    GitHub Actions
  │ POST /api/compile {encodedIni, encodedSketch, password}  或 {projectUrl, password}
  │────────────────────────▶ 校验体积/密码/ini 白名单（URL 模式只校验 URL）
  │                          取 token（service 优先，失败降级 session）
  │                          workflow_dispatch ─────────────▶ 建 run（run-name 含 request_id）
  │◀── {requestId, runId}    按 run-name 匹配最近 run
  │ GET /api/status/...（10s 轮询）
  │────────────────────────▶ runs/:id + artifacts
  │◀── {status, conclusion, artifactUrl, failedJobId}
  │ GET /api/artifacts/...  手动跟随 302 到 Azure Blob 后流式回传
```

工作流步骤：下载工程包或解码输入 → 防御性校验 → 缓存 `.platformio` → 安装 PlatformIO → `pio run -d project` → 收集产物 → 打包加密 zip → 上传 artifact（保留 1 天）→ 写 Job Summary。

### GitHub Actions 手动编译完整工程

在 Actions 的 **Arduino Compile** 工作流中填写 `project_url`，提供可直接下载 ZIP 或 tar.gz 的 HTTP/HTTPS 链接。压缩包根目录必须有 `platformio.ini`；其他完整工程内容（例如 `src/`、`include/`、`lib/`、`data/`、`boards/`、`scripts/`、`test/`）会一并保留，不限定入口文件名。仅支持普通文件和目录，不支持符号链接、硬链接、特殊文件或越界路径。

`project_url` 非空时优先使用工程包，下载、解压或校验失败会直接终止，不会回退到 Base64 输入。留空时必须提供 `encoded_ini` 和 `encoded_sketch`，保持原有行为。两种方式都需要 `request_id` 和 `artifact_password`；`pio_version` 可选。网页表单同样支持 URL 模式，但仅限 `https://`。

工程包可包含 `scripts/`，但现有配置限制不变：`platformio.ini` 不能启用 `extra_scripts` 或 `platform_packages`，也不能包含远程 HTTP/HTTPS 地址。

### 产物内容

```
firmware-<request_id>-password.zip
└── <env>/
    ├── firmware.bin / firmware.hex / firmware.uf2
    ├── firmware.elf
    ├── bootloader.bin, partitions.bin, boot_app0.bin   （ESP32 系；boot_app0.bin 自动取自 Arduino 框架包）
    ├── merged-0x0.bin        ← 单文件镜像（仅 ESP32 系，含 bootloader/分区表/boot_app0/应用，直刷 0x0）
    └── flash_args.txt        ← 现成的 esptool / avrdude 命令
└── build.log
└── BUILD-INFO.txt
```

`flash_args.txt` 示例（ESP32）：

```bash
# 方式一（推荐）
esptool.py --chip esp32 -p COM_PORT -b 460800 write_flash 0x0 merged-0x0.bin

# 方式二（分段）
esptool.py --chip esp32 -p COM_PORT -b 460800 write_flash 0x1000 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
```

> **刷机注意（ESP32 系）**：`0xe000` 的 `boot_app0.bin` 会初始化 otadata，让 bootloader 启动你刚写入的 app0。如果设备**此前跑过别的 OTA 固件**，只写 `0x10000` 的 `firmware.bin`、不写 `boot_app0.bin` 时，bootloader 可能继续启动旧的 app1（现象：刷完没输出、跑的还是老固件）。稳妥做法是刷 `merged-0x0.bin`，或按方式二带上 `0xe000 boot_app0.bin`；也可以先执行：
>
> ```bash
> esptool.py --chip esp32 -p COM_PORT erase_region 0xe000 0x2000
> ```

AVR 板卡（Arduino UNO 等）的产物是 `firmware.hex`，`flash_args.txt` 会给出 avrdude 命令：

```bash
avrdude -p atmega328p -c arduino -P COM_PORT -b 115200 -U flash:w:firmware.hex:i
```

RP2040 板卡（`raspberrypi` 平台）的产物是 `firmware.uf2`，把开发板切到 BOOTSEL 模式后直接复制到对应磁盘即可。

## 安全说明

- 工作流固定 `permissions: contents: read`，构建过程中不注入任何 secret；`GITHUB_TOKEN` 不会被导出到构建环境。
- `platformio.ini` 在后端校验层做了校验，拦截 `extra_scripts`、`platform_packages`、远程 URL 与平台/工具链本地路径——这些都会在 runner 上执行任意代码；平台本身不再限制白名单，但只允许 PlatformIO Registry 中的正式名称（是否支持 Arduino 由 `framework` 决定）。**库（`lib_deps`）和第三方平台的安装脚本仍可能携带构建脚本，这是本方案残留的风险，公开服务上线前请自行评估。**
- URL 工程包来自不可信来源，完整工程中的代码和依赖可能影响构建；工作流的防御检查不等同于后端对网页输入的完整校验，也不是安全沙箱。`project_url` 作为工作流输入对有权查看运行信息的人可见，请勿在链接中放置凭据；Actions 手动填写的 HTTP 链接传输不加密。网页提交的 URL 仍由后端限制为 https，并拒绝本机/内网地址。
- 压缩包密码作为 `workflow_dispatch` 输入传递，能读该 run 的人可以看到它；密码只用于防止产物被随意抓取，不构成访问控制。
- 公开仓库的 Actions 分钟数免费，但任何人都能调用本服务消耗资源：上线前建议加 Cloudflare Turnstile、按 GitHub 用户/ IP 限流，并限制仓库并发。
- 永远不要把真实密钥写进仓库；生产变量走 Cloudflare 控制台，本地放 `.dev.vars`（已被 `.gitignore` 忽略）。

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `Unknown board ID` | `board` 写了平台里不存在的名字；先用 `pio boards <platform>` 查（如 `pio boards atmelavr`） |
| `工程包 URL 仅支持 https:// 链接` / `不能指向本机或内网地址` | 网页提交时只能使用公网可访问的 https 直链；Actions 手动运行额外接受 http |
| 工程包下载或解压失败 | 确认链接可直接下载、大小 ≤ 50 MiB、格式为 ZIP/tar.gz 且**根目录**包含 `platformio.ini`；解压后 ≤ 200 MiB、条目 ≤ 10000 |
| `Project download failed (HTTP 404)` | 链接失效或无权限（私有仓库需要带 token 的直链）；工作流不会回退到 Base64 输入 |
| `Could not find a version that satisfies the requirement platformio==x.y.z` | 版本号写错或该版本不存在，清空版本框用最新版即可 |
| 编译超时 | 工作流超时 25 分钟；首次编译需要下载平台与工具链，缓存命中后会快很多 |
| 产物里没有 `merged-0x0.bin` | 看 CI 日志里的 `merged image skipped ...` 原因：ESP8266/AVR 无分段镜像、esptool 未找到、或合并失败；分段 bins 和 `flash_args.txt` 仍然可用 |
| 刷完设备没输出 / 跑的仍是旧固件 | 设备之前跑过 OTA 固件，otadata 指向旧 app1；刷 `0xe000 boot_app0.bin`、改用 `merged-0x0.bin`，或 `esptool.py erase_region 0xe000 0x2000` 后重新刷 |
