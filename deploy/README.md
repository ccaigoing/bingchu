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

### 买哪个地域：**香港**

| | 香港节点 | 大陆节点 |
|---|---|---|
| ICP 备案 | **不需要** | **需要，1–3 周** |
| 域名可用时间 | 买完域名解析即生效 | 要等备案通过 |
| 国内访问延迟 | 30–80ms，够用 | 最快 |
| 月费（2核4G） | ¥30–60 | ¥60–100 |

**备案看的是服务器在不在大陆，不是域名在哪注册** —— 在国内注册的域名解析到
香港服务器，只要完成域名实名认证（几天）就能用，无需 ICP 备案。答辩有截止日期
时，这个差别就是"今天能上线"和"等三周"。

代价：国内访问比大陆节点慢一点（但比美国节点快一个量级），且理论上存在被
墙的风险。对竞赛演示这个量级完全够用。

> 香港节点还有个隐性好处：**拉 GitHub 是通的**，所以 CI、`git pull`、
> 从 Release 取权重都不需要额外折腾代理。

### 开端口

**两处都要开，只开一处是最常见的"部署完了但打不开"**：

1. 云厂商控制台的**安全组 / 防火墙**里放行 80（以及以后接 HTTPS 的 443）
2. 服务器本机的防火墙：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

> 香港节点不备案也能正常用 80，本节照做即可。
> 只有**大陆节点 + 未备案域名**才会被云厂商拦 80/443，那种情况把
> `deploy/nginx.conf` 的 `listen 80;` 改成 `listen 8080;`，
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

> 还没有仓库、或者仓库里没有这三个权重？**先做文末附录第 1 步**
> （建仓库并推代码）—— 那是一次性的准备工作，代码没上云这一步就无从 clone。
> 注意 `models/` 里只有 `README.md`，`.pt` 权重不进版本库，第 4 步单独取。

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

### 方式一：服务器直接从源站下载（推荐）

```bash
cd /srv/yaodao
.venv/bin/python tools/fetch_weights.py --from-url
```

从 HuggingFace / ultralytics 官方直接拉，**不经过 GitHub，也不占用你家宽带的上行**。
每个权重都配了多个源站（hf-mirror 与 HuggingFace 官方），脚本按顺序试、
哪个通走哪个。香港节点国际带宽好，实测 36MB 的权重几秒下完。

### 方式二：从 GitHub Release 下载

```bash
.venv/bin/python tools/fetch_weights.py --repo <owner>/<repo>
```

需要你先按文末**附录**把三个权重传成 Release 资产。**从国内往 GitHub 推 457MB
是最容易卡住的一步**，能走方式一就别走这条。

### 方式三：从本机 scp（服务器连不上外网时用）

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

## 接域名和 HTTPS

香港节点**不需要 ICP 备案**，所以这一步可以当天做完。

### 1. 域名解析

在域名注册商（阿里云/腾讯云/Namesilo 都行）加一条 A 记录：

```
主机记录  @     记录值  <服务器公网IP>     TTL 600
主机记录  www   记录值  <服务器公网IP>     TTL 600
```

**校验**：`ping <你的域名>` 解析出的 IP 是服务器 IP（DNS 生效通常几分钟到几小时）。
**先确认这一步生效再往下走** —— certbot 是靠域名回访验证的，解析没生效必然失败。

### 2. nginx 加上你的域名

把 `deploy/nginx.conf` 里的 `server_name _;` 改成 `server_name <你的域名> www.<你的域名>;`，
然后 `sudo nginx -t && sudo systemctl reload nginx`。

