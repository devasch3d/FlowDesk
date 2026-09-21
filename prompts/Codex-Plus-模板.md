# Codex Plus 提示词模板（机器 A / B）

> 用法：在机器 A 或 B 上，进入 clone 下来的仓库目录，打开 Codex，把下面内容贴进去（替换占位符）。
> Codex 会自动操作本机 Git；工作目录就是仓库本身。

```
请协助我在 <项目名> 中完成以下开发任务。

【环境】仓库已克隆在本地，当前分支 feat/A（只属于我这台机器，机器 A）。

【硬性边界】
- 只允许修改：module-a/、docs/a.md；禁止改动其他任何目录。
- 不删除、不重命名、不格式化他人的文件。
- 每次动手前先 git pull origin main 并合并到当前分支。
- 只 push 到 feat/A，不 push main，不 force push。
- 提交信息用 conventional 格式：type(scope): 简述。

【任务】
<具体需求>

【完成标准】
<可验证的验收点，如：单测通过、构建通过、接口可调用>

完成后把改动提交并 push 到 feat/A，再提示我在平台发起 PR：feat/A → main。
```
