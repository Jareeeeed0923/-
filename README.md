# HANRL 论文第一阶段：FJSP-SDST 调度复现

> **这是教学版项目，不是作者官方实现，不保证复现论文 Table 2 的精确数值。**
> 基于论文第 4.3 节与第 5.1 节的结构搭建，优先保证调度环境能够被理解和验证。

## 1. MacBook Air M5 + 16GB 环境准备

在 macOS **终端**输入：

```bash
python3 --version
cd ~/Downloads/HANRL_stage1_mac
python3 -m venv .venv
source .venv/bin/activate
python -m pip install matplotlib
```

如果没有 Python 3，请先安装 Python 3（建议使用官网或常用包管理器），然后重试。

## 2. 运行最小例子

```bash
python fjsp_sdst.py --mode demo --plot
python -m unittest -v
```

将得到：
- `results/demo_FIFO.csv` 等四份调度明细，包含开始时间、准备时间、加工时间、完成时间；
- `results/demo_FIFO.png` 等四张甘特图，灰色斜线代表准备时间；
- 单元测试结果，包括资源互斥、工序顺序与 FIFO 的已知 makespan。

如果不想安装 matplotlib，可去掉 `--plot`，其他功能仅需 Python 标准库。

## 3. 生成论文风格随机实例并比较四种规则

```bash
python fjsp_sdst.py --mode experiment --dataset SD1 --orders 10 --factories 5 --cases 20
python fjsp_sdst.py --mode experiment --dataset SD2 --orders 10 --factories 5 --cases 20
```

规模更大时再尝试：

```bash
python fjsp_sdst.py --mode experiment --dataset SD2 --orders 20 --factories 10 --cases 100
```

输出 CSV 可以用 Excel 直接查看，终端会给出 FIFO、SPT、MOR、MWKR 的平均 Makespan。

## 4. 对应论文的方法设定与教学简化

- 论文规定：每个订单有固定工艺先后关系；可分配到兼容的工厂；不可抢占；工厂间共享 step-to-step SDST 表；优化 Makespan。
- 本项目采用：**事件驱动模拟**，只有前驱真正完工、工厂实际空闲后才能派工；准备时间从工厂空闲并且工序已就绪时开始，**不允许提前准备**。这是明确的实现选择。
- SD1：当 `m=5` 时，订单含 4–6 道工序；当 `m!=5` 时，示例采用 8–12 道。SD2：每个订单有 `m` 道工序。加工时间按 Table 1 采样；兼容工厂数 1–m。
- SDST：按照论文 Table 1 的文字/脚注“约 90% 低准备时间 + 10% 高准备时间”模拟；注意正文的公式(25)权重写法与 Table 1 不一致，这里**没有将矛盾静默消除**，而是明确选用 Table 1。为生成“所有工厂共用的工序类型准备时间矩阵”，代码使用目标 step 类型的平均加工时间作为缩放基准；**这是工程化近似，不是作者提供的原代码**。
- FIFO/SDST/剩余工作量有多种实现细节。这里 FIFO 按订单编号（假设同时到达）；SPT 按当前工序加工时间；MOR 按订单剩余工序数；MWKR 按剩余工序最短兼容加工时间之和。原论文尚未给出所有的 tie-break/具体实现细节，因此 Table 2 数字不应预期完全一致。

## 5. 第一阶段验收条件

1. 每道工序恰好加工一次；
2. 工序前驱已完成，后继才能开始；
3. 工厂同一时刻不能执行两道工序；
4. 每次换线都有正确的 SDST，第一道工序从虚拟起点 DN 计算准备时间；
5. 输出 `makespan = max(所有工序的完成时间)`；
6. 同一批实例同时用四种规则比较；
7. 改变随机种子仍可运行、可复现。

## 6. 后续第二阶段的衔接

接入强化学习时，将 `schedule()` 中 `_rank()` 的规则选择替换为 Actor 网络的动作选择，但不需要推倒重写调度环境。正式复现之前，还需要精确对齐原文 MDP 的动作时间推进、状态特征与奖励定义。
