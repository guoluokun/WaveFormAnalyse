# WaveFormAnalyse

一个面向实验与算法开发的轻量级波形处理、可视化和验证工具。

它的目标不是绑定某一种探测器或某一种实验，而是让用户能够快速打开 ROOT 波形数据，交互式调整处理参数，并立即观察不同算法对波形、导数、基线、噪声、频谱、寻峰和拟合结果的影响。

## 主要功能

- ROOT 波形读取
  - TTree 一维数值数组/`std::vector`
  - RNTuple 一维数值字段
  - 每事件一个 TH1 直方图
- 波形浏览
  - 逐事件切换
  - 原始波形与处理后波形同步显示
  - 自动/手动视图缩放
- 基线与噪声
  - 前置采样均值
  - 全局中位数
  - 迭代 sigma clipping
  - 移动中位数基线
  - MAD / RMS 型噪声 sigma 估计
  - 阈值可按 `n × sigma` 或绝对 ADC 设置
- 数字滤波
  - 低通、高通、带通、带阻
- 平滑与求导
  - 滑动平均
  - Savitzky-Golay
  - 中心差分、前向差分
  - 一阶/二阶导数
- 寻峰与参数提取
  - 信号局部极大值
  - 导数过零点
  - 导数上升沿
  - 幅度、峰位、FWHM、积分、上升时间、CFD50 等
- 波形拟合
  - Gaussian
  - 指数衰减
  - 双指数快上升慢衰减脉冲
  - 可选择拟合区间与输入波形
  - 显示参数误差、residual RMS、chi-square/ndf
  - 独立 residual 视图方便检查模型是否合适
- 频域分析
  - FFT 幅度谱
  - Welch PSD
- 批量统计
  - 幅度谱
  - 电荷谱
  - 峰数与噪声统计
  - CSV 导出
- 分析配置
  - JSON 保存/加载
  - 便于算法比较和结果复现

## 安装

推荐 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

开发与测试环境还需要：

```bash
pip install pytest
```

## 启动

直接启动：

```bash
python main.py
```

也可以启动时直接打开 ROOT 文件：

```bash
python main.py demo_data.root
```

## 推荐工作流

1. 打开 ROOT 文件并选择数据源。
2. 确认采样间隔和脉冲极性。
3. 先在“波形”页观察原始数据。
4. 调整基线、滤波和平滑参数，比较处理前后结果。
5. 在“导数”和“频谱”页检查算法对时域/频域信息的影响。
6. 根据任务选择寻峰方法。
7. 需要验证波形模型时启用“波形拟合”，设置拟合区间并重点查看 residual。
8. 参数确定后点击“保存参数”，把分析条件保存为 JSON。
9. 使用“批量统计”检查参数在多个事件上的稳定性。

## 拟合说明

拟合默认关闭，避免普通浏览和批量扫描产生额外计算开销。

目前提供三种基础模型，它们主要用于快速验证算法和波形形状：

- `Gaussian`：适合近似对称峰。
- `exponential`：适合理想化单边指数衰减。
- `double_exp`：适合常见的快上升、慢衰减脉冲。

拟合是在完成滤波、基线校正和极性归一之后进行的。可以选择直接拟合 `signal`，也可以拟合平滑后的 `smoothed` 波形。

建议不要只看拟合曲线是否“贴得上”，还要同时观察 residual。如果 residual 中仍有明显结构，通常说明拟合区间、预处理参数或模型本身并不合适。

## 参数配置

GUI 中的“保存参数”会把当前 `AnalysisParams` 保存为 JSON。配置只描述算法参数，不绑定数据文件，因此可以复用到其他波形数据。

加载配置时会忽略未知字段，这样旧版本配置和未来新增参数之间更容易保持兼容。

## 测试

```bash
python -m pytest tests -v
```

测试包括：

- 基线和噪声估计
- 正/负极性
- 求导
- 寻峰效率与假峰率
- pile-up 条件下的峰检测
- FFT 和数字滤波
- ROOT 读写与缓存
- 批量扫描
- 拟合参数恢复
- JSON 参数保存/加载

## 项目结构

```text
WaveFormAnalyse/
├── main.py
├── requirements.txt
├── demo_data.root
├── demo_data_truth.csv
├── demo_pileup.root
├── demo_pileup_truth.csv
├── tests/
└── wfa/
    ├── baseline.py      # 基线与 sigma
    ├── config.py        # 参数保存/加载
    ├── derivative.py    # 平滑与求导
    ├── fitting.py       # 通用波形拟合
    ├── io_root.py       # ROOT 数据源
    ├── params.py        # 统一参数对象
    ├── peaks.py         # 寻峰和峰参数
    ├── pipeline.py      # 统一分析流程
    ├── simdata.py       # 模拟/真值数据
    ├── spectrum.py      # 滤波、FFT、PSD
    └── ui/              # PyQtGraph GUI
```

## 当前定位与边界

WaveFormAnalyse 目前定位为“快速波形处理和算法验证工具”，而不是特定实验的最终重建框架。因此优先保证：

- 操作简单
- 结果可视化
- 算法模块独立
- 参数可复现
- 模拟数据可验证

后续新增算法建议继续保持这一原则：先作为独立处理模块实现，再接入统一 `pipeline` 和 GUI，同时补充可重复的测试数据与测试用例。
