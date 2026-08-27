"""ROOT 文件波形读取。

支持三种常见存储方式，并自动探测：
1. TTree 分支：每个 entry 一条波形，可以是变长向量 ``std::vector<short/float/...>``
   或定长数组 ``Short_t wave[1024]``；
2. RNTuple 字段：ROOT 新版列式格式（uproot 也默认写这种），处理方式同上；
3. TH1 直方图：每个事件一个直方图，作为文件（或子目录）中的独立 key 存放，
   时间轴直接取直方图 x 轴。

仅依赖 uproot，无需本地安装 ROOT。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import uproot

# 认为可以构成波形的标量类型（向量元素或数组元素）
_NUMERIC_TOKENS = (
    "short", "ushort", "int", "uint", "long", "ulong",
    "float", "double", "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64", "byte",
)


def _is_waveform_typename(typename: str) -> bool:
    """判断分支类型名是否为「一维数值序列」。"""
    t = typename.replace(" ", "")
    low = t.lower()
    if low.startswith("std::vector<") or low.startswith("vector<"):
        inner = t[t.index("<") + 1: t.rindex(">")]
        if "<" in inner:  # 嵌套向量不支持
            return False
        return any(tok in inner.lower() for tok in _NUMERIC_TOKENS)
    if "[" in t and t.count("[") == 1:
        base = t[: t.index("[")].lower()
        return any(tok in base for tok in _NUMERIC_TOKENS)
    return False


def _natural_key(name: str):
    """把 h_10 排在 h_9 之后。"""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


@dataclass
class SourceSpec:
    """一个可读的波形数据源描述。"""

    kind: str                       # "branch" | "rntuple" | "hists"
    label: str
    n_events: int
    tree: str = ""
    branch: str = ""
    keys: tuple = field(default_factory=tuple)


def _collect_branches(tree, prefix: str = ""):
    """递归收集分支 (全名, 类型名)。"""
    out = []
    for br in tree.branches:
        name = f"{prefix}{br.name}"
        try:
            typename = br.typename
        except Exception:
            typename = ""
        if br.branches:
            out.extend(_collect_branches(br, prefix=f"{name}/"))
        if typename:
            out.append((name, typename))
    return out


def discover_sources(path: str) -> list[SourceSpec]:
    """扫描 ROOT 文件，返回所有可作为波形使用的数据源。"""
    specs: list[SourceSpec] = []
    with uproot.open(path) as f:
        classnames = f.classnames(recursive=True)

        # --- TTree 分支 ---
        tree_names = sorted({k for k, c in classnames.items() if c.startswith("TTree")})
        for tname in tree_names:
            tree = f[tname]
            short_tree = tname.split(";")[0]
            for bname, typename in _collect_branches(tree):
                if not _is_waveform_typename(typename):
                    continue
                specs.append(
                    SourceSpec(
                        kind="branch",
                        label=f"[TTree] {short_tree}/{bname}  ({typename}, {tree.num_entries} events)",
                        n_events=int(tree.num_entries),
                        tree=short_tree,
                        branch=bname,
                    )
                )

        # --- RNTuple 字段（ROOT 新版列式格式）---
        rn_names = sorted({k for k, c in classnames.items() if "RNTuple" in c})
        for rname in rn_names:
            rn = f[rname]
            short_name = rname.split(";")[0]
            try:
                typenames = rn.typenames()
            except Exception:
                typenames = {}
            for fname in rn.keys():
                typename = str(typenames.get(fname, ""))
                if not _is_waveform_typename(typename):
                    continue
                specs.append(
                    SourceSpec(
                        kind="rntuple",
                        label=f"[RNTuple] {short_name}/{fname}  ({typename}, {rn.num_entries} events)",
                        n_events=int(rn.num_entries),
                        tree=short_name,
                        branch=fname,
                    )
                )

        # --- TH1 直方图（按所在目录分组）---
        hist_groups: dict[str, list[str]] = {}
        for k, c in classnames.items():
            if c.startswith("TH1"):
                directory = k.rsplit("/", 1)[0] if "/" in k else ""
                hist_groups.setdefault(directory, []).append(k)
        for directory, keys in hist_groups.items():
            keys = sorted(keys, key=_natural_key)
            where = directory if directory else "(根目录)"
            specs.append(
                SourceSpec(
                    kind="hists",
                    label=f"[TH1] {where}  ({len(keys)} 个直方图)",
                    n_events=len(keys),
                    keys=tuple(keys),
                )
            )
    return specs


class WaveformSource:
    """波形数据源基类：按事件号返回 (时间轴, 采样值)。"""

    def __init__(self, label: str, n_events: int, sample_ns: float = 1.0):
        self.label = label
        self.n_events = int(n_events)
        self.sample_ns = float(sample_ns)

    def get_event(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class BranchSource(WaveformSource):
    """从 TTree 分支逐事件读取波形，带分块缓存以加速翻事件。"""

    def __init__(self, path: str, tree: str, branch: str,
                 sample_ns: float = 1.0, block: int = 200):
        self._file = uproot.open(path)
        self._branch = self._file[tree][branch]
        super().__init__(f"{tree}/{branch}", self._branch.num_entries, sample_ns)
        self._block = max(1, int(block))
        self._cache = None
        self._cache_start = -1

    def _ensure_block(self, index: int) -> None:
        start = (index // self._block) * self._block
        if self._cache is not None and start == self._cache_start:
            return
        stop = min(start + self._block, self.n_events)
        self._cache = self._branch.array(entry_start=start, entry_stop=stop, library="np")
        self._cache_start = start

    def get_event(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        if not 0 <= index < self.n_events:
            raise IndexError(f"事件号越界: {index}")
        self._ensure_block(index)
        y = np.asarray(self._cache[index - self._cache_start], dtype=np.float64).ravel()
        t = np.arange(y.size, dtype=np.float64) * self.sample_ns
        return t, y

    def close(self) -> None:
        self._file.close()


class RNTupleSource(WaveformSource):
    """从 RNTuple 字段逐事件读取波形，带分块缓存。"""

    def __init__(self, path: str, rntuple: str, field_name: str,
                 sample_ns: float = 1.0, block: int = 200):
        self._file = uproot.open(path)
        self._field = self._file[rntuple][field_name]
        n = int(self._file[rntuple].num_entries)
        super().__init__(f"{rntuple}/{field_name}", n, sample_ns)
        self._block = max(1, int(block))
        self._cache = None
        self._cache_start = -1

    def _ensure_block(self, index: int) -> None:
        start = (index // self._block) * self._block
        if self._cache is not None and start == self._cache_start:
            return
        stop = min(start + self._block, self.n_events)
        self._cache = self._field.array(entry_start=start, entry_stop=stop)
        self._cache_start = start

    def get_event(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        if not 0 <= index < self.n_events:
            raise IndexError(f"事件号越界: {index}")
        self._ensure_block(index)
        y = np.asarray(self._cache[index - self._cache_start], dtype=np.float64).ravel()
        t = np.arange(y.size, dtype=np.float64) * self.sample_ns
        return t, y

    def close(self) -> None:
        self._file.close()


class HistSource(WaveformSource):
    """每个事件一个 TH1 直方图，时间轴取直方图 bin 中心。"""

    def __init__(self, path: str, keys: Sequence[str], sample_ns: float | None = None):
        self._file = uproot.open(path)
        self._keys = list(keys)
        super().__init__(f"TH1 x{len(self._keys)}", len(self._keys), sample_ns or 1.0)
        self._explicit_sample_ns = sample_ns is not None

    def get_event(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        if not 0 <= index < self.n_events:
            raise IndexError(f"事件号越界: {index}")
        hist = self._file[self._keys[index]]
        y = np.asarray(hist.values(), dtype=np.float64)
        if self._explicit_sample_ns:
            t = np.arange(y.size, dtype=np.float64) * self.sample_ns
        else:
            edges = np.asarray(hist.axis().edges(), dtype=np.float64)
            t = 0.5 * (edges[:-1] + edges[1:])
            if t.size > 1:
                self.sample_ns = float(t[1] - t[0])
        return t, y

    def event_name(self, index: int) -> str:
        return self._keys[index]

    def close(self) -> None:
        self._file.close()


def open_source(path: str, spec: SourceSpec, sample_ns: float | None = 1.0) -> WaveformSource:
    """按 SourceSpec 打开数据源。"""
    if spec.kind == "branch":
        return BranchSource(path, spec.tree, spec.branch, sample_ns or 1.0)
    if spec.kind == "rntuple":
        return RNTupleSource(path, spec.tree, spec.branch, sample_ns or 1.0)
    if spec.kind == "hists":
        return HistSource(path, spec.keys, sample_ns)
    raise ValueError(f"未知数据源类型: {spec.kind}")
