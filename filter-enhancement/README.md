# Filter Enhancement（过滤器增强）插件

将 `ljili1/NagramXF` 仓库 12.10.1 分支上的「过滤器增强」补丁（提交 `67b0380c` + `533af9af`）
移植为 `Keeperorowner/NagramXF` 的 Python 插件（exteraGram 式插件 SDK）。

- 插件文件：`filter_enhancement.py`（单文件，无外部依赖）
- 插件 ID：`filter_enhancement`，版本 1.0.5
- 目标宿主：Keeperorowner/NagramXF **plugin 构建**（dev 分支，`min_version = 12.2.10`）

## 一、功能对照

| # | 原补丁功能（Java） | 插件实现 | 钩子点 |
|---|---|---|---|
| 1 | 被过滤消息显示为可点击占位条（视图类型 -1001，替代直接消失） | 一致 | `ChatActivity$ChatActivityAdapter.getItemViewType` / `onCreateViewHolder` |
| 2 | 连续占位条合并为「N 条消息被隐藏」单条 | 一致（可选关闭） | `onBindViewHolder` |
| 3 | 点击占位条恢复显示整段消息（原内容原样渲染） | 一致 | `ChatActivity.createMenu`（6 参，主路径） |
| 4 | 长按占位条弹出「过滤原因」（命中片段） | 一致 | `ChatActivity.createMenu`（6 参，主路径） |
| 5 | 「收起」悬浮按钮，一键重新隐藏全部已恢复消息 | 一致（可选关闭） | `ChatActivity.createView` |
| 6 | 链接预览（URL/站点名/标题/简介）参与正则匹配 | 一致（可选关闭） | `MessageHelper.getMessageFilterMatchText` |
| 7 | 编辑消息后立即重新判定过滤结果（按内容失效缓存） | 一致 | `MessageObject.checkLayout` + `AyuFilterCache.invalidate/invalidateGroup`（反射） |
| 8 | 切换过滤开关立即刷新已打开聊天 | 一致 | `AyuFilter.invalidateFilteredCache`（后置补发 `regexFiltersUpdated` 通知） |
| 9 | 移除 shadow-ban 链式隐藏（`isShadowBannedPeerChain`） | 默认移除，可开关恢复上游 | `AyuFilter.isShadowBannedPeerChain`（私有静态，前置拦截） |

## 二、与原实现的差异与取舍

1. **相册/删除线相关字段未移植。** `filterGroupStruck`、`filterMergeHidden` 在 12.10.1 终态中
   仅被 `applyFilterMerge()` 复位、无任何写入路径（连续删除线合并已在该版本移除），
   属于死代码，插件不复制。
2. **占位条文案为插件内置中英文**（按系统语言自动选择）。插件无法注册 `R.string` 资源，
   文案与原补丁的 `FilterHiddenHint` 等字符串逐字一致。
3. **过滤原因的命中区间由 Python 端复算**（镜像 `AyuFilter.getMatchedRanges`：共享规则 −
   会话排除 + 会话级规则，含 `RegexFiltersEnableInChats` 判定与区间合并）。Java 与 Python
   正则语法存在细微差异，极个别规则（如 Java 专有语法）的区间显示可能不同；隐藏/恢复
   的主流程判定始终走宿主 `AyuFilter` 本身，不受影响。
4. **反射依赖。** 插件需访问 `this$0`、`hideFilteredMessages`、`messagesStartRow/EndRow`
   等私有成员。若宿主版本混淆策略变化导致反射失败，对应钩子静默降级为上游原生行为，
   不会造成崩溃（全部钩子均有 try/except 保护并输出日志）。
5. **`getMatchedStruckText` 未移植。** 该 API 服务于已移除的删除线展示，终态无调用方。
6. **维护须注意：占位条根视图必须保持不可点击。** 原 Java 补丁是在 `FilterHiddenView`
   内部自行处理触摸（宿主不给它派发条目点击），插件没有独立 View 类，只能依赖
   RecyclerListView 的条目分派。一旦占位条变为 clickable，宿主会跳过手势检测器
   （详见下文 v1.0.5），点击与长按将同时失效。改动 `_build_placeholder_view` 或
   行内监听器挂载逻辑时务必保持该约束。

## 三、配置项（插件设置页）

| 开关 | 默认值 | 说明 |
|---|---|---|
| 显示被过滤消息占位条 | 开 | 对应原补丁 `RegexFiltersShowPlaceholder`（默认 true）。关闭后恢复为直接隐藏。 |
| 合并连续占位条 | 开 | 连续被隐藏的消息合并为一条；点击一次恢复整段。 |
| 显示「收起」悬浮按钮 | 开 | 有已恢复消息时显示底部「收起」按钮。 |
| 链接预览内容参与匹配 | 开 | 链接预览字段纳入正则匹配范围。 |
| 恢复链式屏蔽（上游行为） | 关 | 开启后恢复上游 shadow-ban 链式隐藏。 |

每个开关变更后立即失效缓存并刷新所有已打开聊天。

## 四、安装与启用

