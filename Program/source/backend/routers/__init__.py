"""Routers package. 维护人：机器 A。
各机器新增接口时：新建自己的 router 文件（如 workspaces.py），在 create_app 中 include_router。
公共文件：本 __init__.py 仅作包标识，聚合与挂载由 backend/app.py 负责。"""
