# qq-st-bot

一个有长期记忆、能主动联系你的私人陪伴型 QQ 机器人。

---

## 特性

**记忆系统**
- 短期对话上下文（滑动窗口）
- `character_growth`：角色对你的长期认知，随对话持续积累
- `event_log`：每日事件日志

**主动触发调度器**
- 早安 / 晚安 / 随机日间碎碎念
- 天气联动（极端天气、好天气氛围）
- 日记提醒、每日手账
- 生日多段触发（前夜预热、零点告白、下午关心、夜间收尾）
- 节日感知 / 时间节点感知 / 长假加速
- 未完结话题追问

**现实数据感知**
- Apple Watch：心率异常提醒、睡眠感知（iPhone 捷径推送）
- Obsidian 日记：定期读取作为对话上下文
- 生理期感知：周期中和临近期自动关心

**对话能力**
- 12 层分层 Prompt 架构（世界书 / 角色卡 / 用户画像 / 实时状态…）
- 图片识别（GLM / Gemini / OpenAI Vision）
- TTS 语音合成（GPT-SoVITS，情绪联动参考音频切换）
- 表情包发送（情绪联动，与 TTS 互斥）
- 工具调用：天气查询、备忘录提醒、网页搜索

**运维**
- Web 管理面板（触发器状态、手动触发、配置热更新）
- 冷却状态持久化（重启不丢失）

---

## 技术栈

Python · FastAPI · NapCat (OneBot 11) · DeepSeek · GPT-SoVITS

---

## 快速开始

**环境要求**

- Python 3.10+
- [NapCat](https://github.com/NapNeko/NapCatQQ)（QQ 协议端）

**安装**

```bash
git clone https://github.com/chah69634-arch/qq-st-bot.git
cd qq-st-bot
pip install -r requirements.txt
```

**配置**

```bash
cp config.example.yaml config.yaml
```

按 [配置指南.md](配置指南.md) 填写必填项：LLM API Key、QQ 号、管理面板密钥。

在 `characters/` 目录放入角色卡 `.txt` 文件（格式见配置指南第 6 节）。

**运行**

```bash
# 1. 启动 NapCat，确保 QQ 已登录，WebSocket 服务端监听 3001 端口
# 2. 启动机器人
python main.py
```

管理面板：`http://127.0.0.1:8080`

---

## 文档

- [配置指南.md](配置指南.md) — 所有配置项说明
- [Watch配置指南.md](Watch配置指南.md) — Apple Watch 心率 / 睡眠数据接入（iPhone 捷径）

---

## 注意

- 仅供个人学习使用
- 需自备 LLM API Key（推荐 DeepSeek，国内直连）
- 角色卡需自行准备，`characters/` 目录有格式示例
- 本项目不包含任何角色版权素材

---

## License

MIT
