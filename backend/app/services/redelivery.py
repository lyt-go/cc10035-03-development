"""网关重连补投领域服务：离线批次处置、幂等接入与边缘缓存释放。

业务背景：
- 网关离线期间待收条目滞留在边缘缓存，重连后值班员从网关管理页发起补投，
  打开离线批次即生成一张重连处置单，接入结果始终回到原处置单。
- 补投只对本网关本次离线批次的待收条目生效；接入台账按
  （网关编号, 测点编号, 采样时间）去重，其它网关上报的同名测点不参与匹配，不混发。
- 设备端已接收但答复丢失的条目，刷新页面或重复补投只补齐回执，
  同一采样位置不会出现第二条实际读数。
- 缓存条目只有在接入已确认、或另有可落实的恢复来源时才可释放；
  悬而未决的条目保持「待确认」，可继续处理。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.store import store

CST = timezone(timedelta(hours=8))

# 待收条目终态：到达这些状态后不再参与补投，重复确认直接跳过
FINAL_ENTRY_STATES = ("已收", "已补回执", "已接入")
# 缓存条目释放状态流转：待确认 → 可释放 → 已释放
CACHE_PENDING = "待确认"
CACHE_CLEARABLE = "可释放"
CACHE_RELEASED = "已释放"
# 处置单状态流转：待办理 → 办理中 → 已办结
TICKET_OPEN = "待办理"
TICKET_DOING = "办理中"
TICKET_DONE = "已办结"

_G1 = "GATE-0001"
_G2 = "GATE-0002"
_BATCH_G1 = "OB-GATE-0001-2026112008"
_T_A = "2026-11-20T08:10:00+08:00"
_T_B = "2026-11-20T08:20:00+08:00"
_T_C = "2026-11-20T08:30:00+08:00"


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _seed_tables() -> dict[str, list[dict[str, Any]]]:
    """构造验收场景初始数据。

    G1（GATE-0001）本次离线批次有三条待收条目：
    A 已收、B 设备已收但答复丢失、C 尚未上送；
    G2（GATE-0002）持有同名测点的独立台账与缓存占用，用于验证不混发。
    处置单初始为空：值班员没有可办理的重连处置单。
    """
    batches = [
        {
            "批次编号": _BATCH_G1,
            "网关编号": _G1,
            "离线开始": "2026-11-20T08:00:00+08:00",
            "重连时间": "2026-11-20T09:30:00+08:00",
            "status": "待处置",
        },
    ]
    entries = [
        {
            "条目编号": "EN-A",
            "批次编号": _BATCH_G1,
            "网关编号": _G1,
            "测点编号": "PT-TEMP-01",
            "测点名称": "温度",
            "采样时间": _T_A,
            "采样值": "23.5",
            "接入状态": "已收",
            "处置结果": "待补投",
        },
        {
            "条目编号": "EN-B",
            "批次编号": _BATCH_G1,
            "网关编号": _G1,
            "测点编号": "PT-HUMI-01",
            "测点名称": "湿度",
            "采样时间": _T_B,
            "采样值": "61.2",
            "接入状态": "答复丢失",
            "处置结果": "待补投",
        },
        {
            "条目编号": "EN-C",
            "批次编号": _BATCH_G1,
            "网关编号": _G1,
            "测点编号": "PT-PRES-01",
            "测点名称": "压力",
            "采样时间": _T_C,
            "采样值": "101.3",
            "接入状态": "未上送",
            "处置结果": "待补投",
        },
    ]
    ledger = [
        {
            "台账编号": "LG-0001",
            "网关编号": _G1,
            "测点编号": "PT-TEMP-01",
            "测点名称": "温度",
            "采样时间": _T_A,
            "采样值": "23.5",
            "写入方式": "实时上报",
            "回执状态": "已回执",
            "接入时间": "2026-11-20T08:10:05+08:00",
            "来源批次": "",
        },
        {
            "台账编号": "LG-0002",
            "网关编号": _G1,
            "测点编号": "PT-HUMI-01",
            "测点名称": "湿度",
            "采样时间": _T_B,
            "采样值": "61.2",
            "写入方式": "实时上报",
            "回执状态": "回执丢失",
            "接入时间": "2026-11-20T08:20:05+08:00",
            "来源批次": "",
        },
        {
            "台账编号": "LG-0003",
            "网关编号": _G2,
            "测点编号": "PT-TEMP-01",
            "测点名称": "温度",
            "采样时间": _T_A,
            "采样值": "24.1",
            "写入方式": "实时上报",
            "回执状态": "已回执",
            "接入时间": "2026-11-20T08:10:07+08:00",
            "来源批次": "",
        },
        {
            "台账编号": "LG-0004",
            "网关编号": _G2,
            "测点编号": "PT-PRES-01",
            "测点名称": "压力",
            "采样时间": _T_C,
            "采样值": "99.8",
            "写入方式": "实时上报",
            "回执状态": "已回执",
            "接入时间": "2026-11-20T08:30:09+08:00",
            "来源批次": "",
        },
    ]
    cache_items = [
        {
            "缓存条目": "CI-0001",
            "配置编号": "EDGE-0001",
            "网关编号": _G1,
            "关联条目": "EN-A",
            "测点编号": "PT-TEMP-01",
            "采样时间": _T_A,
            "占用KB": 12,
            "恢复来源": "",
            "释放状态": CACHE_CLEARABLE,
            "释放依据": "接入台账已确认",
        },
        {
            "缓存条目": "CI-0002",
            "配置编号": "EDGE-0001",
            "网关编号": _G1,
            "关联条目": "EN-B",
            "测点编号": "PT-HUMI-01",
            "采样时间": _T_B,
            "占用KB": 12,
            "恢复来源": "",
            "释放状态": CACHE_CLEARABLE,
            "释放依据": "接入台账已确认",
        },
        {
            "缓存条目": "CI-0003",
            "配置编号": "EDGE-0001",
            "网关编号": _G1,
            "关联条目": "EN-C",
            "测点编号": "PT-PRES-01",
            "采样时间": _T_C,
            "占用KB": 12,
            "恢复来源": "",
            "释放状态": CACHE_PENDING,
            "释放依据": "",
        },
        {
            "缓存条目": "CI-0004",
            "配置编号": "EDGE-0002",
            "网关编号": _G2,
            "关联条目": "",
            "测点编号": "PT-TEMP-01",
            "采样时间": _T_A,
            "占用KB": 20,
            "恢复来源": "磁盘持久化副本",
            "释放状态": CACHE_CLEARABLE,
            "释放依据": "恢复来源：磁盘持久化副本",
        },
        {
            "缓存条目": "CI-0005",
            "配置编号": "EDGE-0002",
            "网关编号": _G2,
            "关联条目": "",
            "测点编号": "PT-PRES-01",
            "采样时间": _T_C,
            "占用KB": 20,
            "恢复来源": "",
            "释放状态": CACHE_PENDING,
            "释放依据": "",
        },
    ]
    return {
        "batches": batches,
        "entries": entries,
        "ledger": ledger,
        "cache_items": cache_items,
    }


class RedeliveryService:
    """重连补投协调器：离线批次 → 处置单 → 幂等接入 → 缓存释放。"""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """恢复初始场景数据；测试与演示重跑时使用。"""
        tables = _seed_tables()
        self._batches = tables["batches"]
        self._entries = tables["entries"]
        self._ledger = tables["ledger"]
        self._cache_items = tables["cache_items"]
        self._tickets: list[dict[str, Any]] = []
        self._ticket_seq = 0
        self._ledger_seq = max(
            (int(row["台账编号"].split("-")[1]) for row in self._ledger), default=0
        )

    # ==================== 查询 ====================

    def _batch_entries(self, batch_no: str) -> list[dict[str, Any]]:
        return [row for row in self._entries if row.get("批次编号") == batch_no]

    def _find_batch(self, batch_no: str) -> dict[str, Any] | None:
        for batch in self._batches:
            if batch.get("批次编号") == batch_no:
                return batch
        return None

    def _find_ticket(self, ticket_no: str) -> dict[str, Any] | None:
        for ticket in self._tickets:
            if ticket.get("单号") == ticket_no:
                return ticket
        return None

    def _find_ledger(
        self, gateway_id: str, point_id: str, sample_ts: str
    ) -> dict[str, Any] | None:
        """接入台账去重键：（网关编号, 测点编号, 采样时间）。

        网关编号参与匹配，其它网关上报的同名测点不会被本网关的补投命中。
        """
        for row in self._ledger:
            if (
                row.get("网关编号") == gateway_id
                and row.get("测点编号") == point_id
                and row.get("采样时间") == sample_ts
            ):
                return row
        return None

    def list_batches(self, gateway_id: str | None = None) -> list[dict[str, Any]]:
        """离线批次列表，附带待收条目核对信息。"""
        result = []
        for batch in self._batches:
            if gateway_id and batch.get("网关编号") != gateway_id:
                continue
            entries = self._batch_entries(batch["批次编号"])
            ticket = next(
                (t for t in self._tickets if t.get("批次编号") == batch["批次编号"]),
                None,
            )
            result.append({
                **batch,
                "待收条目数": len(entries),
                "未办结条目数": sum(
                    1 for e in entries if e.get("接入状态") not in FINAL_ENTRY_STATES
                ),
                "处置单号": ticket.get("单号") if ticket else "",
            })
        return result

    def get_batch(self, batch_no: str) -> dict[str, Any] | None:
        batch = self._find_batch(batch_no)
        if batch is None:
            return None
        return {"batch": batch, "entries": self._batch_entries(batch_no)}

    def list_tickets(self, gateway_id: str | None = None) -> list[dict[str, Any]]:
        return [
            ticket
            for ticket in self._tickets
            if not gateway_id or ticket.get("网关编号") == gateway_id
        ]

    def ledger(self, gateway_id: str | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self._ledger
            if not gateway_id or row.get("网关编号") == gateway_id
        ]

    def cache_items(self, gateway_id: str | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self._cache_items
            if not gateway_id or row.get("网关编号") == gateway_id
        ]

    def cache_occupancy_kb(self, gateway_id: str) -> int:
        """网关当前缓存占用：未释放条目占用之和。"""
        return sum(
            int(item.get("占用KB", 0))
            for item in self._cache_items
            if item.get("网关编号") == gateway_id
            and item.get("释放状态") != CACHE_RELEASED
        )

    def ticket_detail(self, ticket_no: str) -> dict[str, Any] | None:
        """处置单详情：待收条目、接入台账、缓存条目与释放决定。"""
        ticket = self._find_ticket(ticket_no)
        if ticket is None:
            return None
        gateway_id = ticket["网关编号"]
        return {
            "ticket": ticket,
            "entries": self._batch_entries(ticket["批次编号"]),
            "cache_items": self.cache_items(gateway_id),
            "ledger": self.ledger(gateway_id),
            "cache_occupancy_kb": self.cache_occupancy_kb(gateway_id),
        }

    # ==================== 命令 ====================

    def open_batch(self, batch_no: str) -> dict[str, Any]:
        """打开离线批次：生成（或复用）本批次唯一的重连处置单。

        幂等：同一批次重复打开返回原处置单，接入结果始终回到原处置单。
        """
        batch = self._find_batch(batch_no)
        if batch is None:
            return {"ok": False, "message": f"离线批次 {batch_no} 不存在"}

        ticket = next(
            (t for t in self._tickets if t.get("批次编号") == batch_no), None
        )
        created = False
        if ticket is None:
            self._ticket_seq += 1
            ticket = {
                "单号": f"RD-{self._ticket_seq:04d}",
                "网关编号": batch["网关编号"],
                "批次编号": batch_no,
                "status": TICKET_OPEN,
                "创建时间": _now(),
                "办结时间": "",
                "办理次数": 0,
            }
            self._tickets.append(ticket)
            batch["status"] = "处置中"
            created = True

        self._refresh_cache_decisions(ticket["网关编号"])
        message = (
            f"已打开离线批次 {batch_no}，生成处置单 {ticket['单号']}"
            if created
            else f"离线批次 {batch_no} 已关联处置单 {ticket['单号']}，继续办理"
        )
        return {"ok": True, "created": created, "message": message,
                **self.ticket_detail(ticket["单号"])}

    def confirm_redelivery(self, ticket_no: str) -> dict[str, Any]:
        """确认补投：对本网关本批次未办结的待收条目执行幂等接入。

        - 台账已有同键读数（设备已收、答复丢失）：只补齐回执，不新增读数；
        - 台账无同键读数（尚未上送）：新增一条接入读数；
        - 已到终态的条目直接跳过，重复确认/刷新页面不会产生第二条读数。
        接入结果写回原处置单，并同步刷新缓存释放决定。
        """
        ticket = self._find_ticket(ticket_no)
        if ticket is None:
            return {"ok": False, "message": f"处置单 {ticket_no} 不存在或已归档"}

        gateway_id = ticket["网关编号"]
        batch = self._find_batch(ticket["批次编号"])
        entries = self._batch_entries(ticket["批次编号"])
        added = receipts = already = 0

        for entry in entries:
            if entry.get("接入状态") in FINAL_ENTRY_STATES:
                if entry.get("处置结果") == "待补投":
                    entry["处置结果"] = "已有接入确认，无需补投"
                already += 1
                continue
            row = self._find_ledger(
                gateway_id, entry["测点编号"], entry["采样时间"]
            )
            if row is not None:
                # 设备端已接收但答复丢失：只补齐回执，同一采样位置不新增读数
                if row.get("回执状态") != "已回执":
                    row["回执状态"] = "已补回执"
                    row["回执补齐时间"] = _now()
                entry["接入状态"] = "已补回执"
                entry["处置结果"] = "命中接入台账，仅补齐回执，未新增读数"
                receipts += 1
            else:
                self._ledger_seq += 1
                self._ledger.append({
                    "台账编号": f"LG-{self._ledger_seq:04d}",
                    "网关编号": gateway_id,
                    "测点编号": entry["测点编号"],
                    "测点名称": entry["测点名称"],
                    "采样时间": entry["采样时间"],
                    "采样值": entry["采样值"],
                    "写入方式": "补投新增",
                    "回执状态": "已回执",
                    "接入时间": _now(),
                    "来源批次": ticket["批次编号"],
                })
                entry["接入状态"] = "已接入"
                entry["处置结果"] = "补投新增接入 1 条读数"
                added += 1

        ticket["办理次数"] = int(ticket.get("办理次数", 0)) + 1
        self._refresh_cache_decisions(gateway_id)

        if all(e.get("接入状态") in FINAL_ENTRY_STATES for e in entries):
            ticket["status"] = TICKET_DONE
            if not ticket.get("办结时间"):
                ticket["办结时间"] = _now()
            if batch is not None:
                batch["status"] = "已办结"
        else:
            ticket["status"] = TICKET_DOING

        return {
            "ok": True,
            "message": (
                f"补投完成：新增接入 {added} 条，补齐回执 {receipts} 条，"
                f"已有确认 {already} 条"
            ),
            "新增接入": added,
            "补齐回执": receipts,
            "已有确认": already,
            **self.ticket_detail(ticket_no),
        }

    def release_cache(self, ticket_no: str) -> dict[str, Any]:
        """按处置单释放本网关可清缓存条目。

        只释放「可释放」条目（已有接入确认或另有恢复来源）；
        悬而未决的「待确认」条目保留，可继续处理。
        """
        ticket = self._find_ticket(ticket_no)
        if ticket is None:
            return {"ok": False, "message": f"处置单 {ticket_no} 不存在或已归档"}

        gateway_id = ticket["网关编号"]
        self._refresh_cache_decisions(gateway_id)
        released = self._release_clearable(gateway_id)
        pending = sum(
            1 for item in self._cache_items
            if item.get("网关编号") == gateway_id
            and item.get("释放状态") == CACHE_PENDING
        )
        freed = sum(int(item.get("占用KB", 0)) for item in released)
        return {
            "ok": True,
            "message": (
                f"已释放 {len(released)} 条可清缓存条目，回收 {freed}KB；"
                f"{pending} 条悬而未决，待接入确认后继续处理"
            ),
            "释放条目数": len(released),
            "释放占用KB": freed,
            "待确认条目数": pending,
            **self.ticket_detail(ticket_no),
        }

    def evict_cache(self, gateway_id: str) -> dict[str, Any]:
        """缓存清理（淘汰）入口：与未办结的重连补投冲突时交回处置页。

        - 本网关存在未办结处置单：判定冲突，不释放任何条目，
          返回处置单号，提示从处置页继续处理；
        - 无未办结处置单：按释放决定清理「可释放」条目，
          「待确认」条目一律保留。
        """
        gateway = next(
            (row for row in store.rows("gateway_mgmt")
             if row.get("网关编号") == gateway_id),
            None,
        )
        if gateway is None:
            return {"ok": False, "conflict": False,
                    "message": f"网关 {gateway_id} 不存在"}

        unresolved = [
            ticket for ticket in self._tickets
            if ticket.get("网关编号") == gateway_id
            and ticket.get("status") != TICKET_DONE
        ]
        if unresolved:
            ticket = unresolved[0]
            clearable = sum(
                1 for item in self._cache_items
                if item.get("网关编号") == gateway_id
                and item.get("释放状态") == CACHE_CLEARABLE
            )
            pending = sum(
                1 for item in self._cache_items
                if item.get("网关编号") == gateway_id
                and item.get("释放状态") == CACHE_PENDING
            )
            return {
                "ok": False,
                "conflict": True,
                "ticket_no": ticket["单号"],
                "message": (
                    f"缓存清理与重连补投冲突：处置单 {ticket['单号']} 未办结，"
                    f"请从处置页继续处理"
                ),
                "可释放条目数": clearable,
                "待确认条目数": pending,
            }

        self._refresh_cache_decisions(gateway_id)
        released = self._release_clearable(gateway_id)
        freed = sum(int(item.get("占用KB", 0)) for item in released)
        return {
            "ok": True,
            "conflict": False,
            "message": f"缓存清理完成：释放 {len(released)} 条，回收 {freed}KB",
            "释放条目数": len(released),
            "释放占用KB": freed,
        }

    # ==================== 内部 ====================

    def _refresh_cache_decisions(self, gateway_id: str) -> None:
        """重算本网关缓存条目的释放决定（不触碰其它网关）。

        可释放的充要条件：接入台账已有同键确认读数，或条目另有
        可落实的恢复来源；否则保持「待确认」，留待继续处理。
        """
        for item in self._cache_items:
            if item.get("网关编号") != gateway_id:
                continue
            if item.get("释放状态") == CACHE_RELEASED:
                continue
            row = self._find_ledger(
                gateway_id, item["测点编号"], item["采样时间"]
            )
            if row is not None:
                item["释放状态"] = CACHE_CLEARABLE
                item["释放依据"] = "接入台账已确认"
            elif item.get("恢复来源"):
                item["释放状态"] = CACHE_CLEARABLE
                item["释放依据"] = f"恢复来源：{item['恢复来源']}"
            else:
                item["释放状态"] = CACHE_PENDING
                item["释放依据"] = ""

    def _release_clearable(self, gateway_id: str) -> list[dict[str, Any]]:
        released = []
        for item in self._cache_items:
            if item.get("网关编号") != gateway_id:
                continue
            if item.get("释放状态") == CACHE_CLEARABLE:
                item["释放状态"] = CACHE_RELEASED
                item["释放时间"] = _now()
                released.append(item)
        return released


redelivery_service = RedeliveryService()
