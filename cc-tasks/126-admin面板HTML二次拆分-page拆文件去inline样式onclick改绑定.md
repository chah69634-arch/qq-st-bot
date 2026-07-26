# Brief 126 · admin/static/index.html 二次拆分：page 拆文件 + 去 inline style + onclick 改事件绑定

写于 2026-07-25，茶茶反馈。上一轮拆分（Brief 119）已经把 CSS 挪到 `style.css`、JS 按
功能域拆成 `admin/static/js/*.js`（13 个文件，7328 行），但 `index.html` 本身还是
2015 行的单文件，里面塞满了 33 个 page 区块、425 处内联 `style="..."`、204 个
`onclick="fn()"`。GPT 建议的方向是对的：内联样式散落各处，以后调主题/改 UI 观感每次
都要满文件 grep，风险和成本都在放大；`onclick` 内联绑定不算错误但不是长期维护友好的
写法。这次做第二轮拆分，只动这三件事，不做无关重构。

## 目标（三条规则，缺一不可）

1. **page 拆文件**：按 `<div class="page" id="page-xxx">` 边界，把 33 个页面区块的
   HTML 移到独立文件（建议 `admin/static/pages/*.html` 或按功能域归组，比如
   `admin/static/pages/observe-*.html` 一组、`admin/static/pages/status.html`、
   `admin/static/pages/character.html`……具体怎么分组参考 Brief 119 里 JS 拆分时
   已经形成的功能域边界，两边尽量对齐，例如 `observability.js` 对应的那些
   `observe-*` 页面应该拆进同一批文件，不要两边分组标准不一致）。
2. **去掉 inline style**：把 425 处 `style="..."` 迁移成 `style.css` 里的具名 class。
   不要求每处样式都做到语义化命名，但要求：
   - 相同/相近的样式组合合并成同一个 class（比如很多地方反复出现的
     `style="font-size:12px;color:var(--muted)"`，应该抽成 `.text-muted-sm` 之类的
     公共 class，而不是拆分后原样保留成 33 个文件各自的内联样式）。
   - `style.css` 里已有的 CSS 变量（`var(--muted)`、`var(--accent)`、`var(--border)`
     等）继续用，不要在拆分过程中把这些变量替换成写死的颜色值。
3. **onclick 改事件绑定**：204 处 `onclick="fn()"` 改成 JS 里 `addEventListener`
   绑定（拆分后每个页面文件对应的加载函数里，给该页面内的按钮/元素统一走
   `element.addEventListener('click', fn)`，而不是 HTML 属性内联调用）。

## 三条规则的验收标准 + 一个具体样例（TTS 配置卡片）

用 `page-status` 里的"TTS 配置"卡片（`admin/static/index.html` 现在的第 566-609 行
左右，`status.tts.title`）作为改造样例，因为它同时踩中三条规则：

```html
<!-- 现状（拆分前）-->
<div class="card">
  <div class="card-header">
    <h3 data-i18n="status.tts.title">TTS 配置</h3>
    <button class="btn btn-ghost btn-sm" onclick="loadTtsConfig()" data-i18n="common.refresh">刷新</button>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
    ...
  </div>
  <button class="btn btn-primary btn-sm" onclick="saveTtsConfig()" data-i18n="common.save">保存</button>
  <button class="btn btn-ghost btn-sm" onclick="testTtsConfig()" data-i18n="status.tts.test">试听当前 Provider</button>
  <button class="btn btn-ghost btn-sm" onclick="loadTtsCallLog()" data-i18n="status.tts.call_log">最近合成记录</button>
</div>
```

拆完之后应该长这样（示意，不是精确要求逐字符匹配）：

- HTML（挪进 `admin/static/pages/status.html` 或对应文件）：
  ```html
  <div class="card">
    <div class="card-header">
      <h3 data-i18n="status.tts.title">TTS 配置</h3>
      <button class="btn btn-ghost btn-sm" data-action="load-tts-config" data-i18n="common.refresh">刷新</button>
    </div>
    <div class="row-inline row-gap-md row-mb-14">...</div>
    <button class="btn btn-primary btn-sm" data-action="save-tts-config" data-i18n="common.save">保存</button>
    <button class="btn btn-ghost btn-sm" data-action="test-tts-config" data-i18n="status.tts.test">试听当前 Provider</button>
    <button class="btn btn-ghost btn-sm" data-action="load-tts-call-log" data-i18n="status.tts.call_log">最近合成记录</button>
  </div>
  ```
- CSS（`style.css` 新增）：`.row-inline{display:flex;align-items:center;} .row-gap-md{gap:12px} .row-mb-14{margin-bottom:14px}`
  （或等价的合并方案，命名不强制照抄）。
