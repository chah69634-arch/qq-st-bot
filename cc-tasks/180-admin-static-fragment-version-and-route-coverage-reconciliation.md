# Brief 180: Admin 静态 fragment、资源版本与路由覆盖总账对齐

## 背景

Admin 静态测试集中出现 9 个失败：导航参数缺失、脚本 query version 过期、runtime signals 页面标记缺失、
fragment 数量由 42 变 44、残留 inline style、孤立 utility CSS、overview 版本缺失，以及
`POST /integrations/garden/test-wake` 未被 UI 引用或白名单登记。

这些问题应按当前页面真值更新清单，不能只把测试中的 42 改成 44 后结束。

## 施工范围

- 盘点 `admin/static/pages/` 全部 fragment 与 `index.html` placeholder/navigation，恢复 memory 导航参数及
  runtime-signals 的 `data-page` 接线。
- 移除页面 fragment 中的 `style=""`，迁移为有实际消费者的语义 class；删除确已无消费者的
  `admin-inline-*` 规则，不保留僵尸 CSS。
- 按 AGENTS.md 同步：页面 fragment 改动时更新 `ADMIN_UI_FRAGMENT_VERSION`、`core.js?v=`；直接加载的
  `character.js`、`overview.js` 使用与测试/brief 对齐的新显式版本。
- 将 fragment 测试从脆弱的固定总数改成“目录、placeholder、导航、loader 集合相等”或同步正式 manifest，
  防止以后每新增页面都遗漏一处常量。
- 对 `POST /integrations/garden/test-wake` 做产品判断：需要管理员操作则补 UI、鉴权、结果反馈和 i18n；仅为
  内部/自动测试则加入带理由的 route coverage whitelist。不得无理由静默豁免。
- 执行三面闭环检查，核对客户端是否也消费 runtime signals/garden wake 状态；未覆盖项按规则写入两个总账。

## 验收

- 本次列出的 Admin 测试全部通过。
- 页面无 inline style/onclick；CSS orphan 审计通过。
- 静态 cachebuster 全部同步；本地启动后目检导航、lazy fragment、只读 runtime signals 与 garden test-wake。

