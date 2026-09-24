# Codex Plus 提示词模板（机器 A / B）

> 用法：在机器 A 或 B 上，进入 clone 下来的仓库目录，打开 Codex，把下面内容贴进去（替换占位符）。
> Codex 会自动操作本机 Git；工作目录就是仓库本身。

```
请协助我在 FlowDesk 项目中完成以下开发任务。

【环境】仓库已克隆在本地，当前分支 feat/<X>（只属于我，机器 <X>）。

【硬性边界】
- 只允许修改：<负责人目录列表>；禁止改动其他任何目录、任何他人文件。
- 不删除、不重命名、不格式化他人的文件。
- 每次动手前先 git pull origin main 并合并到当前分支。
- 只 push 到 feat/<X>，不 push main，不 force push。
- 提交信息用 conventional 格式：type(scope): 简述（feat/fix/docs/chore）。
- 大文件（exe/zip/db/venv/node_modules/dist）绝不 add/commit。

【项目背景】
FlowDesk：本地单机应用（Vue 3 + FastAPI + SQLite）。M1 Project 与 M2 Account 已完成（基线冻结）。
新模块一律按「表文件 + 接口文件 + 视图文件 + 测试文件」四个文件交付，不修改公共层文件
（backend/models/__init__.py、backend/routers/__init__.py、frontend/src/App.vue、backend/migrations.py 等）。

【任务】
<具体需求>

【完成标准】
<可验证的验收点，如：pytest 通过、npm run build 通过、接口可调用>

完成后把改动提交并 push 到 feat/<X>，再提示我在平台发起 PR：feat/<X> → main。
```
