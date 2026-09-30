# Filter Enhancement（过滤器增强）插件

将 `ljili1/NagramXF` 仓库 12.10.1 分支上的「过滤器增强」补丁（提交 `67b0380c` + `533af9af`）
移植为 `Keeperorowner/NagramXF` 的 Python 插件（exteraGram 式插件 SDK）。

- 插件文件：`filter_enhancement.py`（单文件，无外部依赖）
- 插件 ID：`filter_enhancement`，版本 1.0.2
- 目标宿主：Keeperorowner/NagramXF **plugin 构建**（dev 分支，`min_version = 12.2.10`）

## 一、功能对照

| # | 原补丁功能（Java） | 插件实现 | 钩子点 |
|---|---|---|---|
| 1 | 被过滤消息显示为可点击占位条（视图类型 -1001，替代直接消失） | 一致 | `ChatActivity$ChatActivityAdapter.getItemViewType` / `onCreateViewHolder` |
| 2 | 连续占位条合并为「N 条消息被隐藏」单条 | 一致（可选关闭） | `onBindViewHolder` |
| 3 | 点击占位条恢复显示整段消息（原内容原样渲染） | 一致 | 占位条自带 `OnClickListener` |
| 4 | 长按占位条弹出「过滤原因」（命中片段） | 一致 | 占位条自带 `OnLongClickListener` |
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

- **插件设置页内置「钩子状态」行**（9 个钩子应全部安装成功）。若有缺失，该行会红色标注
  实际数量；缺失时对应功能自动降级为上游原生行为，请截图该行并反馈宿主版本号。
- 插件日志经宿主 `AppUtils.log` 输出，前缀 `[filter_enhancement]`；可用日志工具检索。

### 已修复的历史问题

**v1.0.2 —「有过滤的会话打开后消息页空白/闪屏」（用户日志确诊）**

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
