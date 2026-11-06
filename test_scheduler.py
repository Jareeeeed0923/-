import unittest
from fjsp_sdst import RULES, demo_instance, schedule, synthetic_instance, validate


class FirstStageTests(unittest.TestCase):
    """第一阶段验收测试：调度合法性、可复现性、以及与手工推算结果的对照。"""

    def test_demo_all_rules(self):
        # demo 实例（2 单 4 道工序）在四条规则下都应产出合法调度
        inst = demo_instance()
        for rule in RULES:
            sch = schedule(inst, rule)
            validate(inst, sch)                  # 全约束自动校验
            self.assertEqual(len(sch.rows), 4)   # 每道工序恰好分配一次
            self.assertGreater(sch.makespan, 0)  # makespan 必须为正

    def test_demo_fifo_known_makespan(self):
        # FIFO: A1/F1:0-4, B1/F1:4-6, A2/F2:4-10, B2/F1:6-11
        # 与手工推算的甘特图对照，是核心正确性锚点
        self.assertEqual(schedule(demo_instance(), "FIFO").makespan, 11)

    def test_synthetic_same_seed(self):
        # 同种子两次生成必须得到完全相同的实例（可复现性）
        x = synthetic_instance(10, 5, "SD2", 42)
        y = synthetic_instance(10, 5, "SD2", 42)
        self.assertEqual(x, y)
        for rule in RULES:
            validate(x, schedule(x, rule))       # 随机实例上的调度也必须合法

    def test_synthetic_SD1(self):
        # SD1 在 m=5 时：每单工序数应落在 4-6 的范围内
        x = synthetic_instance(10, 5, "SD1", 123)
        self.assertTrue(all(4 <= len(ops) <= 6 for ops in x.orders))
        validate(x, schedule(x, "SPT"))


if __name__ == "__main__":
    unittest.main()
