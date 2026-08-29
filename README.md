# WaveFormAnalyse

一个面向实验与算法开发的轻量级波形处理、可视化和验证工具。

目标不是绑定某一种探测器或实验，而是让用户快速打开 ROOT 波形数据，交互式调整处理参数，并立即观察不同算法对波形、导数、基线、噪声、频谱、寻峰和拟合结果的影响。

## 主要功能

- ROOT 波形读取：TTree、RNTuple、一组 TH1
- 原始/处理后波形快速浏览
- 基线与噪声：前置均值、中位数、sigma clipping、移动中位数、MAD/RMS sigma
- 数字滤波：低通、高通、带通、带阻
- 平滑与求导：滑动平均、Savitzky-Golay、中心/前向差分、一阶/二阶导
- 寻峰与参数：峰位、幅度、FWHM、积分、上升时间、CFD50 等
- 波形拟合：Gaussian、指数衰减、双指数脉冲、参数误差、residual、chi-square/ndf
- FFT 幅度谱和 Welch PSD
- 批量幅度/电荷/峰数/噪声统计和 CSV 导出
- JSON 分析参数保存/加载

## Python 安装

推荐 Python 3.10+，建议使用独立虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

也仍可使用：

```bash
pip install -r requirements.txt
```

开发与测试：

```bash
pip install -e '.[dev]'
python -m pytest tests -v
```

## Linux / Ubuntu / WSL2 GUI 依赖

NumPy、SciPy、uproot 等计算模块本身不依赖桌面环境；Linux 上容易出问题的是 PyQt5 的 Qt platform plugin。

### Ubuntu/Debian 推荐安装

仓库提供辅助脚本：

```bash
bash scripts/install_linux_gui_deps.sh
```

它安装 Qt5/pyqtgraph 常见的 X11/XCB、Wayland 和 OpenGL 运行库。

### 自动平台选择

WaveFormAnalyse 0.2.1 起在导入 PyQt5 **之前**检查图形环境：

- Windows/macOS：交给 Qt 使用系统原生平台。
- Ubuntu GNOME Wayland：若 PyQt5 提供 Wayland plugin，优先 `wayland`。
- WSL2 + WSLg：若存在 `WAYLAND_DISPLAY`，优先 `wayland`。
- Linux X11：使用 `xcb`。
- 如果用户已经设置 `QT_QPA_PLATFORM`，程序尊重用户设置，不覆盖。

这避免了 Ubuntu Wayland/WSLg 环境中 Qt5 默认尝试 `xcb`，却因缺少 XCB 动态库而直接 abort/core dump 的常见问题。

### Qt 环境诊断

任何系统都可以运行：

```bash
python main.py --qt-diagnostics
```

或安装后：

```bash
wfa --qt-diagnostics
```

Linux 下诊断会显示：

- 是否为 WSL
- `XDG_SESSION_TYPE`
- `DISPLAY`
- `WAYLAND_DISPLAY`
- 自动选择的 Qt platform
- PyQt5 platform plugin 目录
- 可用的 `wayland/xcb/offscreen` plugins
- 目标 plugin 的 `ldd` 缺失动态库

如果存在明确缺失依赖，程序会在创建 `QApplication` 前退出并打印修复建议，而不是让 Qt 直接 core dump。

### 手动指定平台

通常无需设置；排错时可以：

```bash
python main.py --qt-platform wayland
python main.py --qt-platform xcb
```

无桌面 CI/服务器只做启动诊断时可使用：

```bash
python main.py --qt-platform offscreen --qt-diagnostics
```

注意：offscreen 模式不适合正常交互式 GUI 使用。

### 你看到 `Could not load the Qt platform plugin "xcb"` 时

先运行：

```bash
python main.py --qt-diagnostics
```

若当前是 GNOME Wayland，正常情况下新版启动器会自动选择 `wayland`。若必须使用 X11/xcb，可运行：

```bash
bash scripts/install_linux_gui_deps.sh
python main.py --qt-platform xcb --qt-diagnostics
```

如果需要进一步人工定位，也可以：

```bash
QT_DEBUG_PLUGINS=1 python main.py --qt-platform xcb
```

## WSL2 建议

1. Windows 中保持 WSL/WSLg 为新版本：

```powershell
wsl --update
wsl --shutdown
```

2. 在 WSL 中确认：

```bash
echo $DISPLAY
echo $WAYLAND_DISPLAY
ls /mnt/wslg
```

3. 项目与大 ROOT 文件优先放在 WSL Linux 文件系统（如 `~/projects`、`~/data`），而不是长期放在 `/mnt/c/...`，以减少跨文件系统 I/O 开销。

## 启动

源码目录：

```bash
python main.py
python main.py demo_data.root
```

安装后：

```bash
wfa
wfa demo_data.root
```

或：

```bash
python -m wfa
```

这三种入口共用同一个 `wfa.app` 启动器，因此 Qt 平台检测行为一致。

## 推荐工作流

1. 打开 ROOT 文件并选择数据源。
2. 确认采样间隔和脉冲极性。
3. 在“波形”页观察原始数据。
4. 调整基线、滤波和平滑参数，比较处理前后结果。
5. 在“导数”和“频谱”页检查时域/频域变化。
6. 根据任务选择寻峰方式。
7. 需要验证波形模型时启用拟合，设置拟合区间并检查 residual。
8. 保存 JSON 参数以复现实验条件。
9. 使用批量统计检查多个事件上的稳定性。

## 项目结构

```text
WaveFormAnalyse/
├── main.py
├── pyproject.toml
├── requirements.txt
├── scripts/
│   └── install_linux_gui_deps.sh
├── tests/
└── wfa/
    ├── app.py           # 跨平台统一启动器
    ├── qt_compat.py     # Linux/WSL/Wayland/X11 环境诊断
    ├── baseline.py
    ├── config.py
    ├── derivative.py
    ├── fitting.py
    ├── io_root.py
    ├── params.py
    ├── peaks.py
    ├── pipeline.py
    ├── simdata.py
    ├── spectrum.py
    └── ui/
```

## 当前定位与边界

WaveFormAnalyse 定位为“快速波形处理和算法验证工具”，优先保证：

- 操作简单
- 结果可视化
- 算法模块独立
- 参数可复现
- 模拟数据可验证
- Windows / Linux / WSL2 启动行为尽量一致

新增算法建议先作为独立处理模块实现，再接入统一 pipeline 和 GUI，同时补充可重复的测试数据与测试用例。
