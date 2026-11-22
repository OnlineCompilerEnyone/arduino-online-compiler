---
name: arduino-online-compiler
description: 通过 GitHub Actions 云端编译 PlatformIO + Arduino 工程并取回固件。默认使用 Base64 模式（platformio.ini + src/main.cpp）；仅当用户能提供可下载的远程文件中转链接时才使用源码包（project_url）模式。
---

# Arduino 在线编译 Skill

调用 https://github.com/OnlineCompilerEnyone/arduino-online-compiler.git 仓库的 `Arduino Compile` 工作流（`.github/workflows/pio-compile.yml`），在云端用 PlatformIO 编译 Arduino 工程，下载加密后的固件产物。本地无需安装任何工具链。

本 Skill 是通用的，不要求在该仓库内使用：可在任意目录下执行，所有 `gh` 命令都通过 `-R` 指定该仓库。

## 模式选择

| 模式 | 工作流输入 | 何时使用 |
| --- | --- | --- |
| **Base64（默认、推荐）** | `encoded_ini` + `encoded_sketch` | 单文件草图（`platformio.ini` + `src/main.cpp`）。无需任何外部托管，最稳妥 |
| 源码包 | `project_url` | **仅当用户明确提供了远程文件中转方式**（可直链下载的 HTTP/HTTPS 链接）且工程有多文件/本地库/`data/` 等内容时使用 |

规则：

- 没有明确的中转链接时，一律用 Base64 模式；不要自行寻找或上传到第三方文件托管。
- `project_url` 非空时优先生效，且下载/校验失败**不会回退**到 Base64。
- 不要在链接里放置凭据（`project_url` 对能查看运行信息的人可见）。

## 前置条件

- 二选一：已安装并登录 `gh`（`gh auth status`，或设置了 `GH_TOKEN`），或使用 GitHub token + 下文的 curl 方式（token 见「Token 配置」）。账号/token 对 `OnlineCompilerEnyone/arduino-online-compiler` 有触发 `workflow_dispatch` 的权限。
- 需要 `base64`、`unzip`（支持密码）；Windows 上改用「Windows（PowerShell 等价实现）」一节，无需这些命令。
- 下文统一使用 `REPO=OnlineCompilerEnyone/arduino-online-compiler`；若用户使用了自己的 fork，替换该变量即可。

## Token 配置（先检查，不要每次向用户索要）

操作前先检查与本文件**同级目录**下是否存在 `github_action_token.env`（即 `skill/arduino-online-compiler/github_action_token.env`，模板见 `github_action_token.env.example`）：

```bash
SKILL_DIR="<本 SKILL.md 所在目录>"
if [ -f "$SKILL_DIR/github_action_token.env" ]; then
  set -a; . "$SKILL_DIR/github_action_token.env"; set +a   # 导出 GH_TOKEN
fi
[ -n "${GH_TOKEN:-}" ] || echo "未找到 GH_TOKEN"
```

- 文件内容为一行 `GH_TOKEN=<token>`；加载后 `gh` 和下文 curl 命令都直接使用 `GH_TOKEN`。
- 文件存在且 `GH_TOKEN` 非空时，直接使用，不再询问用户。
- 文件不存在或为空时，才请用户提供 token（或让用户创建该文件）；也可使用已有的 `GH_TOKEN` 环境变量 / `gh auth login` 登录态。
- 该文件含密钥：已被 `.gitignore` 忽略，不要提交、打印、回显或写入日志/回复。

## 通用输入

| 输入 | 必填 | 说明 |
| --- | --- | --- |
| `request_id` | 是 | 唯一标识，建议 `$(date +%s)-$RANDOM`，仅用字母数字和 `-` |
| `artifact_password` | 是 | 产物 zip 的密码，自行生成随机串并告知用户 |
| `pio_version` | 否 | PlatformIO Core 版本，如 `6.1.18`，留空用最新版 |

## Base64 模式（推荐）

1. 准备 `platformio.ini` 和 `src/main.cpp`。`platformio.ini` 示例：

   ```ini
   [env:esp32dev]
   platform = espressif32
   board = esp32dev
   framework = arduino
   monitor_speed = 115200
   ```

2. 触发工作流：

   ```bash
   REPO=OnlineCompilerEnyone/arduino-online-compiler
   REQ="$(date +%s)-$RANDOM"
   PASS="$(openssl rand -hex 8)"

   gh workflow run pio-compile.yml -R "$REPO" \
     -f request_id="$REQ" \
     -f artifact_password="$PASS" \
     -f encoded_ini="$(base64 -w0 platformio.ini)" \
     -f encoded_sketch="$(base64 -w0 src/main.cpp)"
   ```

   macOS 的 `base64` 没有 `-w0`，改用 `base64 -i <file> | tr -d '\n'`。

