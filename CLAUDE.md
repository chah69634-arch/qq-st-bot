# QQ-ST-Bot Claude Code 项目说明

## 使用规则
- 只读取和修改任务明确指定的文件
- 不扫描整个项目目录
- 每次修改后只跑指定的验证命令，不跑main.py除非明确要求

## 环境
- Python：C:\Users\10434\AppData\Local\Python\pythoncore-3.14-64\python.exe
- pip：完整路径 + --break-system-packages
- Windows命令：findstr不用grep，dir不用ls，PowerShell单行命令

## 代理坑（重要）
本地请求必须绕过系统代理：
- requests：proxies={"http": None, "https": None}
- aiohttp：trust_env=False + TCPConnector(ssl=False)
- httpx：trust_env=False（llm_client.py已处理）

## 项目结构（关键文件）D:\ai\qq-st-bot
├── main.py
├── config.yaml
├── core/
│   ├── pipeline.py          # 四步核心，轻易不动
│   ├── prompt_builder.py    # prompt分层注入
│   ├── llm_client.py        # LLM调用唯一出口，async chat()
│   ├── qq_adapter.py
│   ├── tool_dispatcher.py   # 工具注册和执行
│   ├── error_handler.py
│   └── memory/
│       ├── short_term.py
│       ├── event_log.py
│       ├── character_growth.py
│       └── user_profile.py
├── admin/
│   ├── admin_server.py      # FastAPI路由注册
│   ├── static/index.html    # 唯一前端文件
│   └── routers/             # 各功能路由文件
└── characters/
└── 叶瑄.txt             # 当前角色卡，Markdown格式

## 已冻结模块（不要调用，不要修改）
- core/pet.py
- core/memory/user_profile.py 中的affection相关函数
- admin/routers/memory.py 的affection接口
- 前端中宠物页、与叶瑄页、群聊蒸馏（已隐藏，不删除）

## Prompt注入顺序
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

## 添加新工具
在core/tool_dispatcher.py里：
1. 写async _xxx_wrapper()函数
2. 在_TOOL_REGISTRY注册，包含func/description/dangerous/parameters

## 添加新路由
1. 在admin/routers/新建xxx.py，定义router = APIRouter()
2. 在admin/admin_server.py里import并include_router

## 数据文件路径
- data/profiles/{uid}.json — 用户画像
- data/event_log/{uid}/ — 对话日志
- data/character_growth/ — 叶瑄视角印象
- data/diary_context/ — 日记上下文
- data/jailbreak_entries.json — 破限条目

## 验证命令格式
```bashpython3 -c "from core.xxx import yyy; print('ok')"
python3 -c "from admin.routers.xxx import router; print('ok')"

## config.yaml关键字段
```yamlmax_tokens: 1500
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

## 桌宠端接口（Emerald-Desktop共享后端）
- POST /desktop/chat — 气泡回复
- POST /desktop/trigger — QQ在前台时走NapCat
- POST /agent/think — agent loop纯LLM推理

## 角色卡说明
- 格式：Markdown（.txt后缀）
- 路径：characters/叶瑄.txt
- {{user}}为用户名占位符，加载时自动替换

## 前端说明
- 唯一前端文件：admin/static/index.html
- 隐藏（不删除）：宠物页、与叶瑄页、群聊蒸馏