"""ffmpeg 探测脚本的离线测试。

不依赖本机是否真的装了 ffmpeg：用 mock 模拟子进程输出，验证判定逻辑。
运行：python -m unittest discover -s tests
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "find_ffmpeg.py"

VERSION_OUT = ("ffmpeg version 9.0.2-essentials_build Copyright (c) 2000-2026 "
               "the FFmpeg developers\nbuilt with gcc\n")
ENCODER_GFUL = " V....D libx264              H.264 / AVC\n V....D libx265\n"
ENCODER_BAD = " V....D mpeg4                MPEG-4\n"
FILTER_GOOD = " .. ass               V->V  Render ASS\n T. drawtext          V->V  Draw text\n" \
              " .. subtitles         V->V  Render text\n"
FILTER_BAD = " .. scale             V->V  Scale\n"


def fake_run(stdout_map, returncode=0):
    """按 argv 最后一个参数返回不同 stdout 的 subprocess.run 替身。"""
    def _run(cmd, **kw):
        key = cmd[-1] if len(cmd) > 1 else ""
        out = stdout_map.get(key, "")
        return type("R", (), {"returncode": returncode, "stdout": out, "stderr": ""})()
    return _run


def load():
    spec = importlib.util.spec_from_file_location("find_ffmpeg", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestProbe(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_missing_file_reports_error_not_crash(self):
        info = self.m.probe(Path("__definitely_not_here__/ffmpeg.exe"))
        self.assertFalse(info["ok"])
        self.assertTrue(info["error"])

    def test_good_ffmpeg_detected(self):
        fake = fake_run({"-version": VERSION_OUT,
                         "-encoders": ENCODER_GFUL,
                         "-filters": FILTER_GOOD})
        with mock.patch("subprocess.run", fake):
            info = self.m.probe(Path("ffmpeg"))
        self.assertTrue(info["ok"], info)
        self.assertIn("9.0.2", info["version"])
        self.assertTrue(self.m.capable(info))

    def test_encoder_limited_build_is_not_capable(self):
        """剪映那种 --disable-ffmpeg 定制版：有 ass 但没 libx264 / subtitles。"""
        fake = fake_run({"-version": VERSION_OUT,
                         "-encoders": ENCODER_BAD,
                         "-filters": FILTER_BAD})
        with mock.patch("subprocess.run", fake):
            info = self.m.probe(Path("ffmpeg"))
        self.assertTrue(info["ok"])
        self.assertFalse(info["encoders_has"]["libx264"])
        self.assertFalse(self.m.capable(info))

    def test_nonzero_exit_is_not_ok(self):
        fake = fake_run({"-version": ""}, returncode=2)
        with mock.patch("subprocess.run", fake):
            info = self.m.probe(Path("ffmpeg"))
        self.assertFalse(info["ok"])
        self.assertIn("2", info["error"])

    def test_capable_requires_ok_and_all_caps(self):
        self.assertFalse(self.m.capable({"ok": False}))
        self.assertFalse(self.m.capable({"ok": True,
                                         "encoders_has": {"libx264": False},
                                         "filters_has": {"subtitles": True}}))
        self.assertTrue(self.m.capable({"ok": True,
                                        "encoders_has": {"libx264": True},
                                        "filters_has": {"subtitles": True,
                                                        "ass": True,
                                                        "drawtext": True}}))


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_env_var_is_first_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "my-ffmpeg")
            with mock.patch.dict(os.environ, {"FFMPEG": target}):
                got = list(self.m._candidates())
            self.assertEqual(str(got[0]), target)

    def test_no_duplicates(self):
        cands = [str(c).lower() for c in self.m._candidates()]
        self.assertEqual(len(cands), len(set(cands)), "候选出现重复：" + str(cands))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def _run(self, argv):
        with mock.patch.object(sys, "argv", ["find_ffmpeg.py"] + argv):
            return self.m.main()

    def test_json_output_shape(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self._run(["--json"])
        data = json.loads(buf.getvalue())
        self.assertIn("chosen", data)
        self.assertIn("candidates", data)
        self.assertIsInstance(data["candidates"], list)
        self.assertIn(rc, (0, 1))

    def test_nothing_found_exits_1(self):
        buf = io.StringIO()
        with mock.patch.object(self.m, "_candidates", lambda: iter([])):
            with redirect_stdout(buf):
                rc = self._run(["--quiet"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
