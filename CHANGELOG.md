# 更新记录

## 2026-11-03 · v1.1.1

### 文档

- 新增「安装」一节：依赖、装法、环境要求、缺依赖会怎样，都按实测写；
- 新增「适用用户」一节：写明**适合**与**不适合**，避免被当成万能工具。

### 说明

- 本轮未改动本技能的判定逻辑与脚本行为；版本号仅表示文档完善，便于市场区分新旧包。

## 2026-11-03 · v1.0.1 修正失效路径 + 增加探测工具

修复（均为实测发现，非推测）：
- **推荐的 ffmpeg 路径已失效**：文档原有「用 ShadowBot 那份 ffmpeg」，
  实测 `C://Program Files\ShadowBot\shadowbot-6.3.13\ffmpeg.exe` 已不存在（软件升级后路径消失）。
  改为：先探测再使用。
- **新增 `scripts/find_ffmpeg.py`**：按 `$FFMPEG` → PATH → WorkBuddy 自带 → imageio-ffmpeg
  → 第三方兜底 的顺序探测，并对每份候选实际跑 `-version` / `-encoders` / `-filters`
  核验能力，不靠版本号猜。支持 `--json` / `--quiet` / `--require`。
- **本机 ffmpeg 能力重新实测**：WorkBuddy 自带 9.0.2 具备 libx264 + subtitles + ass + drawtext（首选）；
  剪映 21.7.0 三者皆无（不可用）；imageio-ffmpeg 9.0.2 与 WorkBuddy 同版本。
- **修正「验证」章节**：原内容是伪 shell（`ffprobe:  -i ...`），改为可直接执行的 ffprobe +
  抽帧看图两条命令，并说明「exit 0 不代表字幕真烧进去了」。
- **参考实现章节**：移除已失效的本机绝对路径，改为按文件职责说明，使用者自行搭。
- 烧字幕命令改为由探测脚本取 ffmpeg 路径，不再抄死路径。

新增：
- `README.md`
- `LICENSE`（MIT）
- `tests/test_find_ffmpeg.py`（9 项离线测试：探测解析、能力判定、定制版 ffmpeg 识别、
  候选去重、CLI 退出码）

验证：`python -m unittest discover -s tests` → 9 passed。
`python scripts/find_ffmpeg.py` 在本机正确选出 WorkBuddy 自带 9.0.2 并标出剪映版本缺 libx264。

## 初始版本

- 免端口 Remotion 渲染管线：自包含 offline.html + Chrome 一次性截图 + ffmpeg 编码。
- 记录三个必踩坑：Windows EBUSY 并发、esbuild postinstall 死锁、npm `^` 版本混杂。
- 成片后处理：本地合成音轨 + .ass 硬字幕烧录。