3. 等待并取回产物（见下文「等待与下载」）。

## 源码包模式（需要用户提供中转链接）

用户提供链接后（例如对象存储/文件中转站的直链）：

```bash
gh workflow run pio-compile.yml -R "$REPO" \
  -f request_id="$REQ" \
  -f artifact_password="$PASS" \
  -f project_url="https://example.com/project.zip"
```

源码包要求：

- 仅支持 ZIP 或 tar.gz；链接必须可**直接下载**（不是网页预览页），无需登录。
- 压缩包根目录必须有 `platformio.ini`；如果只有一个顶层文件夹（如 GitHub 的 Download ZIP），会自动展开。
- 下载 ≤ 50 MiB，解压后 ≤ 200 MiB，条目 ≤ 10000；不允许符号链接、硬链接、特殊文件、绝对路径和 `..`。
- 工作流允许 `http://` 与 `https://`，但 HTTP 不加密，优先用 HTTPS。
- 打包前清理 `.pio/`、`.git/`、`node_modules/` 等无关内容。

## 等待与下载

```bash
# 找到刚触发的 run（run-name 含 request_id）
sleep 5
RUN_ID="$(gh run list -R "$REPO" --workflow pio-compile.yml --limit 20 \
  --json databaseId,displayTitle -q ".[] | select(.displayTitle | contains(\"$REQ\")) | .databaseId" | head -n1)"

# 等待结束（首次编译需下载工具链，可能数分钟；工作流超时 25 分钟）
gh run watch "$RUN_ID" -R "$REPO" --exit-status

# 成功：下载并解压
gh run download "$RUN_ID" -R "$REPO" -n "firmware-$REQ" -D out
unzip -P "$PASS" "out/firmware-$REQ-password.zip" -d firmware
```

失败时查看日志尾部：

```bash
gh run view "$RUN_ID" -R "$REPO" --log-failed | tail -n 80
```

根据错误修改 `platformio.ini` / 代码后用新的 `request_id` 重试。产物只保留 1 天。

## 使用 curl + Token（无需安装 gh）

用户只需提供一个有 GitHub 权限的 token：经典 PAT 勾选 `workflow` + `public_repo`，或对目标仓库授予 `Actions: Read and write` 的 Fine-grained PAT。需要 `curl`、`jq`、`base64`、`unzip`。token 优先按上文「Token 配置」从 `github_action_token.env` 读取；不要打印 token 或写进日志、回复。

```bash
# GH_TOKEN 已按「Token 配置」加载；否则手动设置：export GH_TOKEN="<用户提供的 token>"
REPO=OnlineCompilerEnyone/arduino-online-compiler
API="https://api.github.com/repos/$REPO"
H=(-H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28")
REQ="$(date +%s)-$RANDOM"
PASS="$(openssl rand -hex 8)"

# 1) 触发（成功返回 HTTP 204）。Base64 模式：
jq -n --arg req "$REQ" --arg pass "$PASS" \
  --arg ini "$(base64 -w0 platformio.ini)" --arg sketch "$(base64 -w0 src/main.cpp)" \
  '{ref:"main", inputs:{request_id:$req, artifact_password:$pass, encoded_ini:$ini, encoded_sketch:$sketch}}' \
| curl -sS -o /dev/null -w '%{http_code}\n' -X POST "${H[@]}" -d @- "$API/actions/workflows/pio-compile.yml/dispatches"

# 源码包模式（仅用户提供了中转链接时）：
# jq -n --arg req "$REQ" --arg pass "$PASS" --arg url "https://example.com/project.zip" \
#   '{ref:"main", inputs:{request_id:$req, artifact_password:$pass, project_url:$url}}' \
# | curl -sS -o /dev/null -w '%{http_code}\n' -X POST "${H[@]}" -d @- "$API/actions/workflows/pio-compile.yml/dispatches"

# 2) 按 request_id 找到 run（run-name 含 request_id，可能要等几秒）
RUN_ID=""
for i in $(seq 1 12); do
  RUN_ID="$(curl -sS "${H[@]}" "$API/actions/workflows/pio-compile.yml/runs?event=workflow_dispatch&per_page=30" \
    | jq -r --arg req "$REQ" '.workflow_runs[] | select(.display_title | contains($req)) | .id' | head -n1)"
  [ -n "$RUN_ID" ] && break; sleep 5
done
echo "run: $RUN_ID  https://github.com/$REPO/actions/runs/$RUN_ID"

# 3) 轮询直到完成（首次编译可能数分钟，工作流超时 25 分钟）
while :; do
  R="$(curl -sS "${H[@]}" "$API/actions/runs/$RUN_ID")"
  STATUS="$(jq -r .status <<<"$R")"; CONCLUSION="$(jq -r .conclusion <<<"$R")"
  echo "$STATUS $CONCLUSION"
  [ "$STATUS" = completed ] && break; sleep 10
done

# 4a) 成功：下载 artifact（-L 跟随重定向）并解压（外层 artifact zip 无密码，内层固件 zip 需要 $PASS）
if [ "$CONCLUSION" = success ]; then
  ART_URL="$(curl -sS "${H[@]}" "$API/actions/runs/$RUN_ID/artifacts" \
    | jq -r --arg n "firmware-$REQ" '.artifacts[] | select(.name==$n) | .archive_download_url')"
  curl -sS -L "${H[@]}" -o artifact.zip "$ART_URL"
  unzip -o artifact.zip -d out
  unzip -P "$PASS" "out/firmware-$REQ-password.zip" -d firmware
else
  # 4b) 失败：取失败 job 的日志尾部
  JOB_ID="$(curl -sS "${H[@]}" "$API/actions/runs/$RUN_ID/jobs" | jq -r '.jobs[] | select(.conclusion=="failure") | .id' | head -n1)"
  curl -sS -L "${H[@]}" "$API/actions/jobs/$JOB_ID/logs" | tail -n 80
fi
```

