"""提示词引用规则的回归测试。运行：python -m unittest discover -s tests

覆盖 2026-10-15 同事测试时发现的问题（正文漏括号没被拦住），以及容易误判的写法。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xuanshang_canvas.core.rules import canvas_view, check_prompt, find_format_problems, normalize_prompt  # noqa: E402


class BareReferenceTests(unittest.TestCase):
    def test_declared_ok_but_body_missing_parentheses(self):
        """同事的最小复现：声明区合法，正文「背景采用图片2，与图片1保持一致」漏了括号。"""
        result = check_prompt("(图片1) 是人物大头照。\n(图片2) 是场景。\n背景采用图片2，与图片1保持一致。", {"image": 2})
        self.assertEqual(len(result.format_problems), 2)
        self.assertIn("第 3 行", result.format_problems[0])
        self.assertIn("【图片2】", result.format_problems[0])
        self.assertIn("(图片2)", result.format_problems[0])
        self.assertEqual(result.problems, [])  # 声明区已经引用齐，覆盖检查本身是通过的
        self.assertIn("背景采用图片2", result.prompt)  # 裸编号不自动改，交给写提示词的一方确认

    def test_elided_after_reference(self):
        result = check_prompt("(图片1)(图片2)(图片3)(图片4)(图片5)(图片6)(图片7)、8定义的男性司徒陌", {"image": 8})
        self.assertEqual(len(result.format_problems), 1)
        self.assertIn("(图片7)、(图片8)", result.format_problems[0])

    def test_bare_elided(self):
        result = check_prompt("(图片1)(图片2)(图片3)(图片4)(图片5)(图片6)图片7、8定义的男性司徒陌", {"image": 8})
        self.assertEqual(len(result.format_problems), 1)
        self.assertIn("(图片7)、(图片8)", result.format_problems[0])

    def test_ranges(self):
        for prompt in ("人物见图片1—8", "人物见图片1-8", "(图片1)—(图片8)", "(图片1)~8"):
            with self.subTest(prompt=prompt):
                problems = find_format_problems(normalize_prompt(prompt)[0])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("范围写法", problems[0])

    def test_walk_to_is_not_a_range(self):
        self.assertEqual(check_prompt("从(图片1)走到(图片2)", {"image": 2}).format_problems, [])

    def test_out_of_range_number(self):
        result = check_prompt("(图片3)", {"image": 2})
        self.assertTrue(any("只接入了 2 个图片" in p for p in result.problems))

    def test_duration_is_flagged_not_converted(self):
        """「参考视频27秒」不能机械改成「参考(视频27)秒」，只提示换个说法。"""
        result = check_prompt("(图片1)，参考视频27秒，(视频1)运镜", {"image": 1, "video": 1})
        self.assertEqual(len(result.format_problems), 1)
        self.assertIn("时长", result.format_problems[0])
        self.assertIn("参考视频27秒", result.prompt)

    def test_duration_rephrased_is_clean(self):
        result = check_prompt("(图片1)，参考视频时长为27秒，(视频1)运镜，(背景播放舒缓的钢琴乐)", {"image": 1, "video": 1})
        self.assertEqual(result.format_problems, [])
        self.assertEqual(result.problems, [])
        self.assertEqual(result.reference_count, 2)

    def test_file_names_and_shot_numbers(self):
        result = check_prompt("(图片1)参考 16-21-段2-镜134.mp4 的走位，镜127 接 镜128", {"image": 1})
        self.assertEqual(result.format_problems, [])

    def test_fenbie_is_not_a_unit(self):
        """真实数据里的「图片7分别补充」：漏括号，但「分」不是时长单位。"""
        problems = find_format_problems("(图片6)、图片7分别补充其画右、画左近处书架")
        self.assertEqual(len(problems), 1)
        self.assertIn("没有括号", problems[0])
        self.assertNotIn("时长", problems[0])

    def test_unsupported_brackets(self):
        result = check_prompt("(图片1) <图片1> 背景", {"image": 1})
        self.assertEqual(len(result.format_problems), 1)


class NormalizeTests(unittest.TestCase):
    def test_converts_recognized_forms_to_half_width(self):
        text, converted = normalize_prompt("@图片1 和（图片2）、（@图片3）以及【视频1】和 @视频 2")
        self.assertEqual(text, "(图片1) 和(图片2)、(图片3)以及(视频1)和 (视频2)")
        self.assertEqual(len(converted), 5)

    def test_idempotent(self):
        once, _ = normalize_prompt("@图片1 和（图片2）")
        twice, converted = normalize_prompt(once)
        self.assertEqual(once, twice)
        self.assertEqual(converted, [])

    def test_canvas_view_keeps_at_refs_as_problems(self):
        """提交前按画布的规则看：@图片1 画布不认，要报出来。"""
        problems = find_format_problems(canvas_view("@图片1 站在（图片2）前面"))
        self.assertEqual(len(problems), 1)
        self.assertIn("图片1", problems[0])


if __name__ == "__main__":
    unittest.main()
