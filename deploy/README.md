# 部署手册

把整套系统搬到一台公网服务器上，长期公开可访问。按顺序照抄即可，每步都给了
校验方法 —— **不要跳步往下走**，前面一步没验就做后面，出错时排查范围会翻倍。

---

## 0. 前置：买什么样的机器

| 项 | 要求 | 为什么 |
|---|---|---|
| 内存 | **4GB 起** | torch + YOLO11x 权重常驻约 1.0–1.5GB。2GB 会在加载模型时被 OOM killer 杀掉，现象是"服务反复重启" |
| CPU | 2 核 | 单次识别实测 300–500ms，2 核够用 |
| 磁盘 | 40GB 起 | 依赖约 2GB + 权重 519MB + 前端 + 上传图 |
| 系统 | Ubuntu 22.04 / 24.04 | 本文按 Ubuntu 写；CentOS 要换包管理器命令 |

阿里云/腾讯云「轻量应用服务器」2核4G 大约 ¥60–100/月，学生认证通常有折扣。

> ⚠️ **别买 2核2G**。省下的钱会在第一次上传照片时以 OOM 的形式还回来。

### 开端口

**两处都要开，只开一处是最常见的"部署完了但打不开"**：

1. 云厂商控制台的**安全组 / 防火墙**里放行 80（以及以后接 HTTPS 的 443）
2. 服务器本机的防火墙：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

> 未备案域名时，部分云厂商会拦截 80/443。被拦的话改用 8080：
> 把 `deploy/nginx.conf` 的 `listen 80;` 改成 `listen 8080;`，
> 访问地址相应变成 `http://<IP>:8080/`。

---

## 1. 装系统依赖

```bash
sudo apt update
sudo apt install -y nginx git python3.11-venv python3-pip
```

**校验**：`nginx -v` 有版本输出，`python3.11 -V` 显示 3.11.x。

---

## 2. 拉代码

```bash
sudo mkdir -p /srv/yaodao
sudo chown -R "$USER":"$USER" /srv/yaodao

git clone <你的仓库地址> /srv/yaodao
cd /srv/yaodao
```

**校验**：`ls /srv/yaodao` 能看到 `server/ deploy/ src/ models/ tools/`。

---

## 3. 装 Python 依赖

```bash
cd /srv/yaodao/server
python3.11 -m venv .venv
.venv/bin/pip install -U pip -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

> **预计下载 1GB 出头**（含 CPU 版 torch）。用阿里云镜像能快很多；
> 清华 pypi 对本项目实测返回 403，别用。
>
> `requirements.txt` 顶部有一行 `--extra-index-url` 指向 PyTorch 官方 CPU 源 ——
> **别删**。删了会把 CUDA 版 torch 和一堆 nvidia-* 轮子拉下来（多 2.5GB），
> 而这台机器没有 GPU，白占磁盘。

**校验**（确认装的是 CPU 版，不是 CUDA 版）：

```bash
.venv/bin/python -c "import torch; print(torch.__version__)"
```
输出应形如 `2.6.0+cpu`。**如果显示 `2.6.0` 不带 `+cpu`，说明装成了 CUDA 版**，
`pip uninstall -y torch torchvision` 后重装。

---

## 4. 取模型权重

权重不进版本库（436MB 超 GitHub 单文件上限），必须单独取。

### 方式一：从 GitHub Release 下载（正规路径）

```bash
cd /srv/yaodao
.venv/bin/python tools/fetch_weights.py --repo <owner>/<repo>
```

### 方式二：从本机 scp（服务器拉不动 GitHub 时用）

国内服务器拉 GitHub 经常很慢或超时。你的电脑上权重已经是好的，直接传最快：

```bash
# 在你自己的电脑上（Windows 的 git-bash 里）：
scp models/jktk_x.pt models/FastSAM-s.pt models/yolo11s-pest-ip102.pt \
    <用户>@<服务器IP>:/srv/yaodao/models/

