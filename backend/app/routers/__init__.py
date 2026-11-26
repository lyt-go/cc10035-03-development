"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import cross_module, redelivery, resource

# redelivery 的固定前缀 /api/redelivery 必须先于 resource 的 /api/{module} 注册。
ROUTERS = [cross_module, redelivery, resource]
