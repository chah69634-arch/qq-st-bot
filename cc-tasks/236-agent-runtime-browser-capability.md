# Brief 236：浏览器自动化与凭据边界

> 状态：proposal；前置：230、233；最高风险能力之一，不能与 workspace/process 工单并行上线。

## 目标

让角色可以在隔离浏览器中执行受控网页操作，同时不把密码、cookie、token 或浏览器 profile 直接交给模型。

## 设计约束

- 独立浏览器 profile、独立 worker 和独立 task receipt。
- 模型只能看到页面的 bounded 可见内容和结构化操作结果。
- 登录由用户在浏览器中完成，或由凭据代理执行；模型不得读取秘密。
- 导航域名、下载目录、上传文件和操作类型分别 allowlist。
- 登录、支付、发帖、删除、发送邮件、改密等动作必须显式确认。
- 结果未知时不得自动重试可能产生副作用的动作。
- Dream 默认不能访问浏览器能力和 Reality 登录态。

## 验收

- 无 token/cookie/password 出现在 prompt、日志、receipt 或观测端点。
- 浏览器任务可暂停、取消、过期和人工接管。
- 下载/上传必须经过 workspace capability，不得任意读写宿主路径。
- remote_server 默认禁用本地浏览器控制，除非另有明确远程浏览器部署合同。