说明：

- 触发返回 `401/403/404` 多为 token 权限不足或仓库不可访问；`422` 多为输入非法（如 `ref` 分支不存在，或缺少必填输入）。
- `ref` 默认 `main`，使用 fork 时按其默认分支调整。
- macOS 的 `base64` 没有 `-w0`，改用 `base64 -i <file> | tr -d '\n'`。

## Windows（PowerShell 等价实现）

Windows 上没有 bash 时，用系统自带的 Windows PowerShell 5.1 即可，不必安装 `gh`、`jq`、`base64`、`openssl`（pwsh 7 同样适用）。只有解压带密码的产物需要 7-Zip（`winget install 7zip.7zip`），因为 `Expand-Archive` 不支持密码。

先按「Token 配置」加载 token（Windows 写法）：

```powershell
$SkillDir = '<本 SKILL.md 所在目录>'
$envFile  = Join-Path $SkillDir 'github_action_token.env'
if (Test-Path $envFile) {
  ((Get-Content -LiteralPath $envFile) -match '^\s*GH_TOKEN=') |
    ForEach-Object { $env:GH_TOKEN = ($_ -replace '^\s*GH_TOKEN=', '').Trim() }
}
if (-not $env:GH_TOKEN) { throw '未找到 GH_TOKEN' }
```

变量与请求头：

```powershell
$Repo = 'OnlineCompilerEnyone/arduino-online-compiler'
$Api  = "https://api.github.com/repos/$Repo"
$H = @{
  Authorization          = "Bearer $env:GH_TOKEN"
  Accept                 = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
}
$Req  = '{0}-{1}' -f [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(), (Get-Random -Minimum 1000 -Maximum 99999)
$Pass = -join (1..32 | ForEach-Object { '0123456789abcdef'[(Get-Random -Maximum 16)] })
```

Base64 模式触发（`ToBase64String` 等价于 `base64 -w0`，单行无换行）：

```powershell
$ini    = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path 'platformio.ini')))
$sketch = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path 'src/main.cpp')))
$body = @{
  ref    = 'main'
  inputs = @{
    request_id        = $Req
    artifact_password = $Pass
    encoded_ini       = $ini
    encoded_sketch    = $sketch
  }
} | ConvertTo-Json -Depth 5 -Compress
Invoke-RestMethod -Method Post -Headers $H -ContentType 'application/json' -Body $body `
  -Uri "$Api/actions/workflows/pio-compile.yml/dispatches"
```

源码包模式把 `inputs` 换成 `@{ request_id = $Req; artifact_password = $Pass; project_url = 'https://example.com/project.zip' }`。

按 `request_id` 找 run（`run-name` 固定为 `Arduino compile • <request_id>`）：

```powershell
$RunId = $null
for ($i = 0; $i -lt 12 -and -not $RunId; $i++) {
  $runs  = Invoke-RestMethod -Headers $H -Uri "$Api/actions/workflows/pio-compile.yml/runs?event=workflow_dispatch&per_page=30"
  $RunId = ($runs.workflow_runs | Where-Object { $_.display_title -like "*$Req*" } | Select-Object -First 1).id
  if (-not $RunId) { Start-Sleep -Seconds 5 }
}
if (-not $RunId) { throw "没有找到 request_id=$Req 的 run" }
"run $RunId  https://github.com/$Repo/actions/runs/$RunId"
```

轮询并取回产物（外层 artifact zip 无密码，内层固件 zip 需要 `$Pass`）：

```powershell
do {
  Start-Sleep -Seconds 10
  $run = Invoke-RestMethod -Headers $H -Uri "$Api/actions/runs/$RunId"
  "$($run.status) $($run.conclusion)"
} while ($run.status -ne 'completed')

