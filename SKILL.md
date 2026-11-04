---
name: offline-remotion-render
slug: zhengrong-offline-remotion-render
displayName: "本地离线视频渲染"
summary: "本机端口被阻断时用免端口方案逐帧渲染 Remotion 并编码成片，另附音轨合成与硬字幕烧录。"
description: 在本机（Windows + Clash TUN，TCP 回环被阻断）用免端口方案渲染 Remotion 视频，并给出成片后处理（离线合成音轨 + ffmpeg 烧录硬字幕）。Remotion 官方 render/still 依赖 Chrome DevTools Protocol 端口，在此环境 100% 失败，本技能给出可实际出片的替代管线：自包含 offline.html + Chrome 一次性 --screenshot 逐帧 + ffmpeg 编码。触发词：Remotion 渲染失败、ErrorEvent、Bundling 24% 崩溃、#<ErrorEvent>、CDP 连不上、remotion 出不了片、逐帧渲染、免端口渲染、offline.html、视频没声音、没字幕、加音轨、加硬字幕、烧录字幕、BGM。
display_name: "本地离线视频渲染"
agent_created: true
version: 1.1.1
license: MIT
updated: "2026-11-03"

---
# 免端口 Remotion 渲染（本机专用）

## 何时用

- Remotion `render` 或 `still` 报 `UnhandledPromiseRejection: reason "#<ErrorEvent>"`
- 崩溃点停在 `Bundling 24%` 附近（**这是假象，真因见下**）
- 老板要求「现在就出片」，不能只交代码 + 脚本

## 根因（本机环境事实）

Clash TUN 劫持全部出站流量，**TCP 回环彻底不可用**：

```
net.bind('127.0.0.1') 后自己 connect 自己  → ETIMEDOUT
Chrome 打印 DevTools listening on ws://127.0.0.1:9333/...
Node 连 127.0.0.1:9333                     → ECONNREFUSED
```

`dangerouslyDisableSandbox: true` 也**没用**（是系统层 TUN，不是沙箱）。

Remotion 的 `render` 和 `still` **都**必须走 CDP 端口 → 必然失败。

### 排查陷阱（别重复踩）

`Bundling 24%` 这类进度行是**并行任务的输出**，崩溃真点在 `openBrowser()`。
我曾因此白查了 esbuild 版本、`NODE_OPTIONS`、safe-delete shim，全是错方向。

**正确做法：直接加 `--log=verbose` 看输出最后 10 行**，一眼定位：

```
openBrowser()  Opening browser: gl = null, executable = ...
← 崩在这里，后面才是那个没信息量的 ErrorEvent
```

最强诊断信号：`remotion bundle` 单独跑能 100% 成功，但 `remotion render` 必挂
—— 差异（后者 spawn Chrome worker）本身就证明是环境问题，不是代码问题。

## 方案：绕开 CDP，走 Chrome 一次性截图

Chrome 的 `--screenshot` 模式**完全不需要任何端口**：启动 → 渲染 → 截图 → 退出。

### 三步管线

```
1. esbuild 打自包含 offline.html（JS 内联 + 字体 base64 内联）
2. 循环 1800 次：chrome --screenshot=out.png --window-size=W,H "file:///...offline.html?frame=N"
3. ffmpeg -framerate 30 -i frames/f%04d.png -c:v libx264 -crf 20 -pix_fmt yuv420p out.mp4
```

关键点：
- **字体内联 base64**（`FontFace` + `data:font/ttf;base64,`）—— `file://` 下无法 `fetch` 本地 ttf
- **页面用 `@remotion/player` 的 `initialFrame={frame}` 按 URL 参数渲染单帧**，不经过 CDP
- `--virtual-time-budget=2500` 给字体和 React 渲染留时间
- **断点续传**：`if (fs.existsSync(out)) skip` —— 中断后重跑只补缺的帧

## 三个必踩的坑

### 1. Windows EBUSY：并发 spawn 同一个 exe 会全盘失败

```
spawnSync ...\chrome-headless-shell.exe EBUSY
```

- 实测**并发 6 → 1800 帧全部失败**；**并发 2 或串行 → 稳定**
- 必须加指数退避重试（250/500/1000ms）
- `os.cpus().length` 别拿来算并发，Windows 文件锁才是瓶颈

**更重要的是：不要用 Node 并发池 + 忙等退避。**
实测 `render_all.js` 那种写法在 EBUSY 退避时两个 worker 一起空转，
**磁盘上一帧都不落**，看起来像卡死。**改成 bash 串行 for 循环 + `sleep 1` 重试**
（`render_serial.sh`）后 100% 稳定 —— bash 每帧都是独立进程，退出码可靠。