# 然后回到服务器：
cd /srv/yaodao
.venv/bin/python tools/fetch_weights.py --from-dir /srv/yaodao/models
```

**校验**：三个都显示 `校验通过`，最后一行是 `完成 3/3`。
脚本会对每个文件算 SHA256 比对，**校验不过的会被删掉并报错**，不会留下损坏的权重。

---

## 5. 灌入演示数据 —— ⚠️ **只跑一次**

```bash
cd /srv/yaodao/server
.venv/bin/python -m app.seed
```

**校验**：输出末尾会列出各表行数，`disease_classes` 等表都不为 0。

> ### ⚠️⚠️ 这一步跑完就**再也不要跑**
>
> `python -m app.seed` **默认删库重建**（`seed.py:654`，`fresh=not args.keep`）。
> 它能给你一个干净的演示数据基线，代价是**把已有的识别记录全部抹掉** ——
> 包括所有访客上传留下的记录。
>
> - 想补数据而不是重建：`python -m app.seed --keep`（只往空表里补）
> - 服务启动时**不会**自动播种（只有 `init_db()` 建表，见 `main.py:44`），
>   所以**漏跑这一步的表现是：7 个屏都有，但所有图表和列表全是空的**。
>   那不是前端坏了，是没数据。

---

## 6. 构建前端并上传

前端在**你自己的电脑上**构建，再把产物传上去 —— 服务器上为一件事装整个
Node 工具链不划算。

```bash
# 在自己电脑的项目根目录：
npm ci
npm run build
scp -r dist/* <用户>@<服务器IP>:/srv/yaodao/dist/
```

如果服务器上还没建这个目录，先 `mkdir -p /srv/yaodao/dist`。

**校验**：`ls /srv/yaodao/dist` 能看到 `index.html` 和 `assets/`。

---

## 7. 权限

后端以 `www-data` 身份运行（见 `yaodao.service`）。它需要：

- **读**整个 `/srv/yaodao`（代码、venv、dist）
- **写** `server/static/uploads`（存上传图和标注图）
- **写** `server/data`（SQLite 库和它的 -wal / -shm 附属文件）

```bash
sudo chown -R www-data:www-data /srv/yaodao/server/static/uploads \
                                /srv/yaodao/server/data
sudo chmod -R a+rX /srv/yaodao
```

> 漏了写权限的表现：服务能起来、页面能打开，但**一上传照片就 500**，
> 日志里是 `sqlite3.OperationalError: unable to open database file`
> 或 `PermissionError`。这两个错都指向目录权限，不指向代码。

---

## 8. 装服务

```bash
# 后端
sudo cp /srv/yaodao/deploy/yaodao.service /etc/systemd/system/yaodao.service
sudo systemctl daemon-reload
sudo systemctl enable --now yaodao

# nginx
sudo cp /srv/yaodao/deploy/nginx.conf /etc/nginx/sites-available/yaodao
sudo ln -sf /etc/nginx/sites-available/yaodao /etc/nginx/sites-enabled/yaodao
sudo rm -f /etc/nginx/sites-enabled/default   # 去掉自带的默认站点，否则它会抢 80
sudo nginx -t && sudo systemctl reload nginx
```

**校验**：

```bash
systemctl status yaodao --no-pager     # 应为 active (running)
journalctl -u yaodao -n 30 --no-pager  # 应看到三个模型"就绪"
```

日志里应该有三行，缺哪行就是哪块能力降级了：

```
检测模型就绪: jktk_x.pt (116 类, ...)
定位分割就绪: FastSAM-s.pt
虫害闸门就绪: yolo11s-pest-ip102.pt (102 类, conf>=0.50, ...)
```

**出现 `warning` 而不是 `info` 就是降级**，回去查第 4 步。

---

## 9. 验证

在**另一台设备上**（手机开 4G 就行，别用本机浏览器 —— 本机可能走了缓存或回环）
打开 `http://<公网IP>/`：

| # | 操作 | 期望 |
|---|---|---|
| 1 | 打开首页 | 7 个屏都能切换，KPI 数字和图表**有内容**（全空 = 第 5 步没做） |
| 2 | 上传一张水稻病害照 | 出标注图 + 类别 + 置信度 + 建议措施 |
| 3 | 上传剖茎幼虫照 | 报「虫害（未定种）」，框圈住虫体 |
| 4 | **刷新页面** | 刚才那次识别出现在记录表里（证明真的写库了，不是前端内存） |
| 5 | 访问 `/api/health` | `model.mode` 是 `normal`，且返回里有 `guard` 段 |

**护栏验证**：

| # | 操作 | 期望 |
|---|---|---|
| 6 | 用脚本连发 20 次 `POST /api/detect` | 第 16 次起返回 429 + `RATE_LIMITED` |
| 7 | 换一台设备（换 IP）再发 | **不受影响**。若也被拒 → `X-Forwarded-For` 没生效，见故障表 |
| 8 | 同时开 5 个上传 | 变慢但都成功，不会超时失败 |

**韧性验证**：

| # | 操作 | 期望 |
|---|---|---|
| 9 | `sudo systemctl restart yaodao` | 自动恢复，**记录和图片都还在** |
| 10 | 把某个权重改名后重启 | 服务照常起（一条 warning），对应能力降级，**页面不白屏** |
| 11 | `sudo reboot` | 全自动恢复，不需要人工登录做任何事 |

---

## 10. 日常运维

```bash
# 看日志（最常用）
journalctl -u yaodao -f

# 改了代码之后
cd /srv/yaodao && git pull
sudo systemctl restart yaodao

# 改了前端之后（在自己电脑上）
npm run build && scp -r dist/* <用户>@<服务器IP>:/srv/yaodao/dist/

# 临时调护栏参数（不用改代码）
sudo systemctl edit yaodao       # 加 [Service] Environment=RATE_PER_MIN=30
sudo systemctl daemon-reload && sudo systemctl restart yaodao
```

**改配置不用改代码**：`RATE_PER_MIN` / `RATE_PER_DAY` / `INFER_CONCURRENCY` /
`UPLOAD_RETENTION_DAYS` / `CLEANUP_INTERVAL_HOURS` / `CORS_ORIGINS` 都读环境变量，
默认值写在 `server/app/config.py` 里（每一条都注了取值依据）。

---

## 故障排查

| 现象 | 多半是 | 怎么办 |
|---|---|---|
| 页面打得开，图表全空 | 第 5 步没做 | 跑一次 `python -m app.seed`（**只在首次部署时**） |
| 上传照片报 500 | 目录权限 | 回到第 7 步，确认 `uploads/` 和 `data/` 可写 |
| 刷新子页面（如 `/monitor`）就 404 | nginx 少了 SPA 回退 | 检查 `try_files $uri $uri/ /index.html;` |
| **别人能用，你被 429** | `X-Forwarded-For` 没生效 | 见下 |
| 服务反复重启 | 内存不够 | `journalctl -u yaodao \| grep -i "killed"`，确认机器是不是只有 2GB |
| 日志里模型是 `warning` | 权重没取全 | 回第 4 步，`fetch_weights.py` 会告诉你缺哪个 |
| 图片显示不出来但记录还在 | 过期清理删了图 | 正常行为，`UPLOAD_RETENTION_DAYS` 控制保留天数 |

### 关于 `X-Forwarded-For`

配置是对的（`nginx.conf` 里用 `$remote_addr` **覆盖**而不是 `$proxy_add_x_forwarded_for`
追加），但如果表现是"所有人都被同一个额度限制"，说明后端读到的还是 `127.0.0.1`。

验证方法：连续请求几次后看 `/api/health` 的 `guard.trackedIps` ——
它应该随着不同访客**增长**；一直是 1 就说明所有请求被算成了同一个 IP。

> 顺便说明为什么 yaml 里**不用** `$proxy_add_x_forwarded_for`（那是 nginx 文档
> 里更常见的写法）：它的语义是 `$http_x_forwarded_for, $remote_addr`，
> 也就是把**访客自带**的 XFF 头原样接在最前面。访客只要自己发一个
> `X-Forwarded-For: 1.2.3.4` 就能伪造限流键，每次换一个假 IP，
> 限流形同虚设。我们前面没有别的代理，直接覆盖成真实对端地址才对。

### 关于单进程

`yaodao.service` 里**刻意不加 `--workers`**。原因不是性能偏好：

- `services/guard.py` 的限流计数和推理信号量都是**进程内**的，多 worker
  会让实际额度变成 N 倍 —— 护栏名义上还在、实际已经失效
- 每个 worker 都要把 436MB 权重载进内存，2 核机器开两个直接 OOM

要改成多进程，必须先把这两样换成 Redis 之类的共享存储。

---

## 以后要接域名和 HTTPS

现在能做到"所有人可见"了，但地址是 `http://<IP>/`。接域名要做两件事：

1. **ICP 备案**（国内服务器的硬要求，通常 1–3 周）
2. 备案通过后装 certbot 申请证书，`nginx.conf` 里加 443 server 块并 301 跳转

在那之前 `http://<IP>:8080/` 或 `http://<IP>/` 是可用的，答辩演示不受影响。
