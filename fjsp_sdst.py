"""HANRL 论文的第一阶段：教学版 FJSP-SDST 调度器（仅依赖标准库）。

这是一个按事件推进的、非抢占、准备时间不可提前开始的实现。
不是论文作者发布的官方复现。旨在首先验证约束、调度器、派工规则与评价指标。

FJSP-SDST 问题要素：
    - FJSP（柔性作业车间调度）：一道工序可分配给多个具备加工能力的工厂，各厂加工时间不同；
    - SDST（序列相关准备时间）：工厂切换工序类型需要换线时间，时长取决于前后两道工序的类型组合；
    - 目标：最小化 Makespan（所有工序完成时间的最大值）。
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Optional


@dataclass(frozen=True)
class Operation:
    """一道工序：属于某种"步骤类型"，并记录各工厂的加工时间。"""

    step_type: int                       # S1 / S2 ...；用于共享准备时间表
    processing: dict[int, int]           # factory_id -> processing time; 缺失表示不可加工


@dataclass(frozen=True)
class Instance:
    """一个调度问题的完整实例：订单、工厂数量、换线时间表。"""

    orders: list[list[Operation]]        # 每个订单是一条按工艺顺序排列的工序列表
    n_factories: int                     # 工厂总数
    # (上一道工序类型，下一道工序类型) -> 准备时间；0 为虚拟起点 DN
    setup: dict[tuple[int, int], int]


@dataclass(frozen=True)
class Assignment:
    """一道工序的最终分配结果（含完整的时间线），即调度方案中的一行。"""

    order: int                           # 所属订单编号（从 0 开始）
    step: int                            # 该订单内的工序索引（从 0 开始）
    factory: int                         # 被分配到的工厂编号
    dispatch_time: float                 # 派工时刻 = 工厂空闲且前序工序已完工的时刻
    setup_start: float                   # 换线/准备开始时刻（不允许提前准备）
    processing_start: float              # 加工开始时刻 = setup_start + setup
    finish: float                        # 完成时刻 = processing_start + processing
    setup: float                         # 本次换线准备时长
    processing: float                    # 本次加工时长


@dataclass
class Schedule:
    """一份完整的调度方案：规则名 + 所有工序分配明细 + 目标值。"""

    rule: str                            # 使用的派工规则（FIFO/SPT/MOR/MWKR）
    rows: list[Assignment]               # 每道工序一条记录
    makespan: float                      # makespan = max(所有工序的 finish)


RULES = ("FIFO", "SPT", "MOR", "MWKR")   # 四种待比较的派工规则


def demo_instance() -> Instance:
    """可以手工核对的两订单、两工厂实例。

    订单 A（order 0）：S1 可在 F0/F1 加工 -> S2 只能在 F1 加工；
    订单 B（order 1）：S1 只能在 F0 加工 -> S2 可在 F0/F1 加工。
    用于单元测试验证 FIFO 的已知 makespan = 11。
    """
    return Instance(
        orders=[
            [Operation(1, {0: 3, 1: 5}), Operation(2, {1: 4})],
            [Operation(1, {0: 2}), Operation(2, {0: 3, 1: 2})],
        ],
        n_factories=2,
        setup={
            (0, 1): 1, (0, 2): 2,        # 从虚拟起点 DN 进入 S1/S2 的准备时间
            (1, 1): 0, (1, 2): 2,        # 相同类型不换线；S1 -> S2 需要 2
            (2, 1): 3, (2, 2): 0,
        },
    )


def synthetic_instance(n: int, m: int, dataset: str, seed: int) -> Instance:
    """参照论文 Table 1 的分布构造简化的 SD1 / SD2 实例。

    注意：原文混合分布公式(25)的权重写法与其 Table 1、段落叙述不一致；
    这里选用 Table 1 的 90% 短换线 + 10% 长换线。
    为实现跨工厂共享的 step-type 准备时间表，这里按目标工序类型的
    平均加工时间作为换线成本尺度，是入门版实现选择，不是论文官方代码。

    参数：
        n      订单数量
        m      工厂数量
        dataset "SD1"（加工时间 1-20，工序数 4-6 或 8-12）或 "SD2"（加工时间 1-99，每单 m 道工序）
        seed   随机种子；同种子生成的实例完全一致，保证实验可复现
    """
    if dataset not in ("SD1", "SD2"):
        raise ValueError("dataset 必须是 SD1 或 SD2")
    if n < 1 or m < 1:
        raise ValueError("订单数、工厂数必须为正")
    rng = random.Random(seed)            # 独立随机源，种子相同 => 实例相同
    orders: list[list[Operation]] = []
    per_type_times: dict[int, list[int]] = {}   # 收集每种工序类型的加工时间，之后用来定换线尺度
    for _ in range(n):
        # SD1：m=5 时每单 4-6 道工序，否则 8-12 道；SD2：每单固定 m 道
        count = (rng.randint(4, 6) if m == 5 else rng.randint(8, 12)) if dataset == "SD1" else m
        steps: list[Operation] = []
        for s in range(1, count + 1):
            # 第 s 道工序随机挑选 1~m 个兼容工厂（柔性来源）
            candidates = rng.sample(range(m), k=rng.randint(1, m))
            # 加工时间上界：SD1 为 20，SD2 为 99（对应论文 Table 1）
            high = 20 if dataset == "SD1" else 99
            processing = {f: rng.randint(1, high) for f in candidates}
            per_type_times.setdefault(s, []).extend(processing.values())
            steps.append(Operation(s, processing))
        orders.append(steps)

    # 生成所有工厂共享的换线时间表：(前一道工序类型, 后一道工序类型) -> 准备时间
    setup: dict[tuple[int, int], int] = {}
    num_types = max(len(x) for x in orders)
    for a in range(0, num_types + 1):        # 0 表示虚拟起点 DN（首道工序的准备）
        for b in range(1, num_types + 1):
            if a == b:
                setup[(a, b)] = 0            # 同类型不换线，准备时间为 0
            else:
                # 换线成本尺度 = 目标工序类型的平均加工时间（教学近似）
                scale = mean(per_type_times[b])
                if rng.random() < 0.9:
                    # 90% 短换线：平均加工时间的 5%~20%
                    val = rng.uniform(0.05 * scale, 0.2 * scale)
                else:
                    # 10% 长换线：平均加工时间的 80%~120%
                    val = rng.uniform(0.8 * scale, 1.2 * scale)
                setup[(a, b)] = max(0, round(val))
    return Instance(orders, m, setup)


def _rank(inst: Instance, j: int, f: int, complete: list[int], rule: str):
    """根据派工规则返回 (j, f) 的排序键；schedule() 用 min() 选出最优候选。

    返回元组越"小"越优先；末尾的 (j, f) 作为统一的 tie-break，保证结果确定可复现。
    参数：j=订单号，f=工厂号，complete=各订单已完成工序数。
    """
    op = inst.orders[j][complete[j]]     # 订单 j 的下一道待加工工序
    pt = op.processing[f]                # 该工序在工厂 f 的加工时间
    if rule == "FIFO":
        # 先来先做；假设订单同时到达，按订单编号排队
        return (j, f)
    if rule == "SPT":
        return (pt, j, f)   # 论文 SPT：加工时间优先，不自动加上 setup
    if rule == "MOR":
        # 剩余工序最多的订单优先（负号使剩余多者排前）
        return (-len(inst.orders[j]) + complete[j], j, f)
    if rule == "MWKR":
        # 用剩余工序在所有可加工厂中的最小 PT 之和近似剩余工作量
        remaining = sum(min(s.processing.values()) for s in inst.orders[j][complete[j]:])
        return (-remaining, j, f)        # 剩余工作量最大者优先
    raise ValueError(f"不支持规则：{rule}")


def schedule(inst: Instance, rule: str = "SPT") -> Schedule:
    """按离散事件推进的非抢占调度。只允许调度已就绪的工序到空闲工厂。

    主循环：
      1) 收集候选（就绪订单 x 空闲工厂）；
      2) 有候选 -> 按规则选出最优组合立即派工；
      3) 无候选 -> 时间跳跃到最近的完工事件；
      4) 全部完工 -> 校验并返回方案。
    """
    if rule not in RULES:
        raise ValueError(f"rule 必须属于 {RULES}")

    n, m = len(inst.orders), inst.n_factories
    completed = [0] * n       # 每个订单已经完成多少道工序
    running = [False] * n     # 订单是否有正在加工的工序（同单工序不可并行）
    free_at = [0.0] * m       # 各工厂何时空闲
    last_type = [0] * m       # 各工厂上一次加工的工序类型；DN = 0
    t = 0.0                   # 当前仿真时刻
    rows: list[Assignment] = []
    active: list[tuple[float, int]] = []  # (完工时间，订单ID)：未来完工事件表
    target = sum(map(len, inst.orders))   # 需要完成的工序总数
    finished = 0
    eps = 1e-9                # 浮点比较容差

    while finished < target:
        # 只允许当前时刻空闲工厂与“前序工序已真正完成”的订单参与选择
        candidates: list[tuple[int, int]] = []
        for j, steps in enumerate(inst.orders):
            # 订单正在加工中（工艺约束：同单下一道工序必须等前一道完成），或已全部完成 -> 跳过
            if running[j] or completed[j] == len(steps):
                continue
            op = steps[completed[j]]
            for f in op.processing:
                # 工厂需具备加工能力（f 在 processing 中）且此刻空闲
                if free_at[f] <= t + eps:
                    candidates.append((j, f))

        if candidates:
            # 按派工规则选出最优的 (订单, 工厂) 组合
            j, f = min(candidates, key=lambda p: _rank(inst, p[0], p[1], completed, rule))
            step_index = completed[j]
            op = inst.orders[j][step_index]
            # 换线准备时间 = 换线表[工厂上一类型 -> 本工序类型]；首道工序从 DN(0) 查起
            su = inst.setup[(last_type[f], op.step_type)]
            pt = op.processing[f]
            # 准备从当前时刻开始（不允许提前准备），加工随后进行
            processing_start = t + su
            end = processing_start + pt
            assert end > t            # 防御：任何工序都必须占用正时间
            rows.append(Assignment(j, step_index, f, t, t, processing_start, end, su, pt))
            free_at[f] = end          # 工厂直到完工才再次空闲
            last_type[f] = op.step_type
            running[j] = True         # 该订单进入"加工中"状态
            active.append((end, j))   # 登记完工事件
            continue

        if not active:
            raise RuntimeError("调度死锁：可能存在无法加工的工序或约束错误")

        # 没有可调度动作时，跳至下一个工序完成事件（无需逐分钟循环）
        t = min(end for end, _ in active)
        done = [(end, j) for end, j in active if abs(end - t) <= eps]   # 此时刻完工的工序
        active = [(end, j) for end, j in active if abs(end - t) > eps]  # 其余仍在加工
        for _, j in done:
            assert running[j]
            running[j] = False        # 订单释放，下一道工序变为就绪
            completed[j] += 1
            finished += 1

    result = Schedule(rule, rows, max(r.finish for r in rows))
    validate(inst, result)            # 输出前自动校验全部约束
    return result


def validate(inst: Instance, sch: Schedule) -> None:
    """自动检查工厂能力、工艺约束、准备时间及资源互斥。

    这是教学版的"验收器"：任何一项断言失败都说明调度方案非法。
    """
    assert len(sch.rows) == sum(len(x) for x in inst.orders)   # 每道工序恰好分配一次
    by_op = {(r.order, r.step): r for r in sch.rows}
    assert len(by_op) == len(sch.rows), "工序重复分配"
    eps = 1e-9
    # 检查 1：加工能力 与 工艺顺序
    for j, steps in enumerate(inst.orders):
        for s, op in enumerate(steps):
            r = by_op[(j, s)]
            assert r.factory in op.processing, "工厂不具备加工能力"
            assert abs(r.processing - op.processing[r.factory]) < eps   # 加工时长与实例定义一致
            if s:
                # 后序工序的派工时刻必须晚于前序工序的完成时刻
                assert by_op[(j, s - 1)].finish <= r.dispatch_time + eps, "工序先后约束错误"
    # 检查 2：每个工厂内部的资源互斥与 SDST 查表正确性
    for f in range(inst.n_factories):
        seq = sorted((r for r in sch.rows if r.factory == f), key=lambda r: r.dispatch_time)
        prev_end, prev_type = 0, 0    # 工厂初始状态：空闲、上一类型为虚拟起点 DN
        for r in seq:
            # 本次准备不得早于上一道工序完工（不可提前准备 + 资源互斥）
            assert r.setup_start >= prev_end - eps, "工厂资源冲突"
            # 实际使用的准备时间必须等于换线表查表值
            expected = inst.setup[(prev_type, inst.orders[r.order][r.step].step_type)]
            assert abs(r.setup - expected) < eps, "准备时间计算错误"
            # 时间线自洽：加工开始 = 准备开始 + 准备时长；完成 = 加工开始 + 加工时长
            assert abs(r.processing_start - (r.setup_start + r.setup)) < eps
            assert abs(r.finish - (r.processing_start + r.processing)) < eps
            prev_end = r.finish       # 更新工厂状态，供下一道工序校验
            prev_type = inst.orders[r.order][r.step].step_type
    assert abs(sch.makespan - max(r.finish for r in sch.rows)) < eps   # makespan 定义正确


def save_schedule_csv(sch: Schedule, out: Path) -> None:
    """把调度明细写成 CSV（带 BOM，Excel 打开中文不乱码），按派工时间和工厂排序。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.writer(h)
        w.writerow(["rule", "order", "step", "factory", "dispatch_time", "setup_start", "processing_start", "finish", "setup", "processing"])
        for r in sorted(sch.rows, key=lambda x: (x.dispatch_time, x.factory)):
            # 编号统一 +1 转为人类可读的 O1/S1/F1 格式
            w.writerow([sch.rule, f"O{r.order+1}", f"S{r.step+1}", f"F{r.factory+1}", r.dispatch_time, r.setup_start, r.processing_start, r.finish, r.setup, r.processing])