### 3. 申请证书

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <你的域名> -d www.<你的域名>
```

certbot 会自己改写 nginx 配置、加上 443 和 80→443 跳转，并装好自动续期的 timer。

**校验**：

```bash
sudo certbot renew --dry-run        # 模拟续期，应显示成功
curl -I https://<你的域名>           # 应返回 200，且走的是 https
```

> ⚠️ 证书 90 天过期，`certbot` 装的 timer 会自动续，但**别把 nginx 配置改成
> 让 certbot 认不出的样子**（它靠注释标记定位要改的 server 块）。

### 4. 接上域名后要复查一件事

`nginx.conf` 里把访客 IP 传给后端的那行（`X-Forwarded-For $remote_addr`）
不受域名影响，但如果中途加过 CDN（Cloudflare 等），`$remote_addr` 会变成 CDN
的地址，**限流会退化成"所有人共用一个额度"**。加 CDN 的话要改用
`CF-Connecting-IP` 之类的真实来源头，并参见故障表那条"别人能用，你被 429"。

### 还没接域名时

`http://<公网IP>/` 一直是可用的，答辩演示不受影响。域名和 HTTPS 是加分项，不是前置条件。

---

## 附录：把代码和权重放到 GitHub

第 2 步的 `git clone` 需要一个能拉的仓库，这里是一次性的准备。

### 1. 建仓库并推代码

在 GitHub 建一个**空仓库**（不要勾 README / .gitignore / license，否则首次推送会冲突），然后：

```bash
git remote add origin https://github.com/<用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

### 从国内推代码：git 要走代理

直连 github.com 在国内是**间歇性**的 —— 有时 9 秒能通，有时直接
`Recv failure: Connection was reset` 或 `Failed to connect to github.com port 443`。
机器上通常已经跑着代理客户端（Clash 之类），但 Windows 系统代理开关可能是关的，
所以 git 默认不走它。

**用环境变量临时带上代理，别写进 git 全局配置** ——
代理软件一关，写死的 `http.proxy` 会让 git 连任何仓库都失败：

```bash
https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897 \
    git push -u origin main
```

端口按你代理客户端的实际设置改（Clash Verge / mihomo 默认是 7897）。
经代理后实测从 9.5 秒降到 0.3 秒。

> ⚠️ `netsh winhttp show proxy` 显示"无代理"**不代表真的没有** —— 它查的是
> WinHTTP，和浏览器/git 用的 WinINET 不是一回事。要确认代理端口在不在，
> 直接看 `netstat -ano | findstr LISTENING | findstr 7897`。

首次推送会弹出 Git Credential Manager 让你登录 GitHub，选
"Sign in with your browser" 授权一次即可，之后会记住。

**校验**：仓库页面上能看到 `server/ deploy/ src/ tools/`，且 CI 的绿勾出现
（`.github/workflows/ci.yml` 会自动跑前端构建 + 后端导入检查）。

### 2. 把权重传成 Release 资产

三个权重合计 496MB，作为**资产**挂在 Release 下（Release 单文件上限 2GB，
而仓库里单文件只能 100MB，这就是权重不进版本库的原因）。

在 GitHub 网页：**Releases → Draft a new release**

- Tag：`v1.0-weights` —— **必须与 `tools/fetch_weights.py` 里的 `DEFAULT_TAG` 一致**
- 把 `models/jktk_x.pt`、`models/FastSAM-s.pt`、`models/yolo11s-pest-ip102.pt`
  **三个文件**拖进附件区（文件名必须保持原名，脚本按名字拼 URL）
- 发布

> ⚠️ **只传这三个。** `models/insect-detection-yolov8m.pt` 是已否决的候选 B
> （A/B 验证过，见 `models/README.md`），传上去会让"到底用哪版权重"变得不可考。
>
> 457MB 从国内上传可能要很久甚至失败。**如果失败了不必死磕** ——
> 第 4 步的方式一（服务器自己下）和方式三（scp）都不需要这一步。
>
> 以后换权重就换一个 tag（比如 `v1.1-weights`），**别覆盖旧的** ——
> 覆盖会让"服务器上跑的是哪一版"无法追溯。

**校验**：Release 页面三个资产都在，大小分别约 436MB / 23MB / 37MB。