### 2. `npm install` 装 esbuild 同样 EBUSY 死锁

- 报错栈在 esbuild `install.js` → `validateBinaryVersion()`
- postinstall 要 spawn 正在运行的 node.exe，Windows 锁死
- **重试永远过不去**，解法：`npm install --ignore-scripts`
  （`@esbuild/win32-x64` 包内已有二进制，postinstall 只是校验）

### 3. npm 会把版本号改成 `^` 导致版本混杂

- 装完 409/532 混装 → 渲染崩
- `package.json` 版本**必须钉死不带 `^`**
- 验证：`for d in node_modules/@remotion/*; do node -e "console.log(require('./$d/package.json').version)"; done | sort -u`
  **只应输出一个版本号**

## 性能实测（本机 16 核）

| 阶段 | 实测 |
|---|---|
| 单帧 Chrome 截图 | **2.0-2.6 秒**（进程启动为主开销） |
| `--virtual-time-budget` | 400 / 800 / 1500 **产物字节数完全相同** → 调它没用，瓶颈是进程启动 |
| 1800 帧串行 | 约 **60-70 分钟** |
| ffmpeg 编码 1080×1920 | 约 1-2 分钟 |

**结论：不要为提速去调 budget 或加并发**，两者都无效。60 分钟就是成本，接受它。
若确实要快，只能降帧率（如 24fps → 1440 帧，省 20%）或降分辨率。

## ffmpeg 在哪里

系统 PATH 里通常没有 ffmpeg。**先跑探测脚本，不要凭记忆写路径**：

```bash
python scripts/find_ffmpeg.py            # 列出所有候选 + 能力判定
python scripts/find_ffmpeg.py --json     # 机读
python scripts/find_ffmpeg.py --require libx264,subtitles   # 只认满足要求的
```

探测顺序（脚本自动做）：环境变量 `FFMPEG` → PATH → WorkBuddy 自带 → imageio-ffmpeg 自带
→ 常见第三方软件目录（剪映 / ShadowBot 等，仅作兜底）。

### 本机实测结论（2026-11-03 复核）

| 来源 | 版本 | libx264 | subtitles/libass | 结论 |
|---|---|---|---|---|
| WorkBuddy 自带 `~/.workbuddy/binaries/ffmpeg/bin/ffmpeg.exe` | 9.0.2 | ✅ | ✅ | **首选，能力齐全** |
| imageio-ffmpeg（`pip install imageio-ffmpeg`） | 9.0.2 | ✅ | ✅ | 次选，跨平台稳定 |
| 剪映 `~\AppData\Local\JianyingPro\Apps\*\ffmpeg.exe` | 21.7.0 | ❌ | — | **不能用**，定制版禁用编码器 |
| ShadowBot `C:\Program Files\ShadowBot\shadowbot-*\ffmpeg.exe` | 3.0.1 | 曾可用 | 曾可用 | ⚠️ 本机已不存在，旧文档中的该路径**已失效** |

> 历史教训：这份文档曾写死「用 ShadowBot 那份 ffmpeg」，结果 ShadowBot 升级后路径消失，
> 命令直接 404。**凡外部软件路径一律走探测脚本，不写死。**

调用时注意 git-bash 路径转换（路径含空格必须加引号 + 关掉路径转换）：

```bash
MSYS_NO_PATHCONV=1 "$HOME/.workbuddy/binaries/ffmpeg/bin/ffmpeg.exe" -version
```

## 成片后处理：给已渲染 MP4 补「声音 + 硬字幕」

老板常反馈「没声音没字幕」。**不要重渲 1800 帧** —— 直接在成片 MP4 上做 ffmpeg
后处理，几十秒出片。（触发词：视频没声音、没字幕、加音轨、加硬字幕）

### 1. 音轨：本地合成（零联网）

`tools/make_audio.py`（本机 numpy 2.5.3 可用，无需 pip 安装）：

- 氛围 pad（A 小调 + 微失谐展宽 + shimmer）+ 100BPM 软底鼓 + 离拍 hat
- 场景切换时刻（如 5/14/25/38/49s）插入 440→880Hz 上行 blip 音效
- `np.tanh` 软削波 → 归一化 → 淡入淡出 → 写 16-bit PCM WAV → ffmpeg 转 AAC

⚠️ **离线中文配音在本机不可行**：WorkBuddy 的 PowerShell 策略**同时拦截
`Add-Type` 与 `New-Object -ComObject`**（报错 "COM object instantiation can run
arbitrary code"），`SAPI.SpVoice` 调不动 → Windows 原生 TTS 用不了。
需要真人/AI 配音只能另找在线 TTS API 或本地模型，默认交付 **BGM + 音效**。

