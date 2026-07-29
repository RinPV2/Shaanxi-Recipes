from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shanxi_pipeline.config import load_yaml
from shanxi_pipeline.review_priority import apply_text_replacements, compile_text_replacements

CONFIG = Path(__file__).resolve().parents[1] / "config" / "cleaning_rules.yaml"


class CleaningRuleTests(unittest.TestCase):
    """扫描杂点类清洗规则的回归。

    这些规则是全库无条件生效的正则,所以负例（不该动的地方）比正例更重要:
    每一条负例都对应页图上真实存在的一处正常用法。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.replacements = compile_text_replacements(load_yaml(CONFIG))

    def clean(self, text: str) -> str:
        return apply_text_replacements(text, self.replacements)

    def test_stray_dot_between_two_hanzi_is_removed(self) -> None:
        # 不剥的话原料配对会把「面-粉 五钱」切成「粉 五钱」+ 孤立的「面」
        self.assertEqual("熟猪油 一两 湿淀粉 三钱", self.clean("熟猪.油 一两 湿淀粉 三钱"))
        self.assertEqual("花椒三钱 面粉 五钱", self.clean("花椒三钱 面-粉 五钱"))
        self.assertEqual("食盐 四两 花椒 三钱", self.clean("食.盐 四两 花椒 三钱"))

    def test_sentence_punctuation_after_a_measure_word_is_kept(self) -> None:
        # 书1 p20:页图上「另加油半两，先下葱花」印的是逗号,剥掉会把两句粘成一句。
        self.assertIn("半两.先", self.clean("炒勺内另加油半两.先下葱花炝过"))

    def test_dot_between_digits_and_step_enumerators_are_kept(self) -> None:
        self.assertEqual("1. 烧肉切成一寸半长", self.clean("1. 烧肉切成一寸半长"))
        self.assertEqual("35°-38°温水", self.clean("35°-38°温水"))
        self.assertEqual("重（2-3斤）一个", self.clean("重（2-3斤）一个"))

    def test_interpunct_is_only_stripped_before_a_number(self) -> None:
        self.assertEqual("配料：肥瘦生猪肉一 斤", self.clean("配料：肥瘦生猪肉·一 斤"))
        # 版权页的间隔号（书1 p213 / 书2 p182 / 书4 p120）
        self.assertEqual("内部发行·供学习研究", self.clean("内部发行·供学习研究"))
        # 书2 p161:页图上是「调料：」,剥掉分隔符整组调料会被错记成食材
        self.assertEqual("调料·食盐八分味精 二分", self.clean("调料·食盐八分味精 二分"))

    def test_stray_full_stop_between_name_and_quantity_is_removed(self) -> None:
        self.assertEqual("食盐 五钱 酱油 五两", self.clean("食盐 五钱 酱油。 五两"))

    def test_sentence_ending_full_stop_is_kept(self) -> None:
        # 全库 14 处「汉字。数词」里 13 处是正常句末,不能一起剥。
        for text in (
            "绍酒。一并放入盆内",
            "切成六寸长。四寸宽、一寸厚的块",
            "直把水分炒出为止。十斤豆子可制豆沙三十五斤",
            "比例适当。十五种用料配合比例如下：",
        ):
            self.assertEqual(text, self.clean(text))

    def test_broken_ban_glyph_is_restored(self) -> None:
        # 书1 p79 条子肉:20× 页图上是笔画残缺的「半」,且全书「平」从不作量词。
        self.assertEqual("湿淀粉 一钱半 菜籽油 半两", self.clean("湿淀粉 一钱半 菜籽油 平两"))

    def test_ping_as_a_verb_is_not_touched(self) -> None:
        self.assertEqual("压平两面", self.clean("压平两面"))
        self.assertEqual("在平底锅内摊平", self.clean("在平底锅内摊平"))

    def test_placeholder_glyph_is_never_replaced(self) -> None:
        # ▢ 是「印不清、认不出」的占位符,替换成任何具体字都是编数据;
        # 它只作为校对信号上报（见 review_priority）。
        self.assertEqual("▢淀粉 二钱", self.clean("▢淀粉 二钱"))
        self.assertEqual("菜籽油 ▢钱", self.clean("菜籽油 ▢钱"))


if __name__ == "__main__":
    unittest.main()
