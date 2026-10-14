import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cases import dedupe, elapsed_days, validate  # noqa: E402
from common import canonical_url, parse_post_url  # noqa: E402
from fetch_posts import extract  # noqa: E402
from summarize import REV_COARSE, reversal_table, build, stats, wilson  # noqa: E402


def case(**kw):
    base = {"url": "https://m.blog.naver.com/a/1", "case_id": "a_1", "embryo_day": "5", "transfer_type": "동결",
            "count_basis": "date", "test_d13": "", "test_d14": "역전", "test_d15": "", "outcome": "미확인",
            "twins": "", "followup_url": ""}
    base.update(kw)
    return base


class T(unittest.TestCase):
    def test_wilson(self):
        lo, hi = wilson(8, 10)
        self.assertAlmostEqual(lo, 0.4902, places=3)
        self.assertAlmostEqual(hi, 0.9433, places=3)

    def test_elapsed(self):
        # 이식일 포함 15일차 = 이식일 + 14일
        self.assertEqual(elapsed_days("2026-03-01", "2026-03-15"), 14)
        self.assertEqual(elapsed_days(blogger_day=15, basis="one"), 14)
        self.assertEqual(elapsed_days(blogger_day=14, basis="zero"), 14)
        self.assertIsNone(elapsed_days(blogger_day=14, basis="불명"))

    def test_url(self):
        self.assertEqual(parse_post_url("https://blog.naver.com/abc_1/223456789"), ("abc_1", "223456789"))
        self.assertEqual(parse_post_url("https://blog.naver.com/PostView.naver?blogId=xy&logNo=12"), ("xy", "12"))
        self.assertIsNone(parse_post_url("https://foo.tistory.com/12"))
        self.assertEqual(canonical_url("a", "1"), "https://m.blog.naver.com/a/1")

    def test_stats_excludes_unknown(self):
        rows = [case(outcome="심장소리확인", followup_url="x")] * 3 + [case(outcome="화학적유산", followup_url="x"),
                                                                     case(outcome="미확인")]
        s = stats(rows)
        self.assertEqual((s["hb"], s["n"], s["unk"]), (3, 4, 1))
        self.assertAlmostEqual(s["rate"], 0.75)

    def test_validate_and_dedupe(self):
        self.assertTrue(validate([case(test_d14="진함")]))
        self.assertTrue(validate([case(outcome="심장소리확인")]))  # followup_url 누락
        merged = dedupe([case(hcg=""), case(hcg="2026-03-10:300(d9)")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["hcg"], "2026-03-10:300(d9)")

    def test_reversal_day(self):
        self.assertTrue(validate([case(reversal_day="14일")]))
        self.assertFalse(validate([case(reversal_day="미관찰")]))
        t = reversal_table([case(reversal_day="14", outcome="심장소리확인", followup_url="x"),
                            case(case_id="b", reversal_day="19", outcome="화학적유산", followup_url="x")], REV_COARSE)
        self.assertIn("| 경과 14~15일 | 1 | 1 |", t)
        self.assertIn("| 경과 18일 이후 | 1 | 0 |", t)

    def test_build_runs(self):
        md = build([case(outcome="심장소리확인", followup_url="x"), case(case_id="b", test_d14="동일진하기")])
        self.assertIn("100.0%", md)

    def test_extract(self):
        html = ('<div class="se-title-text">제목</div><span class="blog_date">2026. 3. 15. 9:00</span>'
                '<div class="se-main-container"><div class="se-component se-text"><p>이식 14일차</p></div>'
                '<div class="se-component se-image"><img alt="임테기"><p class="se-caption">대조선보다 진함</p></div></div>')
        p = extract(html)
        self.assertEqual(p["title"], "제목")
        self.assertIn(("caption", "대조선보다 진함"), p["blocks"])
        self.assertIn(("text", "이식 14일차"), p["blocks"])


if __name__ == "__main__":
    unittest.main()