### 2. 硬字幕：`.ass` + libass

写 `.ass`（关键字段）：

```
PlayResX: 1080      PlayResY: 1920
Style: Default,Noto Sans SC,50,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,4,0,2,90,90,150,1
```
解读：Alignment=2 底部居中；MarginV=150 距底；Outline=4 黑描边；Bold=1；
`Noto Sans SC` 由 `fontsdir` 提供（项目 `public/fonts/NotoSansSC-*.ttf`）。

### 3. 一条命令烧字幕 + 封装音频

```bash
# 用探测脚本取路径，不要抄死路径
FF="$(python scripts/find_ffmpeg.py --quiet --require libx264,subtitles)"
[ -n "$FF" ] || { echo "没有可用 ffmpeg，先 pip install imageio-ffmpeg"; exit 1; }

MSYS_NO_PATHCONV=1 "$FF" -y \
  -i openclaw-video/output/openclaw-intro.mp4 \
  -i openclaw-video/output/track.wav \
  -filter_complex "[0:v]subtitles=openclaw-video/output/subtitles.ass:fontsdir=openclaw-video/public/fonts[v]" \
  -map "[v]" -map 1:a \
  -c:v libx264 -preset medium -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart \
  openclaw-video/output/openclaw-intro-final.mp4
```

**坑（必踩）**：Windows 盘符 `:` 会炸 filtergraph。**在 bash 里用相对路径**
（cwd=workspace 根，无盘符即无冒号）比 `C\:` 转义稳得多。
旧版 ffmpeg（ShadowBot v3.0.1）**已内置** `subtitles`/`ass`/`drawtext` 滤镜与
`aac` 编码器，足够用 —— 先 `ffmpeg -filters | grep -iE "subtitles|drawtext"` 确认。

### 4. 验证（必做，别只信 exit 0）

```bash
# 1) 音轨是否真的在
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,channels \
        -of default=nw=1 final.mp4
# 期望看到 codec_name=aac / channels=2

# 2) 中文字幕是否真的烧进去了（抽一帧看图，不靠猜）
ffmpeg -y -ss 6 -i final.mp4 -frames:v 1 chk.png
# 然后用 Read 打开 chk.png，肉眼确认字形正常、位置没压到底边
```

> 字幕烧录最常见的失败是**静默无字幕**：exit 0 但滤镜没生效（路径含盘符冒号、
> 字体文件没找到）。所以必须抽帧看图。

## 参考实现（照这个结构自己搭）

原实现是某次真实出片项目，路径已不随包分发。要复现就在你的 Remotion 项目里按下面 5 个文件搭：

| 文件 | 职责 | 关键点 |
|---|---|---|
| `render_serial.sh` | **推荐入口** | bash 串行 + EBUSY 重试 + 断点续传 + 最后调 ffmpeg 编码 |
| `build_offline.js` | esbuild 打包 | 把 JS 内联、字体 base64 内联，产出单文件 `offline.html` |
| `render_all.js` | Node 并发池版 | **有卡死问题，别用**（留作反例） |
| `src/fonts.offline.ts` | 字体注入 | `FontFace` + `data:font/ttf;base64,`，区别于正常渲染用的 `fonts.ts` |
| `src/OfflineFrame.tsx` | 单帧渲染 | `@remotion/player` + `initialFrame={frame}`，帧号从 URL 参数读 |

成片后处理：

| 文件 | 职责 |
|---|---|
| `tools/make_audio.py` | 本地合成 BGM + 场景切换音效 → `track.wav`（numpy，零联网） |
| `output/subtitles.ass` | 中文硬字幕时间轴（Noto Sans SC / 底部居中） |

**排查帧是否在正常产出**（避免又卡住）：

```bash
sleep 60; ls frames/f*.png | wc -l
# 若 60 秒后仍是 0，说明进程卡死 → 停掉换串行脚本
```

## 环境变量

渲染命令一律加（`NODE_OPTIONS` 会注入 WorkBuddy shim 到子进程）：

```bash
env -u NODE_OPTIONS -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY \
    -u https_proxy -u http_proxy -u all_proxy node render_all.js
```

## 性能预期

- 单帧 Chrome 启动约 0.5-2s
- 并发 2 → 1800 帧（60 秒视频）约 **20-40 分钟**
- ffmpeg 编码 1080×1920 约 1-2 分钟
- 中断可随时重跑续传
