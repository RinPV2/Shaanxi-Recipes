from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.obsidian_exporter import _extract_terms


class IngredientIndexTests(unittest.TestCase):
    """食材索引从「名称 用量」条目取名字，括号注按行剥掉后名称尾巴要收拾干净。"""

    def test_paren_note_does_not_leak_into_the_term(self) -> None:
        self.assertEqual(_extract_terms(["主料：去皮肥瘦猪肉（臀尖肉） 四两"]), ["去皮肥瘦猪肉"])

    def test_measure_qualifier_left_by_paren_note_is_stripped(self) -> None:
        # 「活鲤鱼（一条）约 二斤」剥掉括号注后是「活鲤鱼约」，
        # 不收拾就与别处的「活鲤鱼」在索引里分裂成两条
        self.assertEqual(_extract_terms(["主料：活鲤鱼（一条）约 二斤"]), ["活鲤鱼"])
        self.assertEqual(_extract_terms(["主料：甲鱼重（2-3斤） 一个"]), ["甲鱼"])
        self.assertEqual(_extract_terms(["主料：肥母鸡 一只（重约二斤半）"]), ["肥母鸡"])

    def test_single_char_remainder_keeps_its_qualifier(self) -> None:
        # 「蒸约」「煮约」是误入原料区的制法碎片；剥成「蒸」「煮」反而更像食材条目
        self.assertEqual(_extract_terms(["蒸约 二十分"]), ["蒸约"])
        self.assertEqual(_extract_terms(["煮约 十分"]), ["煮约"])
