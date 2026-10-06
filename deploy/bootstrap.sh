#!/usr/bin/env bash
#
# 「机」到病除 —— 服务器一次性引导脚本
#
#     sudo bash /srv/yaodao/deploy/bootstrap.sh
#
# 把 deploy/README.md 里第 1、3、4、5、7、8 步合成一条命令执行。
# 之所以做成脚本而不是让人一条条抄：这些步骤之间有顺序依赖（建目录要在
# chown 之前、播种只能在装服务之前跑一次），手抄很容易漏掉某一步，
# 而漏掉的表现往往是"服务起来了但某个功能静默失效"，最难查的那一类。
#
# 脚本是**幂等**的：重复跑不会重复播种、不会覆盖已有的库，可以放心重试。
# 每一步都打印结果，中途失败会停下并指出是哪一步 —— 把整段输出发出来即可定位。

set -euo pipefail

# ── 输出小工具 ──
step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER="$REPO/server"
PYBIN=""

[ "$(id -u)" -eq 0 ] || die "请用 sudo 运行：sudo bash $0"
[ -f "$SERVER/app/main.py" ] || die "$REPO 看起来不是本项目（找不到 server/app/main.py）"

printf '\033[1m「机」到病除 —— 部署引导\033[0m\n仓库位置：%s\n' "$REPO"

# ─────────────────────────────────────────────────────────
step "1/8  安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx git curl ca-certificates >/dev/null

# 优先用 3.11（与本地开发和 CI 一致），没有就退回系统自带的 ——
# Ubuntu 22.04 自带 3.10，本项目实测在 3.10 上语法与依赖均无问题，
# 所以这里**不为版本号去加第三方软件源**，那会引入一个额外的失败点。
if apt-cache policy python3.11 2>/dev/null | grep -qE 'Candidate: [0-9]'; then
    apt-get install -y -qq python3.11 python3.11-venv >/dev/null
    PYBIN=python3.11
else
    apt-get install -y -qq python3 python3-venv python3-pip >/dev/null
    PYBIN=python3
fi
ok "nginx $(nginx -v 2>&1 | sed 's/.*\///')"
ok "$($PYBIN --version)  （$PYBIN）"

# ─────────────────────────────────────────────────────────
step "2/8  建虚拟环境并安装 Python 依赖"
[ -d "$SERVER/.venv" ] || "$PYBIN" -m venv "$SERVER/.venv"
VENV_PY="$SERVER/.venv/bin/python"
"$VENV_PY" -m pip install -q -U pip
# 约 1GB（含 CPU 版 torch），国内/香港网络下通常 2–5 分钟，慢是正常的
"$VENV_PY" -m pip install -q -r "$SERVER/requirements.txt"
ok "依赖安装完成"

# torch 装成 CUDA 版是这里最隐蔽的坑：能 import、能跑，只是白白多占 2.5GB 磁盘，
# 而且这台机器根本没有 GPU。requirements.txt 里那条 --extra-index-url 就是防这个。
TORCH_VER="$("$VENV_PY" -c 'import torch; print(torch.__version__)')"
case "$TORCH_VER" in
    *+cpu) ok "torch $TORCH_VER（CPU 版，正确）" ;;
    *)     die "torch 装成了 $TORCH_VER（非 CPU 版）。
   修：$SERVER/.venv/bin/pip uninstall -y torch torchvision
       $SERVER/.venv/bin/pip install -r $SERVER/requirements.txt" ;;
esac

# ─────────────────────────────────────────────────────────
step "3/8  检查后端能否导入"
# 早失败早报错 —— 这里过了，后面 nginx 那一层才值得配
(cd "$SERVER" && "$VENV_PY" -c "import app.main" ) \
    || die "后端导入失败。把上面的报错发出来。"
ok "app.main 导入成功"

# ─────────────────────────────────────────────────────────
step "4/8  取模型权重（约 496MB）"
cd "$REPO"
"$VENV_PY" tools/fetch_weights.py --from-url

# ─────────────────────────────────────────────────────────
step "5/8  准备目录与演示数据"
# 目录必须先建出来，下一步的 chown 才有对象
mkdir -p "$SERVER/static/uploads/orig" "$SERVER/static/uploads/annotated" "$SERVER/data"