def gantt(sch: Schedule, out: Path) -> None:
    """可选绘图：需额外安装 matplotlib；安装失败不影响调度。

    每个工厂一行；灰色斜纹块 = 换线准备时间，彩色块 = 加工时间（同一订单同色）。
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    m = max(r.factory for r in sch.rows) + 1
    # 画布高度随工厂数自适应
    fig, ax = plt.subplots(figsize=(11, max(3.3, 0.7 * m + 1.5)))
    colors = plt.get_cmap("tab20")    # 按订单着色的调色板
    for r in sch.rows:
        y = r.factory                 # y 轴为工厂编号
        if r.setup:
            # 有换线时间才画灰色斜纹块
            ax.barh(y, r.setup, left=r.setup_start, height=0.65, color="0.78", edgecolor="0.55", hatch="//")
        ax.barh(y, r.processing, left=r.processing_start, height=0.65,
                color=colors(r.order % 20), edgecolor="white")
        if r.processing >= 1.8:
            # 块足够宽时在中间标注 O订单-S工序
            ax.text(r.processing_start + r.processing/2, y, f"O{r.order+1}-S{r.step+1}", ha="center", va="center", fontsize=8)
    ax.set_yticks(range(m), [f"F{k+1}" for k in range(m)])
    ax.invert_yaxis()                 # 工厂 1 显示在最上方
    ax.set_xlabel("Time (same unit as setup / processing)")
    ax.set_title(f"FJSP-SDST Gantt | {sch.rule} | Makespan = {sch.makespan:.1f}")
    ax.grid(axis="x", alpha=0.2)
    ax.legend(handles=[Patch(facecolor="0.78", edgecolor="0.55", hatch="//", label="Setup time")], loc="upper right")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)                    # 释放画布，避免循环绘图时内存累积


def experiment(dataset: str, n: int, m: int, cases: int, seed: int, out: Path) -> None:
    """所有规则使用完全相同的随机实例，公平比较。

    每个案例生成一份实例，依次用四条规则调度，记录 makespan 到 CSV，
    最后打印各规则的平均 makespan。
    """
    if cases <= 0:
        raise ValueError("cases 必须 >= 1")
    rows = []
    all_scores = {r: [] for r in RULES}   # 规则 -> 该规则所有案例的 makespan 列表
    for i in range(cases):
        inst = synthetic_instance(n, m, dataset, seed + i)   # 种子递增：每个案例不同但可复现
        for rule in RULES:
            sch = schedule(inst, rule)
            all_scores[rule].append(sch.makespan)
            rows.append([dataset, n, m, seed + i, rule, sch.makespan])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as h:
        writer = csv.writer(h)
        writer.writerow(["dataset", "orders", "factories", "seed", "rule", "makespan"])
        writer.writerows(rows)
    print(f"{dataset}, {n} orders x {m} factories, {cases} cases")
    for name, scores in all_scores.items():
        print(f"  {name:4} mean makespan = {mean(scores):.2f}")
    print(f"CSV saved: {out}")


def main() -> None:
    """命令行入口：--mode demo（最小例子+甘特图）或 experiment（随机实例对比实验）。"""
    p = argparse.ArgumentParser(description="FJSP-SDST 第一阶段复现")
    p.add_argument("--mode", choices=["demo", "experiment"], default="demo")
    p.add_argument("--rule", choices=RULES, default="FIFO")
    p.add_argument("--dataset", choices=["SD1", "SD2"], default="SD2")
    p.add_argument("--orders", type=int, default=10)          # 实验模式：订单数
    p.add_argument("--factories", type=int, default=5)        # 实验模式：工厂数
    p.add_argument("--cases", type=int, default=20)           # 实验模式：随机案例数
    p.add_argument("--seed", type=int, default=42)            # 随机种子（保证可复现）
    p.add_argument("--plot", action="store_true")             # demo 模式：是否输出甘特图
    p.add_argument("--outdir", type=Path, default=Path("results"))   # 输出目录
    args = p.parse_args()

    if args.mode == "demo":
        # demo 模式：固定实例，四条规则各跑一遍并分别导出
        inst = demo_instance()
        for rule in RULES:
            sch = schedule(inst, rule)
            save_schedule_csv(sch, args.outdir / f"demo_{rule}.csv")
            print(f"{rule:4}: makespan = {sch.makespan:.1f}")
            if args.plot:
                gantt(sch, args.outdir / f"demo_{rule}.png")
        print("完整测试实例已保存为 results/demo_*.csv")
    else:
        # experiment 模式：随机实例上对比四条规则
        experiment(args.dataset, args.orders, args.factories, args.cases, args.seed,
                   args.outdir / f"{args.dataset}_{args.orders}x{args.factories}.csv")


if __name__ == "__main__":
    main()