- JS（`admin/static/js/status-users.js` 里，页面加载函数中做绑定，不要用
  `document.querySelectorAll('[data-action]')` 全局代理绑定——这个文件里的按钮分布
  在很多不同页面，全局代理容易在页面切换时重复绑定或漏绑定，按每个页面自己的加载
  函数各自绑定更安全）：
  ```js
  function bindTtsConfigActions() {
    document.querySelector('[data-action="load-tts-config"]')?.addEventListener('click', loadTtsConfig);
    document.querySelector('[data-action="save-tts-config"]')?.addEventListener('click', saveTtsConfig);
    document.querySelector('[data-action="test-tts-config"]')?.addEventListener('click', testTtsConfig);
    document.querySelector('[data-action="load-tts-call-log"]')?.addEventListener('click', loadTtsCallLog);
  }
  ```
  并在该页面对应的 `goto()` loader（`core.js` 的 `loaders` 表）里首次进入时调用一次
  `bindTtsConfigActions()`——注意页面可能被反复 `goto()` 进入，绑定函数要么做幂等
  处理（先 `removeEventListener` 再 `addEventListener`，或者用一个 `_bound` 标记位
  防止重复绑定），要么把绑定挪到页面 HTML 首次注入 DOM 时只执行一次，不要跟着每次
  `goto()` 都重新绑一遍导致同一个点击触发 N 次回调。

## 硬约束（不能破的红线，抄自 Brief 119，依然有效）

- 拆分本身不产生任何功能性 diff——不改变任何 DOM id/class/data-* 属性、不改变任何
  API 调用、不改变任何页面的渲染结果。`data-i18n` / `data-i18n-placeholder` 和
  `i18n.js` 的对应关系不能动。
- 本轮新加的 `data-action` 属性只是 onclick 迁移的中间产物，不是必须项——如果某处
  改绑定后发现用 `data-action` 属性 + 统一代理更省事，也可以直接在拆分后的 JS 文件
  里对已知的固定 DOM 结构用 `document.getElementById(...)` /
  `querySelector(...)` 精确绑定，不强制统一走 `data-action`。
- 所有函数依然要保持全局可访问（拆分后的 JS 文件继续用普通 `<script src=...>` 引入，
  不要改成 `type="module"`，否则会破坏尚未来得及迁移的、仍然依赖全局函数名的代码）。
- `admin/static/index.html` 拆分后只保留 nav 骨架 + 每个 page 的 `<div id="page-xxx">`
  占位容器，页面内容通过 fetch/include 或构建时拼接的方式注入——具体用哪种机制（纯
  静态文件没有原生 include，需要接手时定一个方案：可以是简单的 fetch 拉页面片段插入
  DOM，也可以是加一个轻量构建脚本在部署前把分片文件拼回一个 `index.html`，二选一，
  但要写清楚部署/开发流程有没有因此多一步）。
- **本次也要覆盖 2026-07-25 当天新加的三块面板**（资源完整性 `page-observe-resource-
  completeness`、API 契约检查 `page-observe-api-contract`、角色权限
  `page-observe-char-permissions`，都在 `core/resource_completeness.py` /
  `core/api_contract_check.py` / `core/character_permissions.py` 对应的观测面板，
  代码集中在 `admin/static/js/observability.js` 文件末尾）——这三块是最新加的，
  内联样式和 onclick 用得最密集，不要因为"新加的就先跳过"漏掉，否则刚拆完又立刻
  多出一批需要二次处理的内联样式。

## 验收

1. `pytest -n auto`（或至少 `pytest -n auto tests/test_admin_mcp_ui.py` 以及任何
   断言 `index.html`/静态资源内容的测试）全过，需要的话同步改测试读取路径，改成
   读取拆分后的多个文件拼起来判断。
2. 管理面板启动后，nav 里全部页面（含新拆分出的文件）能正常 `goto()` 切换、按钮
   点击都能正确触发对应函数，浏览器 console 里过一遍确认没有 `onclick is not a
   function` / 找不到 DOM 元素之类的报错。
3. 视觉抽查：随机挑 5-6 个页面（包括这次新加的三块观测面板）截图对比拆分前后，
   确认布局、间距、颜色没有跑偏（inline style 迁移成 class 最容易在这一步出偏差）。
4. 更新 `AGENTS.md`（如果里面提到 admin 面板的文件结构说明）以及本文件所在目录下
   如果有维护中的架构说明文档，反映拆分后的新文件布局。

## 备注

这个仓库的协作偏好和红线写在 `AGENTS.md`（Codex 默认读取的入口）；`CODEX.md` 是
`CLAUDE.md` 的兼容镜像，两者冲突时以 `AGENTS.md` 为准。跟 Brief 119 一样，这是体力活
为主、不太需要架构判断的执行工作，适合丢给额度充足的执行者；但这次牵涉到给 204 个
`onclick` 一一改绑定，逐个核对容易漏，建议做完后写一个小脚本 grep 一遍
`index.html`（以及拆出去的文件）确认不再有残留的 `onclick="` 字符串，作为自查手段。
