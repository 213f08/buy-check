# 部署上线指南（博客可挂的在线体验版）

目标：把「买前尽调」部署到一个**公网可访问的 URL**，博客文章里直接放链接给评委点。

---

## 0. 两条路线怎么选

| 路线 | 成本 | 稳定性 | 适合 |
|---|---|---|---|
| **A. 腾讯云轻量应用服务器**（推荐） | 约 ¥50–112/月（活动新用户更低） | 高，24h 在线 | 正式参赛、评委随时能点 |
| B. 本机 + 内网穿透（cpolar / frp / ngrok） | 0 元 | 低，断网/休眠就挂 | 只在发文前临时演示 |

> 建议：发文期间用 A；比赛结束后随时销毁，按量计费花不了多少钱。
> 用 **IP 直连不上域名**，可以规避大陆服务器「域名需备案」的问题。

---

## 1. 路线 A：腾讯云轻量服务器部署（约 30 分钟）

### 1.1 准备（你需要做的）

1. 注册腾讯云账号并**实名认证**；
2. 控制台搜索「**元宝搜索**」→ 开通服务（每月 2000 次免费调用）；
3. 「访问管理 → API 密钥管理」创建密钥，拿到 `SecretId` / `SecretKey`；
4. 购买一台**轻量应用服务器**（Ubuntu 22.04，最低配即可），记下公网 IP；
5. 防火墙放行端口：`8010`（或你自定义的端口）。

### 1.2 上传代码（在服务器上执行）

```bash
# 方式一：git（推荐，先把代码推到你的 GitHub/Gitee 私有仓库）
git clone https://github.com/213f08/buy-check.git
cd buy-check

# 方式二：本地 scp 上传
# scp -r buy-check/ ubuntu@你的IP:~/
```

### 1.3 配置环境

```bash
cd ~/buy-check
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # 可选：仅 AK/SK 模式需要 SDK；API Key 模式零依赖可跳过

# 写入密钥与配置（不要提交到 git）
cp .env.example .env
vim .env   # 填入 YUANBAO_API_KEY，并把 HOST 改为 0.0.0.0
```

`.env` 关键项（**两种密钥二选一，推荐 API Key**——控制台「元宝搜索 → 服务 API KEY」获取，`sk-` 开头）：

```ini
# 方式一（推荐）：服务 API KEY，零依赖直连
YUANBAO_API_KEY=sk-你的KEY

# 方式二：腾讯云 AK/SK 签名（需 pip install -r requirements.txt）
# TENCENTCLOUD_SECRET_ID=你的ID
# TENCENTCLOUD_SECRET_KEY=你的KEY

MOCK=0
HOST=0.0.0.0
DAILY_LIMIT=60
CACHE_TTL=3600
```

### 1.4 先手动跑一次

```bash
python3 server.py 8010
# 本地验证：
curl http://127.0.0.1:8010/api/health
# 应返回 {"ok": true, "mode": "live", ...}
```

浏览器打开 `http://你的公网IP:8010` 能看到页面即成功。

### 1.5 systemd 常驻（防止 SSH 断开服务就停）

```bash
sudo tee /etc/systemd/system/buycheck.service > /dev/null <<'EOF'
[Unit]
Description=BuyCheck - purchase due diligence demo
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/buy-check
EnvironmentFile=/home/ubuntu/buy-check/.env
ExecStart=/home/ubuntu/buy-check/.venv/bin/python server.py 8010
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now buycheck
sudo systemctl status buycheck   # 确认 active (running)
```

> 注意：`server.py` 用 `os.getenv` 读环境变量，`EnvironmentFile` 恰好按 `.env` 的 `KEY=VALUE` 格式注入，无需改动代码。

### 1.6 （可选）nginx 反代到 80 端口

```bash
sudo apt install -y nginx
sudo tee /etc/nginx/sites-available/buycheck > /dev/null <<'EOF'
server {
    listen 80 default_server;
    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/buycheck /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

之后直接访问 `http://你的公网IP`（不带端口）。

---

## 2. 路线 B：本机 + 内网穿透（0 元，临时演示）

```bash
# 本机
python server.py 8010

# cpolar / ngrok 任选其一
ngrok http 8010      # 得到一个临时公网 URL
```

缺点：链接会变、断网即失效。**发文时不要用这种链接**，除非发文当天你会一直开着电脑。

---

## 2.5 路线 C：Docker 一条命令（有 Docker 的机器首选）

```bash
cp .env.example .env    # 填入 YUANBAO_API_KEY
docker compose up -d --build
# 打开 http://服务器IP:8010
```

镜像基于 `python:3.11-slim`，项目零依赖所以构建秒级完成；`./data` 目录挂载到宿主机，额度计数在容器重启后不丢。

---

## 3. 上线安全清单（务必逐条核对）

- [ ] 密钥只存在于服务器的 `.env`，**源码、截图、博客里都不出现**；
- [ ] `.gitignore` 已包含 `.env` 和 `data/`（已内置）；
- [ ] `DAILY_LIMIT` 已设置（默认 60 份/天），防止评委集中点击刷爆免费额度；
- [ ] `CACHE_TTL` 开启（同一机型 1 小时内不重复扣额度，已内置）；
- [ ] 每 IP 限流已开启（`RATE_LIMIT_PER_MIN=20`，默认内置，POST 接口生效）；
- [ ] 请求体上限已开启（`MAX_BODY_BYTES=64KB`，默认内置）；
- [ ] 安全响应头已内置（nosniff / DENY / Referrer-Policy）；
- [ ] 降级策略确认：密钥失效/网络故障时，报告仍能以精选数据模式输出（已内置，页面会显示提示）；
- [ ] 页面底部有免责声明（价格仅供参考，以面交验机为准）。

---

## 4. 额度账本（心里有数）

| 项 | 数值 |
|---|---|
| 免费额度（基础） | 2000 次/月 |
| 免费额度（核销邀请码后） | **6000 次/月**（活动专区填邀请码，+4000，2026.10.10–11.30） |
| 单份报告消耗 | 3 次搜索（每机型 1 次，命中缓存不计） |
| `DAILY_LIMIT=60` | 每天最多烧 180 次；核销后月耗 5400 次以内都安全 |
| 缓存命中 | 同机型 1 小时内重复报告 = 0 消耗 |
| 超额保护 | 当天额度用完自动降级为精选数据模式，服务不中断 |

> 个人账号（TOC）免费额度仅限极速版 / 标准版；本文使用的服务 API KEY 模式在覆盖范围内。
> 如果预期流量大（比如文章上了热门），可在腾讯云控制台购买资源包（极速版 14 元/千次）兜底。

---

## 5. 部署后验收清单

- [ ] `http://IP/api/health` 返回 `"mode": "live"`；
- [ ] 生成一份「二手相机」报告，行情卡下方出现**实时行情线索**（带可点击的来源链接与抓取时间）；
- [ ] 1 小时内对同一机型重复生成，报告头部显示「缓存」标记，且额度计数不增加；
- [ ] 手动把 `DAILY_LIMIT` 临时调成 0 再请求，页面出现「额度已用完」降级提示；
- [ ] 手机浏览器打开页面排版正常。
