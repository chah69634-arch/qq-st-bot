# 功能控制面事实清单（2026-07-13）

管理服务的设置面分三层：

后台练习盲评不属于管理面热更新 API，但其模型选择遵循同一模型路由真值：
`practice.reviewer_category` 是 routing profile category（默认 `consolidation`）；可选旧字段
`practice.reviewer_preset` 是严格的直接 preset 名并优先于 category。未知 preset 会让该次
练习明确失败并进入 scheduler 异常记录，不会静默回落 chat。

所有写入 `config.yaml` 的设置端点统一经过 `admin.config_control`：写请求按进程内锁串行，
用临时文件原子替换，并以读取时快照做三方合并，避免并发设置覆盖无关字段。若待修改字段
在 `config.local.yaml` 中存在覆盖，接口返回 HTTP 409 且不改写 base config；管理面不得把
这种冲突显示为保存成功。local override 仍由部署者直接维护，不通过管理 API 静默删除或改写。

- persona 级：`/settings/model-routing`、`/settings/tts-desktop`、`/settings/tts-auto-play`、`/settings/tool-loop`、`/settings/thinking`、`GET/PUT /output-segment-enforce`，供客户端使用；不返回模型密钥。段落兜底开关热更新 `output.segment_enforce`，只影响发送副本（桌面流式 delta、最终 canonical 与非流式输出），默认关闭。
- admin 专用配置：`/model-presets/*`、`/proxy`、`/tts-config`、`/sticker-config`、`/scheduler/config`、`/settings/relay`、`/settings/mcp`。routing profile 也包含 `sensor_judge`：它是后台裁决专用 category，应映射到稳定的轻量 `chat_completions` preset；缺失时兼容回退 `intent → chat`。该 category 固定使用短 timeout、零 SDK retry 与进程内断路器，未在桌面设置页单独暴露。preset 的 `api_protocol` 由管理面和 `PUT /model-presets/presets/{name}` 管理，取值为 `chat_completions`（默认）或 `responses`；它独立于 `provider_kind` 与 `tool_call_mode`，保存后热重载，不会静默切换 API。
- LLM/model preset/vision/proxy 热重载会等待旧 AsyncOpenAI/httpx client 关闭后再返回；关闭失败
  fail-open 记 warning，旧实例已从 registry 摘除，新请求只会按新配置惰性建 client。
- admin 功能开关白名单：`GET/PUT /settings/feature-flags`。只接受 `settings_feature_flags.FLAGS` 中已有运行时消费者的布尔字段，不接受密钥、路径、额度或任意 YAML。每项返回 `apply_mode` / `restart_required`，PUT 返回 `reload_status` 和本次确实改变且需要重启的字段。`qq.enabled` 只在 `main.py` 启动阶段注册通道、回调和监听任务，因此明确为 `restart_required`，不得显示成热生效；`mail` 及其余逐次读配置的功能仍是 `hot_reload`。`private_exchange.enabled` 与 `qq`/`mail` 两个通道总开关均走这条白名单；desktop/mobile/device 通道没有独立 enabled 字段，是否可用只取决于对应 token 是否配置且未停用。
- admin 配置中心（Brief 93 §1，管理面板「配置」页，`GET/PUT /settings/base-model`、`GET/PUT /settings/embedding`、`GET /settings/setup-status`）：`/settings/base-model` 透明兼容 `model_presets` 主聊天 preset 与旧版 `llm:` 块，由 `_resolve_base_chat_preset_name()` 判定写入目标，不引入第三套真值来源；`/settings/embedding` 读写 `embedding:` 块（缺失时向量召回 fail-open 降级为关键词路径，不算必填）；`/settings/setup-status` 的 `needs_setup` 驱动面板首次登录自动跳转与顶部红色横幅，判定标准是 base_url/api_key/model 三者均非空且不是 `config.example.yaml` 里 `YOUR_`/`YOUR-` 前缀的占位符。
- 密钥本快捷入口（Brief 93 §2，`GET /system/secrets-book`、`POST /system/secrets-book/open`）：仅当请求方 `request.client.host` 是 `127.0.0.1`/`::1`/`localhost` 时可用，用系统默认程序打开 `secrets.local.yaml`；非本机请求悬浮按钮隐藏、`open` 端点直接 403。
- 401 人话化（Brief 93 §6）：`admin/auth.py` 的 401 响应体 `detail` 从纯字符串改为 `{"message", "hint"}`；`/ws/desktop`、`/ws/device` 鉴权失败的 WS close 附带同语义的 `reason`（受 RFC 6455 123 字节上限约束，文案比 HTTP hint 精简）。桌面端 Brief 34 直接透传 `detail.hint` 显示。

