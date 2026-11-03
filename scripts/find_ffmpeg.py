#!/usr/bin/env python
"""定位一个「真能用」的 ffmpeg，并核验它是否具备所需能力。

为什么需要这个脚本：曾经把外部软件（ShadowBot）的 ffmpeg 绝对路径写死在文档里，
该软件升级后路径消失，命令直接失败。外部工具路径必须探测，不能写死。

用法:
  python scripts/find_ffmpeg.py                     # 人读：列出候选 + 能力
  python scripts/find_ffmpeg.py --json              # 机读
  python scripts/find_ffmpeg.py --require libx264   # 只接受具备该能力的
  python scripts/find_ffmpeg.py --require libx264,subtitles --quiet

退出码: 0=找到合格 ffmpeg, 1=未找到, 2=参数错误
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_ENCODERS = ("libx264",)
REQUIRED_FILTERS = ("subtitles", "ass", "drawtext")


def _candidates():
    """按优先级产出候选 ffmpeg 路径。"""
    seen = set()

    def push(p):
        if not p:
            return
        try:
            rp = Path(p).expanduser()
        except Exception:
            return
        key = str(rp).lower()
        if key in seen:
            return
        seen.add(key)
        yield rp

    env = os.environ.get("FFMPEG")
    if env:
        yield from push(env)

    on_path = shutil.which("ffmpeg")
    if on_path:
        yield from push(on_path)

    home = Path.home()
    # WorkBuddy / CodeBuddy 自带
    for base in (".workbuddy", ".codebuddy"):
        yield from push(home / base / "binaries" / "ffmpeg" / "bin" / "ffmpeg.exe")
        yield from push(home / base / "binaries" / "ffmpeg" / "bin" / "ffmpeg")
    # imageio-ffmpeg 自带
    try:
        import imageio_ffmpeg
        yield from push(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    # 第三方软件兜底（不可依赖，仅作最后手段）
    jy = sorted((home / "AppData" / "Local" / "JianyingPro" / "Apps").glob("*/ffmpeg.exe"))
    for p in reversed(jy):
        yield from push(p)
    for p in sorted(Path("C:/Program Files/ShadowBot").glob("shadowbot-*/ffmpeg.exe")):
        yield from push(p)


def probe(path: Path, timeout: int = 20) -> dict:
    """返回 {ok, version, encoders_has, filters_has, error}。"""
    info = {"path": str(path), "ok": False, "version": "", "error": ""}
    try:
        v = subprocess.run([str(path), "-version"], capture_output=True,
                           timeout=timeout, text=True, errors="replace")
        if v.returncode != 0:
            info["error"] = "ffmpeg -version 退出码 %d" % v.returncode
            return info
        head = (v.stdout or "").splitlines()
        info["version"] = head[0].strip() if head else ""

        enc = subprocess.run([str(path), "-hide_banner", "-encoders"],
                             capture_output=True, timeout=timeout, text=True, errors="replace")
        flt = subprocess.run([str(path), "-hide_banner", "-filters"],
                             capture_output=True, timeout=timeout, text=True, errors="replace")
        info["encoders_has"] = {e: (e in (enc.stdout or "")) for e in REQUIRED_ENCODERS}
        info["filters_has"] = {f: (f in (flt.stdout or "")) for f in REQUIRED_FILTERS}
        info["ok"] = True
    except FileNotFoundError:
        info["error"] = "文件不存在"
    except subprocess.TimeoutExpired:
        info["error"] = "探测超时"
    except Exception as ex:  # noqa: BLE001 - 探测失败不应中断整体流程
        info["error"] = str(ex)
    return info


def capable(info: dict) -> bool:
    if not info.get("ok"):
        return False
    return all(info.get("encoders_has", {}).values()) and all(info.get("filters_has", {}).values())


def main():
    ap = argparse.ArgumentParser(description="定位并核验可用的 ffmpeg")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--require", default="", help="逗号分隔的必需能力：libx264,subtitles,ass,drawtext")
    ap.add_argument("--quiet", action="store_true", help="只输出选中路径")
    a = ap.parse_args()

    need = [x.strip() for x in a.require.split(",") if x.strip()]
    results = []
    for c in _candidates():
        if not c.is_file():
            continue
        results.append(probe(c))

    def meets(info):
        if not info.get("ok"):
            return False
        caps = {}
        caps.update(info.get("encoders_has", {}))
        caps.update(info.get("filters_has", {}))
        return all(caps.get(n, False) for n in need) if need else capable(info)

    chosen = next((r for r in results if meets(r)), None)

    if a.json:
        print(json.dumps({"chosen": chosen["path"] if chosen else None,
                          "require": need, "candidates": results},
                         ensure_ascii=False, indent=2))
    elif a.quiet:
        if chosen:
            print(chosen["path"])
    else:
        if not results:
            print("未找到任何 ffmpeg 候选。安装方式：pip install imageio-ffmpeg")
        for r in results:
            caps = []
            for k, v in (r.get("encoders_has") or {}).items():
                caps.append(("✓" if v else "✗") + k)
            for k, v in (r.get("filters_has") or {}).items():
                caps.append(("✓" if v else "✗") + k)
            mark = "★" if r is chosen else (" " if r.get("ok") else "!")
            print("%s %s" % (mark, r["path"]))
            if r.get("version"):
                print("    %s" % r["version"])
            if r.get("error"):
                print("    错误: %s" % r["error"])
            if caps:
                print("    能力: %s" % " ".join(caps))
        print()
        if chosen:
            print("建议使用: %s" % chosen["path"])
        else:
            print("没有满足要求的 ffmpeg（要求: %s）。" % (",".join(need) or "libx264+subtitles"))
            print("修复: pip install imageio-ffmpeg")

    return 0 if chosen else 1


if __name__ == "__main__":
    sys.exit(main())
