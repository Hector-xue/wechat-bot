# 微信机器人（Linux WeChat Bot）

基于 Linux 版微信客户端的群聊机器人：页面捕获 + LD_PRELOAD 进程拦截 + 内存密钥定位 + 消息库解密 + OCR + LLM 判官 + 群聊分析流水线。

> ⚠️ 本项目涉及对微信客户端的进程级操作（内存读取 / LD_PRELOAD 拦截 / 代码注入 hook）。仅用于学习研究，请自行评估并承担合规与账号风险。

## 目录结构

| 目录 | 说明 |
|------|------|
| `wx-linux/` | 主项目：实时机器人、守护、分析流水线、内存/密钥/解密工具 |
| `wxgroup-bot/` | 独立简化版群聊机器人（不依赖微信 GUI，用 `--mock` 可离线测试） |

## 工作原理（简述）

```
微信客户端(Linux) ──LD_PRELOAD 拦截/页面捕获──► 消息
        │
        ├─ 内存扫描(memscan) 定位 SQLCipher 密钥
        ├─ wd/ 解密 messages.db
        └─ OCR / 直接读取消息原文
                 │
                 ▼
        判官 / 敏感词 / 人设 / LLM
                 │
                 ▼
              发送回复
```

## 主要组件

| 文件 | 作用 |
|------|------|
| `wxbot_run.py` / `wxbot.py` | 实时机器人入口 / 主逻辑 |
| `wxguard.py` | Xvfb + 微信 24×7 守护 |
| `wxpipe.py` | 定时入库 + 增量分析流水线 |
| `wxhealth.py` | 状态面板 |
| `wxanalyze.py` `wxreport.py` `wxdaily.py` `wxnames.py` `wxnews.py` `wxcomic.py` | 分析 / 报告 / 日报 / 昵称 / 新闻 / 漫画 |
| `sniffer.c` → `sniffer.so` | LD_PRELOAD 拦截库：pread 抓明文页 + pwrite 抓调用栈 |
| `memscan.c` → `memscan` | 内存扫描器：定位 AES/SQLCipher 密钥候选 |
| `btprobe.c` / `memcpy_probe.c` | 进程探针 |
| `wd/` | 微信 DB 解密与密钥定位工具 |
| `gdbsniff*.py` / `gdbpage*.py` | gdb 辅助脚本 |
| `pageparse.py` `findtext.py` `ocrtest.py` `ocrbench.py` | 页面解析 / 找字 / OCR |
| `qrserve.py` | 二维码服务 |
| `deploy/` | systemd 服务模板 |

## 依赖

### 系统
- Linux 微信客户端（xwechat）
- Python 3.12
- Xvfb + X11（GUI 自动化）
- OpenSSL 开发头（`openssl-devel` / `libssl-dev`，仅编译 `memscan` 需要）
- systemd（可选，用于服务化部署）

### Python
```bash
cd wx-linux
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 编译 C 工具

```bash
make -C wx-linux
```

## 配置

编辑 `wx-linux/config.json` 和 `wx-linux/wbot.json`，填入你自己的：

- 目标群 / 会话名
- 机器人人设（persona）
- LLM `base_url` / `api_key` / `model`
- 冷却、频率、静默时段等行为参数

> 所有配置字段当前都是占位符，请按需替换。

## 部署（systemd）

1. 参考 `wx-linux/deploy/*.service`，把其中的路径改成你的实际安装路径。
2. 安装并启用：

```bash
sudo cp wx-linux/deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wxguard wxbot wxpipe wxhealth
```

## 离线测试（wxgroup-bot）

`wxgroup-bot` 提供了不碰微信、不花钱的离线模拟：

```bash
python wxgroup-bot/wx_group_bot.py --mock wxgroup-bot/mock_chat.txt --offline
```

## 更多设计文档

- `wx-linux/ANALYSIS.md` — 项目深度分析与落地路线图
- `wx-linux/docs/PLAN-inline-hook.md` — 毫秒级消息接管的 inline hook 技术方案

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
