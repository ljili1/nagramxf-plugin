# nagramxf-plugin

NagramXF（Keeperorowner/NagramXF，plugin 构建）的 Python 插件合集。每个目录为一个
独立插件：`<name>.plugin` 为安装文件（发送到任意聊天后点击，或在 设置 → 插件 →
从文件安装），`test_<name>.py` 为离线测试（CPython 直接运行，无需 Java 环境）。

## 插件列表

| 目录 | 插件 | 说明 |
|---|---|---|
| `filter-enhancement/` | Filter Enhancement | 过滤器增强：被过滤消息原位占位条、点击恢复、合并连续段、长按看命中原因、收起悬浮按钮、链接预览参与匹配、编辑后即时重判。ljili1/NagramXF 12.10.1 过滤器增强补丁的插件化移植。 |
| `ws-proxy/` | WS Proxy | WebSocket 代理相关插件。 |


## 版本归档

历史版本保留在各插件目录的 `versions/` 子目录。各版本差异见插件目录内 `README.md` 的「故障排查 /
已修复的历史问题」一节。
