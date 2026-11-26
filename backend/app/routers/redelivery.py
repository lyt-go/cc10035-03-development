"""网关重连补投接口：离线批次打开、补投确认、缓存释放与台账查询。

路径挂在 /api/redelivery 下，注册顺序在通用资源路由 /api/{module} 之前，
避免被动态模块路由抢先匹配。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.redelivery import redelivery_service

router = APIRouter(prefix="/api/redelivery", tags=["网关重连补投"])


@router.get("/batches")
def list_batches(gateway_id: str | None = Query(default=None)):
    """离线批次列表：按网关过滤，附带待收条目核对信息。"""
    return {"items": redelivery_service.list_batches(gateway_id)}


@router.get("/batches/{batch_no}")
def get_batch(batch_no: str):
    """离线批次详情：打开前先核对待收条目。"""
    detail = redelivery_service.get_batch(batch_no)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"离线批次 {batch_no} 不存在")
    return detail


@router.post("/batches/{batch_no}/open")
def open_batch(batch_no: str):
    """打开离线批次：生成（或复用）本批次唯一的重连处置单。"""
    result = redelivery_service.open_batch(batch_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/tickets")
def list_tickets(gateway_id: str | None = Query(default=None)):
    """重连处置单列表：值班员的待办队列。"""
    return {"items": redelivery_service.list_tickets(gateway_id)}


@router.get("/tickets/{ticket_no}")
def ticket_detail(ticket_no: str):
    """处置单详情：待收条目终态、接入台账、缓存条目与释放决定。"""
    detail = redelivery_service.ticket_detail(ticket_no)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"处置单 {ticket_no} 不存在或已归档")
    return detail


@router.post("/tickets/{ticket_no}/confirm")
def confirm_redelivery(ticket_no: str):
    """确认补投：幂等接入，结果写回原处置单。"""
    result = redelivery_service.confirm_redelivery(ticket_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/tickets/{ticket_no}/release-cache")
def release_cache(ticket_no: str):
    """按处置单释放本网关可清缓存条目，悬而未决的保留。"""
    result = redelivery_service.release_cache(ticket_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/cache/evict")
def evict_cache(gateway_id: str = Query(..., description="网关编号")):
    """缓存清理：与未办结补投冲突时返回处置单号，交回处置页处理。"""
    return redelivery_service.evict_cache(gateway_id)


@router.get("/ledger")
def query_ledger(gateway_id: str | None = Query(default=None)):
    """接入台账：按网关查询实际读数与回执终态。"""
    return {"items": redelivery_service.ledger(gateway_id)}


@router.get("/cache-items")
def query_cache_items(gateway_id: str | None = Query(default=None)):
    """边缘缓存条目：按网关查询占用与释放状态。"""
    items = redelivery_service.cache_items(gateway_id)
    return {
        "items": items,
        "cache_occupancy_kb": (
            redelivery_service.cache_occupancy_kb(gateway_id) if gateway_id else None
        ),
    }