**前提**：安装 Keeperorowner/NagramXF 的 **plugin 构建**（带 Python 插件引擎的版本；
normal 构建中 `PluginsController` 为空壳，无插件功能）。

1. 将 `filter_enhancement.py` 传输到手机（任意目录）。
2. 打开 NagramXF → **设置 → 插件（Plugins）** → 选择 **安装插件 / 从文件安装**，
   选中 `filter_enhancement.py`。宿主会校验元数据并把文件复制为
   `plugins/filter_enhancement.py`。
3. 在插件列表中打开 **Filter Enhancement** 的启用开关。
4.（可选）进入该插件的设置页按需调整上述开关。

备选安装方式：部分构建支持将文件重命名为 `filter_enhancement.plugin` 后作为文档
发送到任意聊天，点击该文档即可触发安装弹窗（`PluginsConstants.PLUGINS_EXT = ".plugin"`）。

**过滤规则本身仍在原处维护**：Nagram 设置 → 过滤器（Regex Filters）。本插件只增强
展示与匹配行为，不接管规则的增删改。

## 五、卸载与回退

- **临时回退**：关闭插件启用开关即可，所有钩子停止生效，行为回到上游原生。
- **完全卸载**：在插件列表中删除插件。卸载时自动摘除全部 Xposed 钩子、移除悬浮按钮
  并清理全部运行时状态；插件设置文件 `plugins/filter_enhancement/settings.json` 一并失效。

## 六、故障排查

- **插件设置页内置「钩子状态」行**（10 个钩子应全部安装成功）。若有缺失，该行会红色标注
  实际数量；缺失时对应功能自动降级为上游原生行为，请截图该行并反馈宿主版本号。
- **「交互诊断」行**：显示两级钩子的安装状态、**钩子被调用次数**、占位条创建/绑定次数、
  点击与长按命中次数。三种情形可直接区分：
  - 安装正常但「钩子被调用 = 0」→ 触摸未派发到拦截点（宿主分派路径不同，或行被误置为可点击）；
  - 「被调用 > 0 但命中 = 0」→ 派发到达但行未被识别（`_views` 注册/父链解析问题）；
  - 「命中 > 0」→ 功能正常。
  反馈时请附该行截图与日志中 `filter_enhancement` / `createMenu hook invoked` 相关行。
- 插件日志经宿主 `AppUtils.log` 输出，前缀 `[filter_enhancement]`；可用日志工具检索。

### 已修复的历史问题

**v1.0.5 — 占位条必须不可点击（第三轮真机日志确诊的最终根因）**

第三轮日志证明 v1.0.4 的拦截层本身是健康的：

```
D/AppUtils: hooks installed: 10/10
D/AppUtils: listener hooks (secondary path): click=True long=True
```

`createMenu`（6 参）主钩与两个匿名监听器钩**全部安装成功、零异常**，却**没有任何点击/长按命中记录**——说明触摸根本没有派发到这些方法。根因在宿主触摸派发的入口，而非拦截点：

`RecyclerListView$RecyclerListViewItemClickListener.onInterceptTouchEvent()` 在 `ACTION_DOWN` 时做两件事：

```java
childEvent = MotionEvent.obtain(0, 0, action, x - left, y - top, 0);
if (currentChildView.onTouchEvent(childEvent)) interceptedByChild = true;   // ①
...
if (currentChildView != null && !interceptedByChild) {
    gestureDetector.onTouchEvent(event);                                   // ② 唯一喂手势检测器处
}
```

- `View.setOnClickListener()` 会把视图置为 `clickable`，而 **clickable 视图的 `onTouchEvent()` 对合成 DOWN 返回 `true`** → ① 置 `interceptedByChild = true` → ② 被跳过。
- 手势检测器是**唯一**触发 `onSingleTapUp` / `onLongPress` 的地方，跳过即意味着
  `onItemClickListener` / `onItemLongClickListener` 永不派发，`createMenu` 也永不调用。
- 结果：**占位条照常渲染，点击与长按同时全死，且日志全静默**——正是上报症状。
- 姊妹插件 `filter-sentinel` 的提交 `v2.4.0: bar must stay non-clickable` 即同一结论。

修复：占位条根视图**不再挂载** `OnClickListener` / `OnLongClickListener`，并显式
`setClickable(False)`（内层 `hint` TextView 一并显式置否——同一处判定还会检查行的
**直接子视图**是否 clickable）。交互统一由列表层拦截点（`createMenu` 主路径 +
匿名监听器次级路径）承接；只有当两级列表层钩子**都**不可用时，才回退到行内监听器，
此时会打日志说明。

诊断升级：设置页「交互诊断」行新增「钩子被调用次数」与「占位条创建/绑定次数」。
由此可一次判定三种情形——`钩子被调用=0`（触摸未派发至拦截点）、`被调用>0 但命中=0`
（行未被识别）、`命中>0`（功能正常）。日志中对应新增
`createMenu hook invoked (first call)`、`list item click hook invoked (first call)`、
`placeholder view created (first)…clickable=False`、`placeholder bind recognised (first)`。

**v1.0.4 — 交互拦截改挂在 `createMenu` 汇聚点（点击/长按仍无效的根因收敛）**

