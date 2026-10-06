"""把三个模型权重取到 models/ 下，并逐个校验 SHA256。

## 为什么需要这个脚本

`models/*.pt` 被 .gitignore 排除（见 .gitignore 第 24 行）—— 光 jktk_x.pt 就
457,175,703 字节，远超 GitHub 单文件 100MB 上限。所以**代码能 git clone，
权重不能**。服务器上 clone 完代码后必须再跑一次这个脚本，否则后端会以降级模式
启动：判型、定位、虫害闸门全部哑火，页面上什么都认不出来。

放 GitHub **Release 资产**里是正解 —— Release 单文件上限 2GB，
三个加起来 519MB 装得下，而且带版本号和下载计数，比丢网盘可追溯得多。

## 三种取法

    1. --from-url            从权重**源站**直接下载（最快，推荐）
    2. --repo owner/name     从 GitHub Release 下载（正规路径，做一次就够）
    3. --from-dir <本地目录>  从本机已有的 models/ 直接拷

**优先用 --from-url**：它直接从 HuggingFace / ultralytics 官方下载，
不经过 GitHub，也不占用你家宽带的**上行**。436MB 从家里往上推到 GitHub
是国内部署最容易卡死的一步，而在服务器上往下拉通常快得多。
每个权重都列了多个源站（hf-mirror 与 HuggingFace 官方），脚本按顺序试，
哪个通走哪个 —— 这正好对应"国内 vs 香港"两种服务器网络。

**服务器连不上外网时用第 3 种**：在你自己的电脑上（权重已经在了）跑

    scp models/*.pt user@<服务器IP>:/srv/yaodao/models/

然后在服务器上 `python tools/fetch_weights.py --from-dir /srv/yaodao/models`。

## 校验

每个文件都带 SHA256，**校验不过就删掉重来并报错退出**，不会留下半个损坏的权重。
这些哈希是在本机对着能跑出正确结果的权重算出来的（jktk_x 的哈希与
models/README.md 里 pest 权重那条记录互相印证过，见文件末尾）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = ROOT / "models"

# 默认 Release 标签。每次换权重就换一个标签，别覆盖旧的 ——
# 覆盖会让"服务器上跑的是哪一版权重"变得不可考，而这正是答辩会被问的。
DEFAULT_TAG = "v1.0-weights"

# ── 权重清单 ──
#
# size 只是**提示**，真正判定用 sha256。写在这里是为了下到一半时
# 能算出百分比进度 —— 519MB 在慢网络上要等很久，没有进度条像是卡死了。
WEIGHTS: dict[str, dict] = {
    "jktk_x.pt": {
        # 判型主力。YOLO11x / 116 类 / apache-2.0
        # 来源 hf-mirror.com/hodoly163/krishibondhu-jktk
        "sha256": "e24887caf451239cd506fa611db25b9524430ca085aa562aecaf1b1d4e3c39bf",
        "size": 457_175_703,
        "required": True,
        # 源站地址，按顺序试。第一个是 hf-mirror（国内快），第二个是 HuggingFace
        # 官方（香港/海外快）—— 服务器在哪边都能走最快的那个。
        # 两个地址实测都是 206 且 Content-Range 的字节数与 size 一致。
        "urls": [
            "https://hf-mirror.com/hodoly163/krishibondhu-jktk/resolve/main/jktk_x.pt",
            "https://huggingface.co/hodoly163/krishibondhu-jktk/resolve/main/jktk_x.pt",
        ],
    },
    "FastSAM-s.pt": {
        # 定位辅助：类无关分割，用来把泥水从病灶候选里减掉。
        # AGPL-3.0，官方 ultralytics 资产 v8.3.0
        "sha256": "c9f78716a81c7aff0d608ccc73e1b82ab3aaad86005049f6a92106a0be6d0844",
        "size": 23_851_578,
        "required": False,   # 缺了只是定位回落纯 HSV，不崩
        "urls": [
            "https://github.com/ultralytics/assets/releases/download/v8.3.0/FastSAM-s.pt",
        ],
    },
    "yolo11s-pest-ip102.pt": {
        # 虫害闸门：只回答"有没有虫"，虫种名不可采信（见 services/pest_gate.py）
        # MIT，来源 hf-mirror.com/underdogquality/yolo11s-pest-detection
        # ⚠️ 源站文件名是 best.pt，落地时改成了现在这个名字。仓库根目录下就是它
        #    （weights/best.pt 那个路径实测 404，别照直觉猜子目录）。
        "sha256": "810f0df179aec54f5d9762a11df4a147ff87ef79ca46649151914eeed260237f",
        "size": 38_317_890,
        "required": False,   # 缺了判型回落「疑似病斑」
        "urls": [
            "https://hf-mirror.com/underdogquality/yolo11s-pest-detection/resolve/main/best.pt",
        ],
    },
}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    """分块算哈希。436MB 一次性读进内存没必要，也会让低配机器更难喘气。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def download(url: str, dest: Path, expect_size: int) -> None:
    """下载到 .part 再改名。

    **不直接写目标文件名**：中断时留下半个文件，下次跑会被"文件已存在"的
    判断当成完好权重放过去 —— 那种损坏要到加载模型时才暴露，且报错信息
    完全指不到"当初下载没下完"。半成品叫 .part，一眼能看出来。
    """
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)

    print(f"  下载 {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 —— 地址来自本文件内的常量
            total = int(resp.headers.get("Content-Length") or expect_size)
            done = 0
            last_pct = -1
            with part.open("wb") as out:
                while block := resp.read(1 << 20):
                    out.write(block)
                    done += len(block)
                    # 只在百分比变化时刷屏，否则每 MB 一行会把日志淹掉
                    pct = int(done * 100 / total) if total else 0
                    if pct != last_pct and pct % 10 == 0:
                        last_pct = pct
                        print(f"    {pct:>3}%  {_human(done)} / {_human(total)}", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"下载失败：{exc}") from exc

    part.replace(dest)


def fetch_one(
    name: str,
    spec: dict,
    models_dir: Path,
    *,
    repo: str | None,
    tag: str,
    from_dir: Path | None,
    from_url: bool,
    force: bool,
) -> str:
    """取一个权重。返回 'ok' / 'skip' / 'failed'。"""
    dest = models_dir / name
    expect = spec["sha256"]

    if dest.exists() and not force:
        actual = sha256_of(dest)
        if actual == expect:
            print(f"[跳过] {name} —— 已存在且校验通过")
            return "ok"
        print(f"[重取] {name} —— 文件存在但校验不过")
        print(f"        期望 {expect}")
        print(f"        实际 {actual}")
        dest.unlink()
    elif force and dest.exists():
        dest.unlink()

    try:
        if from_dir is not None:
            src = from_dir / name
            if not src.exists():
                raise RuntimeError(f"源目录里没有 {name}")
            if src.resolve() == dest.resolve():
                raise RuntimeError(f"--from-dir 指向的就是目标目录，源和目标同一个文件")
            print(f"[拷贝] {name} ← {src}")
            shutil.copy2(src, dest)
        elif from_url:
            # 依次试源站地址。**不因为第一个失败就放弃** —— hf-mirror 与
            # HuggingFace 官方在不同网络下的可达性正好相反（国内 vs 海外），
            # 多列一个就等于让脚本自己挑可达的那个。
            urls = spec["urls"]
            for i, url in enumerate(urls, 1):
                try:
                    download(url, dest, spec["size"])
                    break
                except RuntimeError as exc:
                    if i == len(urls):
                        raise RuntimeError(
                            f"{len(urls)} 个来源都失败：\n"
                            + "\n".join(f"  {u}" for u in urls)
                            + f"\n  最后一次：{exc}"
                        ) from exc
                    print(f"        ↑ 失败（{exc}），换下一个来源")
        else:
            if not repo:
                raise RuntimeError(
                    "没有指定来源。三种取法：\n"
                    "  --from-url            从权重源站下载（服务器带宽好时最快）\n"
                    "  --repo owner/name     从 GitHub Release 下载\n"
                    "  --from-dir <目录>     从本地已有的 models/ 拷贝"
                )
            url = f"https://github.com/{repo}/releases/download/{tag}/{name}"
            download(url, dest, spec["size"])
    except RuntimeError as exc:
        print(f"[失败] {name} —— {exc}")
        return "failed"

    actual = sha256_of(dest)
    if actual != expect:
        print(f"[失败] {name} —— 校验不过，已删除")
        print(f"        期望 {expect}")
        print(f"        实际 {actual}")
        dest.unlink(missing_ok=True)
        return "failed"

    print(f"[完成] {name} · {_human(dest.stat().st_size)} · 校验通过")
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="获取并校验模型权重",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--repo", default=os.getenv("YAODAO_REPO"),
                    help="GitHub 仓库 owner/name（也可用环境变量 YAODAO_REPO）")
    ap.add_argument("--tag", default=DEFAULT_TAG, help=f"Release 标签（默认 {DEFAULT_TAG}）")
    ap.add_argument("--from-url", action="store_true",
                    help="从权重源站直接下载（hf-mirror / HuggingFace / GitHub 官方）")
    ap.add_argument("--from-dir", type=Path,
                    help="改为从本地目录拷贝（服务器拉不动外网时用这个）")
    ap.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    ap.add_argument("--force", action="store_true", help="已存在也重新取")
    args = ap.parse_args()

    args.models_dir.mkdir(parents=True, exist_ok=True)
    print(f"目标目录：{args.models_dir}\n")

    results: dict[str, str] = {}
    for name, spec in WEIGHTS.items():
        results[name] = fetch_one(
            name, spec, args.models_dir,
            repo=args.repo, tag=args.tag,
            from_dir=args.from_dir, from_url=args.from_url, force=args.force,
        )

    ok = [n for n, r in results.items() if r == "ok"]
    failed = [n for n, r in results.items() if r == "failed"]

    print(f"\n完成 {len(ok)}/{len(WEIGHTS)}")
    if failed:
        print(f"失败：{'、'.join(failed)}")
        missing_required = [n for n in failed if WEIGHTS[n]["required"]]
        if missing_required:
            print(
                "\n⚠️ 缺的是**必需**权重，后端会以**降级模式**启动 ——"
                "页面上认不出任何病害，且日志里会有一条 warning。"
                "不要就这么上线。"
            )
        else:
            print(
                "\n缺的都是可选权重，后端会正常启动，只是对应能力降级："
                "\n  FastSAM-s 缺 → 定位回落纯 HSV（泥水图上的框会变差）"
                "\n  pest 闸门缺 → 害虫照片报「疑似病斑」而不是「虫害（未定种）」"
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