if ($run.conclusion -eq 'success') {
  $arts = Invoke-RestMethod -Headers $H -Uri "$Api/actions/runs/$RunId/artifacts"
  $url  = ($arts.artifacts | Where-Object { $_.name -eq "firmware-$Req" }).archive_download_url
  Invoke-WebRequest -Headers $H -Uri $url -OutFile 'artifact.zip' -UseBasicParsing
  Expand-Archive -LiteralPath 'artifact.zip' -DestinationPath 'out' -Force
  & "$env:ProgramFiles\7-Zip\7z.exe" x "out\firmware-$Req-password.zip" "-p$Pass" '-ofirmware' -y
} else {
  $jobs  = Invoke-RestMethod -Headers $H -Uri "$Api/actions/runs/$RunId/jobs"
  $jobId = ($jobs.jobs | Where-Object { $_.conclusion -eq 'failure' } | Select-Object -First 1).id
  $log   = Invoke-WebRequest -Headers $H -Uri "$Api/actions/jobs/$jobId/logs" -UseBasicParsing
  ($log.Content -split "`n") | Select-Object -Last 80
}
```

- `Invoke-RestMethod` 遇 4xx/5xx 直接抛异常，状态码取 `$_.Exception.Response.StatusCode.value__`；触发成功返回 204 且响应体为空，不抛异常即为成功。
- `archive_download_url` 会 302 到签名地址，`Invoke-WebRequest` 自动跟随；换主机时 .NET 会丢弃 `Authorization`，签名 URL 本就不需要它。
- 7-Zip 默认装在 `$env:ProgramFiles\7-Zip\7z.exe`；自定义安装目录时改该路径即可。
- 装 `gh` 亦可（`winget install GitHub.cli`），但本节命令不依赖它。

## 产物说明

```
firmware/
├── <env>/
│   ├── firmware.bin | firmware.hex | firmware.uf2
│   ├── firmware.elf
│   ├── bootloader.bin, partitions.bin, boot_app0.bin   （ESP32 系）
│   ├── merged-0x0.bin                                  （ESP32 系，单文件镜像，刷 0x0）
│   └── flash_args.txt                                  （现成的 esptool / avrdude 命令）
├── build.log
└── BUILD-INFO.txt
```

把 `flash_args.txt` 中的命令交给用户，`COM_PORT` 换成实际串口。ESP32 优先刷 `merged-0x0.bin`；RP2040 进入 BOOTSEL 后复制 `firmware.uf2`；AVR 用 `avrdude` 刷 `firmware.hex`。

## 限制（会被工作流直接拒绝）

- `platformio.ini` 必须有 `[env:xxx]` 和 `platform`；`framework` 若声明必须包含 `arduino`。
- 禁止 `extra_scripts`、`platform_packages`，以及任何 `http(s)://` 远程地址（请使用 registry 名称与版本号，如 `lib_deps = adafruit/Adafruit NeoPixel@^1.12.0`）。
- 不要在工程或输入中放任何密钥；构建运行在无 secret 的 runner 上，`artifact_password` 对能看到该 run 的人可见，仅用于防止产物被随意抓取。
- 板卡 ID 不确定时，用 `pio boards <platform>` 查询。

## 排错速查

| 现象 | 处理 |
| --- | --- |
| `Missing Base64 project inputs` | `encoded_ini` / `encoded_sketch` 为空；确认文件存在且已编码 |
| `Unknown board ID` | board 写错，查 `pio boards <platform>` |
| `Project download failed` | 中转链接失效/需要登录/不是直链；确认后重试 |
| 工程包根目录缺 `platformio.ini` | 重新打包，保证 `platformio.ini` 在压缩包根 |
| `unzip` 提示密码错误 | 使用触发时的 `PASS`；注意 shell 引号 |
| `Expand-Archive` 打不开内层 zip | 内层有密码，改用 7-Zip：`7z x <zip> -p<PASS>` |
| 找不到 run | 稍等几秒重试 `gh run list`，并确认 `REQ` 一致 |
