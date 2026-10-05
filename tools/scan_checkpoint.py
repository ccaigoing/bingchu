"""安全检查第三方 .pt 权重 —— 全程**不执行**其中的代码。

原理：`.pt` 是 zip 包，里面是 pickle。加载 pickle 会执行字节码，
但用 `pickletools` **反汇编**它不会 —— 只读操作码。

关键区分：
- `GLOBAL` / `STACK_GLOBAL` 指向的是**会被调用的可调用对象** → 安全风险在这里
- `BINUNICODE` 等只是**字符串常量**（类别名、路径、超参） → 仅作参考，不算风险

上一版把两者混在一起查，导致 "content"、"augment"、"anthracnose" 这类
含 "nt"/"os" 的普通单词全被误报。这一版只追踪真正的调用目标。

用法：E:/anaconda3/python.exe tools/scan_checkpoint.py models/jktk_x.pt
"""

from __future__ import annotations

import io
import pickletools
import sys
import zipfile
from pathlib import Path

# 精确的模块级黑名单：命中即高危
DANGEROUS_MODULES = {
    "posix", "nt", "subprocess", "shutil", "socket", "ctypes", "pty",
    "commands", "webbrowser", "marshal", "importlib", "os", "sys",
    "pickle", "dill", "cloudpickle", "runpy", "platform", "tempfile",
}

# 危险的名字（模块无关）
DANGEROUS_NAMES = {
    "system", "popen", "exec", "eval", "execfile", "compile", "__import__",
    "spawn", "fork", "call", "check_output", "check_call", "run", "Popen",
    "loads", "load", "open", "remove", "unlink", "rmtree", "chmod",
}


def collect_call_targets(data: bytes) -> tuple[set[str], int]:
    """反汇编 pickle，返回它实际引用的可调用目标集合。

    只跟踪 GLOBAL / STACK_GLOBAL，不把字符串常量算进来。
    """
    targets: set[str] = set()
    stack: list[str] = []
    n_ops = 0

    for opcode, arg, _pos in pickletools.genops(io.BytesIO(data)):
        n_ops += 1
        name = opcode.name

        if name == "GLOBAL" and isinstance(arg, str):
            # 形如 "module name"，以空格分隔
            parts = arg.split(" ")
            if len(parts) == 2:
                targets.add(f"{parts[0]}.{parts[1]}")
                stack = stack[-20:] + [parts[1]]
            else:
                targets.add(arg)
        elif name == "STACK_GLOBAL":
            if len(stack) >= 2:
                targets.add(f"{stack[-2]}.{stack[-1]}")
        elif name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE",
                      "SHORT_BINSTRING", "BINSTRING", "STRING") and isinstance(arg, str):
            # 只用于给 STACK_GLOBAL 配对，不作为风险项
            stack = (stack + [arg])[-20:]
        elif name in ("EMPTY_TUPLE", "TUPLE", "TUPLE1", "TUPLE2", "TUPLE3",
                      "EMPTY_LIST", "LIST", "DICT", "EMPTY_DICT"):
            stack = stack[-20:]

    return targets, n_ops


def judge(targets: set[str]) -> list[str]:
    """按精确规则判定：模块名命中，或（模块不在白名单且名字危险）。"""
    hits: list[str] = []
    for t in sorted(targets):
        if "." not in t:
            continue
        mod, _, nm = t.rpartition(".")
        root = mod.split(".")[0]

        if root in DANGEROUS_MODULES:
            hits.append(t)
        elif root in ("builtins", "__builtin__") and nm in DANGEROUS_NAMES:
            hits.append(t)
    return hits


def scan(path: Path) -> int:
    print(f"扫描目标: {path}")
    print(f"文件大小: {path.stat().st_size / 1024 / 1024:.1f} MB")
    print()

    if not zipfile.is_zipfile(path):
        print("[警告] 不是 zip 格式，无法安全解析，文件结构异常。")
        return 2

    z = zipfile.ZipFile(path)
    pkls = [m for m in z.namelist() if m.endswith(".pkl")]
    print(f"zip 成员 {len(z.namelist())} 个，pickle 文件 {len(pkls)} 个")
    for m in pkls:
        print(f"  {m}  ({z.getinfo(m).file_size} 字节)")
    print()

    if not pkls:
        print("未发现 .pkl，风险较低。")
        return 0

    all_targets: set[str] = set()
    total_ops = 0
    for m in pkls:
        try:
            targets, n_ops = collect_call_targets(z.read(m))
        except Exception as exc:  # noqa: BLE001
            print(f"[警告] {m} 反汇编失败: {type(exc).__name__}: {exc}")
            return 2
        all_targets |= targets
        total_ops += n_ops
        print(f"  {m}: {n_ops} 操作码, {len(targets)} 个调用目标")
    print()

    hits = judge(all_targets)

    print(f"── 被引用的可调用对象（共 {len(all_targets)} 个，全部列出）──")
    for t in sorted(all_targets):
        mark = "  <== 可疑" if t in hits else ""
        print(f"    {t}{mark}")
    print()

    if hits:
        print("[!] 命中危险调用目标：")
        for h in hits:
            print(f"    {h}")
        print()
        print("→ 强烈建议不要加载此权重。")
        return 1

    print("[通过] 未发现 os/subprocess/socket/ctypes/exec 等危险调用。")
    print()
    print("注意：静态扫描通过 != 绝对安全。混淆过的字节码、运行时拼接的"
          "符号名仍可能绕过检查。它排除的是最常见的攻击形态。")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("models/jktk_x.pt")
    raise SystemExit(scan(target))
