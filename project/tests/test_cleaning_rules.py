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

    # ——— 2026-07-30 用户裁定的用字归一（work/reports/待裁定.csv 第 1/3 类）———

    def test_ocr_mistake_lai_is_restored_to_cai(self) -> None:
        # 全库「莱」8 处,无一是真的「莱」。「莱籽汕」两处讹字叠在一起（书4 p68)。
        self.assertEqual("菜籽油 一两", self.clean("莱籽汕 一两"))
        self.assertEqual("菜籽油 三两", self.clean("莱籽油 三两"))
        self.assertEqual("配料: 大白菜 一斤半", self.clean("配料: 大白莱 一斤半"))
        self.assertEqual("3. 走菜时将鸡片捞出", self.clean("3. 走莱时将鸡片捞出"))

    def test_ocr_mistake_bocai_and_baifan(self) -> None:
        self.assertEqual("菠菜 三钱", self.clean("波菜 三钱"))
        # 原书这一行名称与用量之间是对齐空格,所以规则必须是单字「矶」而不是词组「白矶」
        self.assertEqual("豆 粉 十斤 白 矾 五钱", self.clean("豆 粉 十斤 白 矶 五钱"))

    def test_shanzha_rule_covers_more_than_the_cake(self) -> None:
        # 原规则只有「山查糕」,「炸山查肉夹」（书2 p171 菜名）因此一直漏改。
        self.assertEqual("（一七九）炸山楂肉夹", self.clean("（一七九）炸山查肉夹"))
        self.assertEqual("山楂糕 一钱", self.clean("山查糕 一钱"))

    def test_high_confidence_modern_spellings(self) -> None:
        self.assertEqual("芥末糊 三钱", self.clean("芥茉糊 三钱"))
        self.assertEqual("（五三）荷叶饼", self.clean("（五三）合页饼"))
        self.assertEqual("（一七七）拔丝梨", self.clean("（一七七）拨丝梨"))
        self.assertEqual("番茄酱 五钱", self.clean("蕃茄酱 五钱"))
        self.assertEqual("酸辣甘蓝", self.clean("酸辣甘兰"))

    def test_internal_variants_are_folded_to_the_majority(self) -> None:
        self.assertEqual("（八六）挂粉汤圆", self.clean("（八六）挂粉汤元"))
        self.assertEqual("菜籽油 半两", self.clean("菜子油 半两"))
        self.assertEqual("调和面 二钱", self.clean("调合面 二钱"))
        self.assertEqual("净虾籽一两", self.clean("净虾子一两"))
        self.assertEqual("（十三）焦溜里脊片", self.clean("（十三）焦熘里脊片"))

    def test_words_that_look_similar_are_not_touched(self) -> None:
        # 「元宵」是另一种食品（书3 p96 独立成篇),不是「汤元」
        self.assertEqual("（八七）元宵", self.clean("（八七）元宵"))
        # 「炒拨鱼」是正经菜名（书3 p77),只有「拨丝」才替换
        self.assertEqual("（六二）炒拨鱼", self.clean("（六二）炒拨鱼"))
        # 「桔饼」不动:全库「桔」29 处 vs「橘」1 处,多数派是「桔」
        self.assertEqual("桔饼 二钱", self.clean("桔饼 二钱"))
        # 「莲籽」「松籽」「捶」是老菜谱习用写法,用户裁定保留
        self.assertEqual("蜜汁糖莲籽", self.clean("蜜汁糖莲籽"))
        self.assertEqual("松籽酿方肉", self.clean("松籽酿方肉"))
        self.assertEqual("清汤捶鸡片", self.clean("清汤捶鸡片"))
        # 页图核对后确认原书如此,不改（详见 CLAUDE.md「已确认保留」清单）
        for text in ("西卤羊肉", "奶汤伞胆", "八锦甜饭", "炒肝油", "硬汁里脊",
                     "元桂 一钱", "穿裤里脊", "带背酥", "浇糊肘子", "金葱扒童狗",
                     "炸高力鱼条"):
            self.assertEqual(text, self.clean(text))

    def test_toc_wins_only_for_the_three_named_dishes(self) -> None:
        # 用户逐条裁定「按目录」的三条,必须是词组限定
        self.assertEqual("（一〇五）干烧仔鸡", self.clean("（一〇五）干烧子鸡"))
        self.assertEqual("（一一五）口蘑汆肫肝", self.clean("（一一五）口蘑汆胗肝"))
        self.assertEqual("（一五三）五柳素鱼", self.clean("（一五三）五柳絮鱼"))
        # 同类的其它「子鸡 / 胗 / 絮」一律以正文为准,不得连坐
        self.assertEqual("（一〇四）熬炒子鸡", self.clean("（一〇四）熬炒子鸡"))
        self.assertEqual("主料：光子鸡一只", self.clean("主料：光子鸡一只"))
        self.assertEqual("（一一三）辣子鸡丁", self.clean("（一一三）辣子鸡丁"))
        self.assertEqual("净鸡胗 一两", self.clean("净鸡胗 一两"))
        self.assertEqual("先搅成面絮", self.clean("先搅成面絮"))


    def test_second_batch_2026_07_30(self) -> None:
        """2026-07-30 第二批（页图逐字核定）的四条，正例 + 负例。"""
        # ① 转录漏字：页图上标题是五个字「（三一）镇川干炉馍」，制法两处自证
        self.assertEqual("（三一）镇川干炉馍", self.clean("（三一）镇川干炉"))
        # 已经对的不许改成「干炉馍馍」
        self.assertEqual("即成“干炉馍”", self.clean("即成“干炉馍”"))
        self.assertEqual("将干炉馍放入火鏊上", self.clean("将干炉馍放入火鏊上"))

        # ② 原书换行断字造成的假空格（书3 p69：「元」在行尾、「桂」在次行行首）
        self.assertEqual(
            "食盐、元桂、调料包", self.clean("食盐、元 桂、调料包")
        )
        self.assertEqual("元桂 一两", self.clean("元桂 一两"))
        # 真正的「品名 分量」字段分隔不受影响
        self.assertEqual("元桂 一节", self.clean("元 桂 一节"))
        self.assertEqual("上元桂 二斤", self.clean("上元桂 二斤"))

        # ③ 「干爦」是方言本字，不是「烩」（书3 p69 三处同一字形）
        self.assertEqual("干爦肉臊子", self.clean("干烩肉稍子"))
        self.assertEqual("3. 干爦臊子：猪槽头肉切小丁", self.clean("3. 干烩梢子：猪槽头肉切小丁"))
        # 词组限定：同书正经的「烩」不受影响
        for text in ("炒饼、烩饼、焖饼", "荠菜烩肉丝", "3. 烩臊子：将水海参、鱿鱼"):
            self.assertEqual(text, self.clean(text))

        # ④ 「稍子/梢子」→「臊子」（原书一贯写法归现代汉语）
        self.assertEqual("肉臊子 一两", self.clean("肉稍子 一两"))
        self.assertEqual("汤臊子", self.clean("汤梢子"))
        self.assertEqual("素臊子——按四季选用各种时鲜菜", self.clean("素稍子——按四季选用各种时鲜菜"))
        # 作副词的「稍」（全书 200 余处）与其它「梢」不许连坐
        for text in ("味精少许稍焖即成", "投入葱、姜稍爆", "搅匀, 稍煮一会", "稍加搅炒"):
            self.assertEqual(text, self.clean(text))


if __name__ == "__main__":
    unittest.main()
