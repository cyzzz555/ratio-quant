# 全局 UI 与 K 线标志更新 · 2026-10-12

本次仅更新已有十个页面的视觉与导航呈现。左上角 Q 替换为自制矢量蜡烛 K 线与波动轨迹标志，浏览器 favicon 使用同一资产。

## 设计参考

参考 [Apple iOS 27 页面](https://images.apple.com/os/ios/) 与 [Apple Materials 指南](https://developer.apple.com/design/human-interface-guidelines/materials)：导航使用半透明材质、背景柔和渐变、圆角浮层与胶囊控件；行情表格与图表使用较实的阅读底层。属于 Web 视觉适配，不宣称复刻原生 Liquid Glass 光学效果。

## 文件变更

- frontend/public/quant-mark.svg：原创矢量 K 线品牌标志。
- frontend/index.html：favicon、安全区域 viewport 与 theme-color。
- frontend/src/main.tsx：十个导航 SVG 图标、工作空间栏、安全详情入口、键盘跳过导航。
- frontend/src/style.css：全局设计变量、导航、卡片、表单、表格、图表、弹窗、日志、桌面/手机布局；减少动态与提高对比度适配。
- frontend/src/ResearchChart.tsx：统一图表网格、坐标、涨跌与权益曲线颜色。
- frontend/src/ResearchDesk.tsx：行情周期加入可见标签，调整控件布局。
- 本报告及 ui_redesign_validation_2026-10-12.json：实际验证记录。

没有新增外部 UI 依赖，没有修改交易计算、持仓、审批、数据库或风险参数。

## 运行

在项目目录双击 `启动研究工作台.command`，或在现有本机服务运行时打开 http://127.0.0.1:5173/#market 。本次已重启 Vite；原页面刷新即可载入新版。生产构建执行 `cd frontend && pnpm build`。

## 实际验证

- Ruff：通过；mypy：34 个源文件通过。
- pytest -m 'not network' -q：215 passed，4 skipped，1 deselected；1 条现有 Starlette/httpx 弃用提示。
- pnpm test：5 passed；pnpm build：TypeScript 通过，Vite 40 modules 构建通过。
- 浏览器分别在 1280px 桌面与 390px 手机宽度遍历十个页面：文档宽度等于视口宽度，无页面横向溢出；表格和手机导航在自身容器滚动。
- 美光中文搜索匹配 MUUSDT；回测 SPCX 搜索匹配 SPCXUSD1 / SPCXUSDT。
- 中文名、研究模式与删除窗口均实际打开后取消；没有改名或删除研究记录。
- 风险模式窗口 Esc 关闭后焦点返回原按钮；跳过导航保留当前研究路由并聚焦内容。
- 公共行情实际返回并绘制 90 根闭合 K 线；没有伪造行情。

本地截图保存在项目之外的 `../ui-redesign-evidence/`，不随 Git 上传：overview-desktop.png、market-desktop.png、risk-mobile.png、mode-dialog.png、name-dialog.png、research-mode.png、record-delete-dialog.png。

## 边界与遗留

LIVE_TRADING_ENABLED=false、HUMAN、PAPER_BROKER 保持不变；微资金 50% 本金亏损容忍、常规 10–20x 与最高 25x 单仓偏好未变更。其他候选风险参数未获实盘授权。

PostgreSQL 未配置，本次 4 项数据库集成测试跳过；不代表完整 P1/P2/P3 验收。快速切换行情页面时，已有请求串行保护可返回 HTTP 409「行情请求正在进行」；请求完成后刷新可显示真实行情。本次未更改此接口行为。

浏览器验证过程中公共探测输出可能被本地使用者更新；该类运行快照不纳入本次 UI 提交，保留在本机。