模型从 legacy 迁移时调用 `POST /model-presets/bootstrap`，它把现有 `llm` 连接持久化为 `legacy` preset 和 `default` routing profile；之后客户端只切 routing profile，不需要重新录入 API key/base URL。

`/settings/model-routing` 切的是**全局** active_routing；per-角色覆盖是另一条入口：
`GET/PATCH /character/{char_id}/model-routing`（persona 级，Brief 87）读写角色卡
`presence_ext.model_routing`，绑定对象是 routing profile 整体（不支持绑定单个 preset），
`null` 或字段缺失才表示清除声明、回落全局；`"default"` 是一个真实的 profile 名，和其他字符串 profile 一样会固定绑定角色。可选 profile 清单走 `GET /model-presets/routing-profiles`
（persona 级，不含 api_key/base_url）。管理面 `GET /model-presets` 会附带当前活动角色的有效固定绑定（若有），在切换全局路由时明确提示该角色不受影响。跨群一致——不做 per-group override。

`presence_ext.tool_loop` 是角色卡级 Path C 覆写，不经设置 API：`"on"` 在全局
`tool_loop.enabled=false` 时仍为该卡开启多步工具循环，`"off"` 强制关闭，缺失或非法值回落全局。
全局 `tool_loop.total_timeout_s` 控制单轮工具循环的总墙钟预算，默认 300 秒；管理面可调范围为 5–720 秒。
它仍要求 owner 私聊与当前 chat preset 的 `tool_call_mode=function_calling`；角色卡不能借此绕过
工具暴露分类或危险工具排除。`examples/assistant.example.json` 展示人机直连组合，普通角色卡未声明时
继续遵从全局默认关闭。

Path A 没有独立通道开关：QQ、desktop、mobile 都经 `core.pretool_router.route_pretool()`；类别由入口
固定为 QQ/mobile `info`、desktop `info + desktop`。显式快速路径白名单当前仅 `get_time`，不由设置页
或工具 keywords 扩大；Path C 激活时只跳过普通 probe，快速成功会从本轮 loop schema 排除同名工具。

TTS 有三个层次的开关：`tts.enabled` 是服务端能力总开关；`tts.desktop_enabled` 是旧桌面语音条显示兼容项，并与 `tts.auto_play.desktop_pet` 双向同步；`tts.auto_play` 则按 `chat`、`dream`、`video_call`、`desktop_pet`、`mobile` 独立决定客户端是否自动请求/播放，全部默认关闭。`GET/POST /settings/tts-auto-play` 是该落盘状态的读回观测面。桌面设置页提供已接入语音条的聊天与桌宠气泡开关，并在收到回复后实际自动合成播放。`POST /tts/synthesize` 只在能力总开关开启且 persona 鉴权通过时按需合成，接受可选 `scene`（旧客户端可省略），并在合成前移除中英文括号中的旁白/动作描写；返回 base64 WAV。手机轮询消息只携带 `voice_available` 轻量标记，绝不携带音频本体；手机端在本机“自动播放语音”开启时，以该标记按需请求并播放音频。管理面“观测 → 资源完整性”分别报告 TTS 服务就绪和桌宠手动语音条可用性；前者为关闭时，后者即使单独开启也会明确报告为不可合成。

TTS provider 由管理面（admin token）经 `GET/PUT /tts-config` 管理：`tts.provider` 当前支持 `gsv` 与明确标注为预留的 `openai_compatible`，每个 provider 可放在 `tts.providers.<provider>`。`GET` 会分别返回各 provider 的脱敏参数块，面板切换 provider 时显示对应参数且保存互不污染；预留 provider 在面板禁用，绝不猜测或发起云厂商请求。GSV 可选 `gpt_model_path` / `sovits_model_path`，留空时分别切回 v3 / v2ProPlus 默认底模；模型切换是 GSV 服务的全局状态，后端会把切换与同次合成串行化，路径错误时自动回退对应底模。GSV 默认启用后端分句：清洗控制/格式字符并识别实际、字面 `\\n` 与 `/n` 换行，按 `。！？；……` 优先切分，只有超过 `segment_max_chars`（默认 42）才在逗号或破折号处兜底；每段以 GSV `不切` 请求、按中文/英文脚本选择语言模式，再校验 PCM WAV 参数并插入 `segment_pause_seconds`（默认 0.25 秒）静音拼接。`external_segment_enabled: false` 可临时恢复 GSV 内部切分。旧有顶层 GSV 字段（`api_url`、`ref_audio`、情绪参数等）会自动映射，保持已有本地 GPT-SoVITS 部署行为不变。`POST /tts-config/test` 只试听已就绪 provider，`GET /observability/api-calls?caller=tts` 可查询最近合成结果与失败类别（`state.read`）。