# ⚠️ 播种**只在库不存在时**做一次。
#    `python -m app.seed` 默认删库重建（seed.py:654，fresh=not args.keep），
#     再跑一次会把所有访客留下的识别记录全部抹掉。
#    服务启动时只建表不播种（main.py:44），所以漏跑的表现是
#    "7 个屏都在、但图表和列表全是空的" —— 那不是前端坏了。
if [ -f "$SERVER/data/yaodao.db" ]; then
    warn "数据库已存在，跳过播种（这正是想要的行为，不是失败）"
else
    (cd "$SERVER" && "$VENV_PY" -m app.seed)
    ok "演示数据已灌入"
fi

# ─────────────────────────────────────────────────────────
step "6/8  修正权限"
# 后端以 www-data 身份跑（见 yaodao.service），它要能读全部代码，
# 还要能**写**上传目录和 SQLite 目录。
# 漏了写权限的表现很难认：服务能起、页面能开，但一上传照片就 500，
# 报的是 sqlite3.OperationalError 或 PermissionError，看不出是权限问题。
chown -R www-data:www-data "$SERVER/static/uploads" "$SERVER/data"
chmod -R a+rX "$REPO"
ok "www-data 可写 uploads/ 与 data/"

# ─────────────────────────────────────────────────────────
step "7/8  安装 systemd 服务与 nginx 站点"
cp "$REPO/deploy/yaodao.service" /etc/systemd/system/yaodao.service
systemctl daemon-reload
systemctl enable --now yaodao >/dev/null

cp "$REPO/deploy/nginx.conf" /etc/nginx/sites-available/yaodao
ln -sf /etc/nginx/sites-available/yaodao /etc/nginx/sites-enabled/yaodao
# 自带的默认站点会抢 80 端口，必须去掉，否则访问到的是 nginx 欢迎页
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null || die "nginx 配置检查不通过，上面有具体行号"
systemctl reload nginx
ok "yaodao.service 与 nginx 站点已装载"

# ─────────────────────────────────────────────────────────
step "8/8  验证"
# 三个模型加起来要载 1.5GB 左右，冷启动给它留足时间
printf '  等待后端加载模型'
for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
    printf '.'; sleep 2
done
printf '\n'

HEALTH="$(curl -fsS --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
[ -n "$HEALTH" ] || die "后端 10 分钟内没起来。执行 journalctl -u yaodao -n 50 --no-pager 看原因。"

"$VENV_PY" - "$HEALTH" <<'PY'
import json, sys
h = json.loads(sys.argv[1])
m = h["model"]
print(f'  模型   : {m["name"]} · {m["mode"]} · {m["device"]} · {m["classCount"]} 类')
if m["mode"] != "normal":
    print(f'  \033[33m!\033[0m 模式是 {m["mode"]} 而不是 normal —— 有权重没取到：{m["error"]}')
g = h.get("guard")
if g:
    # trackedIps 是**已跟踪的访客 IP 数量**，不是并发数（并发上限在
    # config.INFER_CONCURRENCY，没透出到 health）。这里如实标注，
    # 别让它看着像一个"并发度"指标 —— 那个数字在服务器上应该随着
    # 不同访客增长，一直是 1 就说明 nginx 的 X-Forwarded-For 没生效。
    print(f'  护栏   : {g["perMinute"]} 次/分 · {g["perDay"]} 次/天 · 已跟踪 {g["trackedIps"]} 个访客 IP')
else:
    print('  \033[33m!\033[0m /api/health 里没有 guard 段 —— 跑的不是最新代码？')
PY

echo
curl -fsS -o /dev/null -w '  经 nginx : HTTP %{http_code}\n' http://127.0.0.1/ || \
    warn "nginx 转发失败 —— 可能还没上传前端（见下）"

# ── 前端产物 ──
if [ -f "$REPO/dist/index.html" ]; then
    ok "前端产物已就位（$REPO/dist）"
else
    cat <<'MSG'

  ⚠️ 前端还没上传 —— 现在打开 http://<公网IP>/ 会是 404 / nginx 欢迎页。
     在自己电脑上执行（不是在这台服务器上）：

         cd <项目目录>
         npm run build
         scp -r dist/* root@<公网IP>:/srv/yaodao/dist/

MSG
fi

printf '\n\033[1;32m════════ 引导完成 ════════\033[0m\n'
cat <<'MSG'

  本机自测：curl http://127.0.0.1/api/health
  外网访问：http://<公网IP>/     ← 需先在云厂商控制台的安全组里放行 80
  看日志  ：journalctl -u yaodao -f
  重启后端：systemctl restart yaodao

MSG
printf '  公网 IP ：'
curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || printf '(取不到，去控制台看)'
printf '\n\n'
