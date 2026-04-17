# QQ-ST-Bot Claude Code Skill

## 使用规则
- 只读取和修改任务明确指定的文件
- 不扫描整个项目目录
- 每次修改后只跑指定的验证命令，不跑main.py除非明确要求

## 项目结构（关键文件）
```
D:\ai\qq-st-bot\
├── main.py
├── config.yaml
├── core/
│   ├── pipeline.py          # 四步核心，轻易不动
│   ├── prompt_builder.py    # prompt分层注入
│   ├── llm_client.py
│   ├── qq_adapter.py
│   ├── scheduler.py         # 主动行为调度器
│   ├── tool_dispatcher.py
│   ├── error_handler.py
│   └── memory/
│       ├── short_term.py
│       ├── event_log.py
│       ├── character_growth.py
│       └── user_profile.py  # 画像部分保留，affection已冻结
├── admin/
│   ├── admin_server.py
│   ├── static/index.html    # 唯一前端文件
│   └── routers/
│       ├── character.py
│       ├── lorebook.py
│       ├── scheduler.py
│       ├── watch.py
│       ├── settings_llm.py
│       ├── settings_misc.py
│       └── ...
└── characters/
    └── 叶瑄.txt             # 当前角色卡，Markdown格式
```

## 已冻结模块（不要调用，不要修改）
- core/pet.py
- core/memory/user_profile.py 中的affection相关函数
- admin/routers/memory.py 的affection接口
- 前端中宠物页、与叶瑄页、群聊蒸馏（已隐藏，不删除）

## Prompt注入顺序（修改prompt_builder时参考）
- 层0: 破限预设（可选）
- 层1: 角色卡
- 层2: 用户关系
- 层3: 用户画像
- 层4: 世界书
- 层5: 角色成长记忆
- 层6: 事件日志
- 层7: 对话示例
- 层8: 短期历史
- 末尾: chat.style模式指令

## 验证命令格式
每次改完只跑被改到的模块：
```bash
python3 -c "from core.xxx import yyy; print('ok')"
python3 -c "from admin.routers.xxx import router; print('ok')"
```
不要每次都跑main.py，除非改动涉及启动流程。

## config.yaml关键字段（当前值）
```yaml
max_tokens: 1500
chat:
  style: roleplay
  mode: roleplay
proxy:
  enabled: false
tts:
  enabled: false
admin:
  enabled: true
scheduler:
  enabled: true
```

## 角色卡说明
- 格式：Markdown（.txt后缀）
- 路径：characters/叶瑄.txt
- 加载方式：character_loader.py检测后缀，txt/md直接整体读入作为description
- {{user}}为用户名占位符，加载时自动替换

## 前端说明
- 唯一前端文件：admin/static/index.html
- 标签页分组：
  - 🎭 叶瑄：角色卡、世界书、调度器
  - 🔧 工具：工具管理、错误日志
  - 👥 用户：用户管理、关系配置、黑名单
  - ⚙️ 系统：QQ设置、系统状态、系统设置
- 隐藏（不删除）：宠物页、与叶瑄页、群聊蒸馏