视觉模型不进 LLM 的 `routing_profiles`：通用图片识别使用 `GET/PUT /vision-params` 的 `vision:` 块；手机自动化可通过 `GET/PUT /vision-params/phone-control` 管理 `phone_control_vision:` 覆盖。两个控制卡片归在管理面的“模型路由”页，接口、落盘语义和热重载保持不变。后者只保存显式填写的字段，空字段会删除覆盖并继承通用视觉配置；保存后热重载。`/phone_control/status` 继续按合并后的 `base_url` 与 `model` 判断 `vision_configured`。

表情包由管理面（admin token）经 `GET/PUT /sticker-config` 管理：`sticker.enabled` 是总开关，`sticker.trigger_prob` 是 0–1 的每轮独立触发概率。缺失该配置块时保持兼容行为（启用、0.06）；关闭时不会发送或广播表情包。TTS 的概率单独掷骰，不会抢占或缩减表情包的配置概率。GET 返回当前有效值，兼作该落盘配置的只读观测面；若已命中概率但目标情绪目录无图，服务端会记录目录路径以便排查。

MCP server 由管理面（admin token）经 `GET/PATCH /settings/mcp`、`POST /settings/mcp/test`、
`POST /settings/mcp/import`、`PATCH /settings/mcp/{name}` 和 `DELETE /settings/mcp/{name}` 管理。URL 导入必须先完成
`initialize + list_tools` 测试才写入配置；URL 导入可选 `streamable-http`（推荐）或 `sse`，而配置文件也可声明
`stdio`；旧 `http` 配置继续按 `streamable-http` 处理。HTTP endpoint URL 与 headers 都支持 `${ENV_VAR}` 展开：
服务商使用路径认证时可将敏感路径段写为 `${MCP_TOKEN}`，缺失变量会 fail-closed；管理面不回显字面 URL
路径或 header 值。MCP 不继承环境代理：loopback/localhost 地址始终直连，远程地址可在管理面单独设置
`use_proxy`，启用后使用全局 `proxy.http` / `proxy.https`。删除会立即断开该 server 并摘除它的动态工具；总开关同步所有 session，单 server 的启停/白名单只重载该 server；工具调用以
`caller=mcp__{server}__{tool}` 记录到 API 调用总账。`tool_timeout_s` 是 server 默认值，`tool_timeouts_s.<tool>` 可为个别工具覆盖 1-660 秒的调用上限；设置读取接口会返回两者，更新会热重载对应 server。动作工具超时会记录相同 `request_id` 并返回 `outcome_unknown`，不会自动重放。工具策略新增 `unrestricted`（面板显示“无限制执行”）：管理员选择时强制显式幂等、跳过确认，并以同一 `request_id` 最多重连重试三次。`tool_policy.<tool>.ui_label` 是可选的本地瞬态展示标签（1-48 字符），仅供已配对桌面端的 NOW 状态使用；它不影响权限、确认、重试或调用参数，缺失时统一显示“外部工具”，不会回显远端工具名、说明、参数或结果。

后端管理面 MCP 页的 Tool-call Console 仅通过 admin-only 的 `POST /settings/mcp/console/invoke` 与
`POST /settings/mcp/console/confirm` 调用。路由只接受当前已连接、有效 allowlist、已注册且本地 policy 已确认的动态工具，并在服务端以工具的 JSON Schema 校验参数；绝不接受任意 MCP method 或 server command。它复用 `tool_dispatcher.execute(origin="admin_console")`、effect/确认门、每工具超时和 MCP API 调用总账，不直接触碰 session；高危调用返回一次性确认票据（120 秒、仅原工具原参数可确认）。控制台响应和总账以 `audit_id` 关联，且总账不记录 arguments 或返回正文。桌面客户端不代理 MCP 管理调用、配置或密钥。

每个 MCP server 可保存命名的 `tool_presets`（每项是一组工具白名单）和当前 `active_tool_preset`。选择预设会将该工具集写回运行时实际使用的 `allow_tools` 后热重载；手工改复选框则回到“自定义”选择，避免悄悄改写命名预设。开启 `require_local_policy` 时，`allow_tools` 仍是唯一运行时白名单；管理面 URL 导入和普通白名单保存会在工具探测成功后为新白名单工具写入本地默认 `tool_policy`，保留已有显式策略。MCP annotations（`readOnlyHint` / `destructiveHint`）或名称和描述只能影响默认 effect 建议，不能授予远端权限或自动开启确认：未知语义落为 `write + require_confirm: false`。管理页逐工具“每次执行前确认”复选框显式保存 true/false；导入、普通保存和批量默认授权都只补缺失字段，不覆盖已有选择。无法从当前运行时快照补齐策略时，严格写入会被拒绝，不会注册或调用。保存时会清理已移出白名单的策略项。单 server 保存向对应 owner task 发送重载信号，失败时 API 返回 `reload_status=restart_required`，管理面提示重启。

