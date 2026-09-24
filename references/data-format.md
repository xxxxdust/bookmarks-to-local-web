# 输入格式

`library.json` 为 UTF-8 JSON 对象，包含 `meta`、`posts`、`prompts`、`skills`。脚本只将已审核数据排版，不自动概括。

- `meta`: `title`、`scope`、`limitations` 为非空字符串，`takeaways` 为字符串数组，`subtitle` 可选。范围必须说明是本批还是已确认全部，缺失项不要留给数量猜测。
- `posts[]`: 新同步批次须填写 `read_state`（`unavailable/partial/complete`），按实际约定阅读范围判断；读取失败用unavailable。 `id` 正整数（组内唯一、不必连续）；字符串字段 `title, author, category, url, lead, action, resources, status`；`points` 为重点字符串数组；`prompts, skills` 为对应ID数组。`status` 说明实际读到哪些内容，`resources` 说明资源状况和缺失。
- `prompts[]`: `id`；`title, body, note` 非空字符串；`kind` 为 `作者原版`、`整理改写版`、`用户原稿` 三选一；`sources` 为非空帖子ID数组。`note` 注明使用条件及原文/改写边界。
- `skills[]`: `id`；`name, repository, use, source, file, license, commit` 非空字符串；`sources` 为非空帖子ID数组；`files` 为 `{label, path}` 对象数组。实际可以是 Skill、模板或工具包，名称如实标明。未知版本/许可写“未确认”，不要猜。`file` 是本地原包，`files` 仅列需要纯文本预览的文件。

URL 仅接受无账号密码的 HTTP(S)。本地文件 `file/path` 均须以 `resources/` 开始，相对 `library.json` 所在目录，禁止 `..`、绝对路径和目录外符号链接。脚本复制这些文件；不能把资源藏在 Skill 自己的目录里。不要将可执行文件当文本预览。

最小输入（此例是格式示范，不能作为用户真实笔记）：

```json
{
  "meta": {"title":"阅读笔记","scope":"本批1条；总量未确认","limitations":"仅示范格式","takeaways":[]},
  "posts": [{"id":10,"title":"示例","author":"示例作者","category":"示例","url":"https://example.com/note","lead":"示例结论","points":["示例重点"],"action":"示例建议","resources":"无公开资源","status":"格式示范","prompts":[],"skills":[]}],
  "prompts": [],
  "skills": []
}
```

生成到新目录后，原文件保留不变。增量更新由执行 Skill 的助手先合并数据并核对事实，再构建新版本；构建器本身不抓取、不自动增量同步。抓取清单/恢复点放工作目录，交付总览概括缺失和最后读取锚点即可，不暴露凭证。
