# 本地离线视频渲染（offline-remotion-render）

> **Remotion 官方 `render` / `still` 在「TCP 回环不可用」的机器上 100% 失败。**
> 这个技能给出一条能真正出片的替代管线：自包含 `offline.html` + Chrome 一次性 `--screenshot`
> 逐帧 + ffmpeg 编码。附带成片后处理（补音轨 + 烧硬字幕）。

---

## 一、什么时候用

- `remotion render` / `still` 报 `UnhandledPromiseRejection: reason "#<ErrorEvent>"`
- 崩溃点停在 `Bundling 24%` 附近 —— **这是假象，真因在 `openBrowser()`**
- 机器开了全局代理 TUN（Clash / Mihomo 等），`127.0.0.1` 自连不通
- 老板要「现在就出片」，不接受只交代码

---

## 二、根因（一句话）

```
Clash TUN 劫持全部出站流量 → net.bind('127.0.0.1') 后自己 connect 自己 → ETIMEDOUT
Chrome 打印 DevTools listening on ws://127.0.0.1:9333/...  → Node 连它 → ECONNREFUSED
```

Remotion 的 `render` 和 `still` **都**必须走 Chrome DevTools Protocol 端口，所以必然失败。
`dangerouslyDisableSandbox: true` 也没用——是系统层 TUN，不是沙箱。

**诊断捷径**：`remotion bundle` 单独跑能 100% 成功，但 `remotion render` 必挂。
这个差异本身就证明是环境问题，不是你的代码问题。

---

## 三、替代管线

```
1. esbuild 打自包含 offline.html（JS 内联 + 字体 base64 内联）
2. 循环 N 次：chrome --screenshot=out.png --window-size=W,H "file:///...offline.html?frame=N"
3. ffmpeg -framerate 30 -i frames/f%04d.png -c:v libx264 -crf 20 -pix_fmt yuv420p out.mp4
```

关键点：

- **字体内联 base64** —— `file://` 下 `fetch` 不到本地 ttf
- 页面用 `@remotion/player` 的 `initialFrame={frame}` 按 URL 参数渲染单帧，不经过 CDP
- `--virtual-time-budget=2500` 给字体和 React 留时间（但实测调大无收益，见性能表）
- **断点续传**：`if (fs.existsSync(out)) skip` —— 中断后重跑只补缺帧

---

## 四、三个必踩的坑

| 坑 | 现象 | 解法 |
|---|---|---|
| Windows EBUSY | 并发 spawn 同一 exe → `EBUSY`，**并发 6 时 1800 帧全失败** | 并发 ≤2 或直接串行；加指数退避。**别用 Node 并发池 + 忙等**，会两 worker 一起空转、一帧不落 |
| esbuild 装不上 | `npm install` 卡在 `validateBinaryVersion()` | `npm install --ignore-scripts`（二进制已在包内，postinstall 只是校验） |
| 版本混杂 | 装完 409/532 混装 → 渲染崩 | `package.json` 版本**钉死不带 `^`**；用 `sort -u` 验证只剩一个版本号 |

---

## 五、性能实测（16 核）

| 阶段 | 实测 |
|---|---|
| 单帧 Chrome 截图 | 2.0–2.6 秒（进程启动是主要开销） |
| `--virtual-time-budget` 400 / 800 / 1500 | **产物字节数完全相同** → 调它没用 |
| 1800 帧串行 | 约 60–70 分钟 |
| ffmpeg 编码 1080×1920 | 约 1–2 分钟 |

**结论：不要为提速去调 budget 或加并发，两者都无效。** 要快只能降帧率或降分辨率。

---

## 六、工具：`scripts/find_ffmpeg.py`

外部软件路径会变（曾经写死的 ShadowBot 路径某次升级后就消失了）。所以路径一律探测：

```bash
python scripts/find_ffmpeg.py                                   # 人读：候选 + 能力
python scripts/find_ffmpeg.py --json                            # 机读
python scripts/find_ffmpeg.py --quiet --require libx264,subtitles   # 只输出合格路径
```

探测顺序：`$FFMPEG` → PATH → WorkBuddy 自带 → imageio-ffmpeg → 剪映 / ShadowBot 兜底。
每份候选都会实际跑 `-version` / `-encoders` / `-filters` 核验能力，**不靠版本号猜**。

本机 2026-11-03 实测：

| 来源 | 版本 | libx264 | subtitles | 可用 |
|---|---|---|---|---|
| WorkBuddy 自带 | 9.0.2 | ✅ | ✅ | **首选** |
| imageio-ffmpeg | 9.0.2 | ✅ | ✅ | 次选 |
| 剪映 | 21.7.0 | ❌ | ❌ | 不可用（定制版禁了编码器） |

---

## 七、成片后处理：补声音 + 硬字幕

**不要重渲 1800 帧**，直接在成片 MP4 上做 ffmpeg 后处理，几十秒出片。

- **音轨**：`tools/make_audio.py` 本地合成 BGM + 场景切换音效（numpy，零联网）
- **硬字幕**：`.ass` + libass，`Noto Sans SC`，底部居中，`MarginV=150`，`Outline=4`
- **必做验证**：`ffprobe` 确认有 aac 音轨；**抽一帧看图**确认中文字形与位置。
  exit 0 不代表字幕真的烧进去了。

> ⚠️ 离线中文配音在 WorkBuddy 环境下不可行：PowerShell 策略同时拦截 `Add-Type` 与
> `New-Object -ComObject`，`SAPI.SpVoice` 调不动。默认交付 BGM + 音效；要人声请用
> `shortvideo-pipeline` 或在线 TTS。

---

## 八、测试

```bash
python -m unittest discover -s tests -v
```

9 项，全部离线：探测逻辑、能力判定、编码器受限版本识别、候选去重、CLI 退出码。

---

## 九、已知边界

- 这是**诊断 + 管线 knowledge 型技能**，不含可直接跑的完整渲染器；参考实现需按
  `SKILL.md` 的 5 个文件结构自己在项目里搭。
- 串行 1800 帧 = 1 小时左右，这是硬件与 Windows 文件锁的现实成本，不是能优化掉的。
- 只解决「出不了片」，不解决排版/设计质量问题。

## 十、许可证

MIT，见 `LICENSE`。

## 运行环境

| 项 | 状态 |
|---|---|
| Windows 11 + Python 3.12 / 3.13 | ✅ 实测通过 |
| Linux（含 WSL） | ⚠️ **未实测**。代码用 `pathlib`，没有硬编码分隔符，理论上可跑；但测试只在 Windows 跑过，不声称支持 |
| macOS | ⚠️ 未实测 |

诚实标注：不要在没有实跑过的平台上对外声称「已支持」。