管理面「运维 → 工具」经 admin-only `GET/PUT /settings/tools` 统一观察内置已注册工具、保存命名的 `tool_loop.tool_presets`，并把预设绑定到 `model_presets.presets.<name>.tool_preset`。该预设只收窄该聊天模型收到的内置 function schema，且不替代 `tools.<name>.enabled` 全局执行闸门。未绑定模型明确显示为「全局默认」：勾选并保存会把内置工具选择编译为全局 `tool_loop.categories` / `exclude_tools` 并热更新；面板未表示的类别与排除项会原样保留。MCP 在此页只显示全局启用状态，动态工具目录、连接与配置仍不由此页维护。删除工具预设会同步清除引用它的模型绑定。

LLM 请求快照是独立的高敏感调试开关：管理面 MCP 页通过 admin-only 的
`GET/PUT /llm-debug-requests` 控制 `llm_debug_requests.enabled` 与 `keep_days`（1–7，默认关闭/1 天）。
开启后，`core/llm_client.py` 会在实际请求发出前记录 messages、tools 与生成参数；疑似密钥字段和
`data:image/...` 二进制数据会被遮蔽。读取只能经 admin-only 的
`GET /observability/llm-debug-requests`，并可经同为 admin-only 的 `DELETE /observability/llm-debug-requests` 主动清空；不可复用普通 `state.read` API 调用总账权限。它只应用于短时
排查，关闭后不再产生新快照，既有快照按保留期自动轮转清理。

降级路径：关闭对应功能布尔值时保留其余配置；tool loop 回到普通单次回复，thinking 回到无前置思考，桌面 TTS 回到纯文字，生成后段落兜底关闭后直接发送清理后的模型原文，模型可切回稳定 routing profile。

内置唤醒由 `GET/PATCH /admin/autonomy/config` 与 `GET/PATCH /admin/autonomy/tools` 控制，配置和有限运行记录按 owner/角色写入独立 autonomy state，不写入 `config.yaml`。默认关闭；启用后的 job 仍只由现有 scheduler tick 消费。全局已连接的只读 MCP 工具会直接进入自主工具面，但仍必须通过全局启用、MCP local policy、Self Capability 的有效授权与动态注册检查；写入工具继续要求 autonomy allowlist 和代码审查的 sandboxed write（当前为花园浇水）。`manage_self_capability` 只在存在可由角色修改的、用户已授权且未锁定的能力时暴露。每次 run 会保存只读记忆、最近五轮和基础角色描述组成的 prompt 快照；普通运行列表不返回快照，只有 `GET /admin/autonomy/runs/{run_id}/prompt`（`admin` scope）可读取。关闭开关会停止新的 autonomy run，不会改变普通聊天 tool loop、Wake Bridge 或现有 scheduler trigger 的行为。

Self Capability P0 uses `GET /admin/self-management` and fixed `POST` actions for grants, locks, restore, and undo. Its durable state and audit are scoped by `uid + char_id` under the runtime sandbox, separately from autonomy state and `config.yaml`. The global `self_management.enabled` master switch is exposed in System Status -> Feature switches and is hot-reloaded. When off, stored agent overrides are dormant, the management gateway is hidden, and agent requests are rejected; user grants and audits remain intact for a later re-enable. The panel returns capability IDs, status, constraints, revisions, and audit metadata only; it never returns MCP URLs, headers, tokens, or raw tool results. Agent mutations use the internal `manage_self_capability` gateway and require a user grant, `mutable_by_agent`, an unlocked capability, a current revision, and an idempotent action ID. During an autonomy run, the gateway is exposed only while a mutable capability exists; every model step rebuilds the effective schema, and every requested call is checked against that current allowlist before dispatch. Self-management calls use `autonomy_self_management`; business calls use `autonomy_loop`, and the two origins are not interchangeable. Audit records correlate the run/job/action IDs while the autonomy tools endpoint reports the safe final decision matrix. The effective runtime decision still intersects global availability and every existing dispatcher/autonomy gate.
# MCP 批量授权补充（Brief 135）

MCP 管理页的 server 卡片提供“默认授权全部”和“无限制授权全部”两个 server 级动作。
它们分别发送一次 `PATCH /settings/mcp/{name}`，请求体只允许
`{"bulk_authorize":"default"}` 或 `{"bulk_authorize":"unrestricted"}`；服务端从当前连接态
`list_tools()` 快照生成白名单，写入一次并热重载一次。响应的 `processed_count`、最终白名单、
policy 和 `reload_status` 是管理面的唯一状态来源；未连接或没有工具目录时按钮禁用并显示原因。

严格本地策略通过 `GET /settings/mcp` 返回的 `require_local_policy` 显示。严格模式空白
`allow_tools` 是零授权；legacy 非严格模式才保留空白即全开的兼容语义。