v1.0.3 把拦截挂在 `ChatActivity` 的两个匿名监听器实例上，存在两处结构性弱点：

1. **安装点被早退/异常吞掉。** `_install_listener_hooks` 原本写在
   `_after_create_view` 的「收起」悬浮按钮创建之后，而该方法在此之前有多个
   `return`（按钮已挂载、`contentView`/`context` 取不到），并且整段包在同一个
   `try/except` 内——按钮构建任一环节抛异常，安装调用就会被整体跳过。结果是
   **占位条照常显示、点击与长按同时静默失效**，与上报症状完全吻合。
2. **依赖匿名类的字段名。** `onItemClickListener` / `onItemLongClickListener`
   是包级私有字段，宿主版本若改为内联 lambda 或改名，反射返回 `None`，
   同样只影响交互、不影响占位条。

修复（分层，逐级降级）：

- **主路径**：钩 `ChatActivity.createMenu(View, boolean, boolean, float, float, boolean)`
  ——两种手势的汇聚点。RecyclerListView 的触摸派发最终都会走到它：
  点击 -> `createMenu(view, true, false, x, y, false)`；
  长按 -> `createMenu(view, false, true, x, y, true)`。
  它是 `ChatActivity` 自有私有方法（非匿名类成员），**插件加载时即可安装**，
  不需要 `ChatActivity` 实例。同类插件 `filter-sentinel` 亦采用该拦截点。
  另挂 7 参重载（长按标志后移一位）作为可选加固，不计入健康分。
- **次级路径**：v1.0.3 的匿名监听器钩子保留，但从 pill 块中解耦、提到
  `_after_create_view` 最先执行；宿主无对应字段时置位 `_listener_hooks_dead`，
  避免每次开聊天重复反射。
- **兜底路径**：占位条自身 `OnClickListener` / `OnLongClickListener` 仍保留。
- `createMenu` 钩子对非占位条视图直接放行，宿主原有长按菜单不受影响。

新增设置页「交互诊断」行：显示 `createMenu` 钩子与监听器钩子的安装状态、
点击/长按命中次数。若点击后命中次数不增加，即说明触摸未派发到上述任一拦截点，
可据此直接定位宿主差异。

**v1.0.3 —「点击显示无效、长按不显示命中规则」（第二轮用户日志确诊）**

根因：Telegram 的 `RecyclerListView` 会拦截条目触摸并**自行派发**
`onItemClick` / `onItemLongClick`，子视图自带的 `OnClickListener` /
`OnLongClickListener` 永远收不到事件（这正是原 Java 补丁演化史中
`fix(filters): route tap-to-reveal through RecyclerListView.onItemClick`
这条提交的由来，v1.0.2 之前的插件未参考到该经验）。日志表现：钩子 9/9
安装、零异常、零点击日志——监听器从未被触发。
修复：在 `ChatActivity.createView` 时读取 `onItemClickListener` /
`onItemLongClickListener`（包级私有字段，匿名内部类，全进程单一 Class），
钩住其 `onItemClick(View,int,float,float)`：点击→恢复整段并消费事件；
长按→弹出命中原因并消费事件。占位条自身的监听器保留为兜底。事件在
首次打开聊天时懒安装（需要 ChatActivity 实例定位匿名类）。

**v1.0.2 —「有过滤的会话打开后消息页空白/闪屏」（用户日志确诊，8162 次同类异常）**

根因：`getItemViewType` 返回类型为 `int`，插件在钩子中 `setResult(-1001)` 时，Chaquopy
对 Object 形参下的 Python `int` 默认装箱为 `java.lang.Long`，而 Xposed 框架交还结果时
执行 `(Integer)` 强转，导致每个被过滤行在布局期抛出
`ClassCastException: Long cannot be cast to Integer`（堆栈帧 `LSPHooker_.getItemViewType`），
`dispatchLayoutStep2` 中断 → 整页空白；反复布局反复抛出 → 闪屏。
修复：所有 `setResult` 改为显式构造 `Integer`/`Boolean`；反射调用
`AyuFilterCache.invalidate(long,int)` 的参数亦改为显式 `Long`/`Integer` 装箱
（此前编辑后即时重判功能静默失效）。

**v1.0.1 — 占位条创建失败导致的空白页降级路径**

上游 `onCreateViewHolder` 对未知视图类型返回 0 高度空 `View`。v1.0.1 起占位条构建
三级降级（主题版 → 极简版 → 失效标记），且 `getItemViewType` 仅在创建钩子确认有效时
才发出 -1001，最坏情况回退为上游「直接隐藏」；`getItemViewType` 同时改为按上游分支
顺序短路判定（未读分割线/屏蔽用户先行），不再重复分组与过滤判定；缓存失效通知
增加 120ms 合并。

### 其他排查项

- 若占位条不出现：确认「显示被过滤消息占位条」开关已开、过滤规则本身已启用
  （`RegexFiltersEnabled`）、且消息确被规则命中（上游原生直接隐藏生效时插件才有占位条）。
- 若升级宿主后功能失效，多为第二节第 4 条的反射依赖变化，请反馈并附宿主版本号。
