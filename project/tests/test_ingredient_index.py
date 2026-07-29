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


class VagueQuantityTermTests(unittest.TestCase):
    """用模糊用量的条目也要抽出食材名。

    旧实现只认「数词+量词」，于是原书大量写成「酱油 少许」「葱段、姜块少许」的条目
    在食材索引里整条缺席——第四册的横排流水原料文尤其严重（书4 p81 油焖腐竹
    十五味料里五味用模糊用量）。模糊用量是原书的合法用量写法，与数词用量同等对待。
    """

    def test_vague_quantity_yields_the_name(self) -> None:
        self.assertEqual(_extract_terms(["酱油 少许"]), ["酱油"])
        self.assertEqual(_extract_terms(["盐 少许"]), ["盐"])
        self.assertEqual(_extract_terms(["调料：葱段、姜块少许"]), ["葱段", "姜块"])
        self.assertEqual(_extract_terms(["桃红食色素 微量"]), ["桃红食色素"])

    def test_names_sharing_one_vague_quantity_are_all_collected(self) -> None:
        # 书4 p81 油焖腐竹：原书「水木耳　水玉兰片适量」——两味料共用一个用量。
        # 名称段里的空格是原书栏间分隔，去掉就粘成「水木耳水玉兰片」再也分不开。
        self.assertEqual(_extract_terms(["水木耳 水玉兰片 适量"]), ["水木耳", "水玉兰片"])
        self.assertEqual(_extract_terms(["食盐 味精 适量"]), ["食盐", "味精"])

    def test_alignment_padding_does_not_become_single_char_terms(self) -> None:
        # 名称段里有空格时只收两字以上的词：原书为对齐把「味精」拆成「味 精」，
        # 当成两味独立食材只会造出假名字（分段器已把这种条目并成「味精 少许」）
        self.assertEqual(_extract_terms(["味 精 少许"]), [])

    def test_measure_words_outside_the_standard_table(self) -> None:
        # 「段」「厘」「头」入表后，这些条目才抽得出名字
        self.assertEqual(_extract_terms(["葱 一段"]), ["葱"])
        self.assertEqual(_extract_terms(["味精 五厘"]), ["味精"])
        self.assertEqual(_extract_terms(["蒜 两头"]), ["蒜"])
        self.assertEqual(_extract_terms(["紫菜 两小片"]), ["紫菜"])
        # 「对」故意不入表：入了表，前导用量剥离会把真食材「对虾」剥成「虾」
        self.assertEqual(_extract_terms(["对虾 四个"]), ["对虾"])
