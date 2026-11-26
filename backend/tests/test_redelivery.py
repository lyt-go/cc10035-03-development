"""网关重连补投验收测试：离线批次处置、幂等接入、缓存释放与跨网关隔离。

场景：网关 G1 下 A 已收、B 丢了答复、C 尚未上送；缓存清理与重连补投
发生冲突，从处置页继续处理。设备接入最终只新增 C，A、B、C 均能查到
终态，G2 的缓存占用和接收记录没有变化。
"""
from __future__ import annotations

import copy

import pytest

from app.services.redelivery import (
    CACHE_CLEARABLE,
    CACHE_PENDING,
    CACHE_RELEASED,
    TICKET_DONE,
    redelivery_service,
)

G1 = "GATE-0001"
G2 = "GATE-0002"
BATCH_G1 = "OB-GATE-0001-2026112008"


@pytest.fixture(autouse=True)
def fresh_service():
    """每个用例都从初始场景重跑，保证重复执行结果一致。"""
    redelivery_service.reset()
    yield


def _entry(detail: dict, entry_no: str) -> dict:
    return next(e for e in detail["entries"] if e["条目编号"] == entry_no)


def _cache_item(service, item_no: str) -> dict:
    return next(i for i in service.cache_items() if i["缓存条目"] == item_no)


# ==================== 初始状态 ====================

class TestInitialState:
    def test_no_pending_ticket_for_operator(self):
        """值班员初始没有可办理的重连处置单。"""
        assert redelivery_service.list_tickets() == []

    def test_g1_offline_batch_ready(self):
        batches = redelivery_service.list_batches(G1)
        assert len(batches) == 1
        batch = batches[0]
        assert batch["批次编号"] == BATCH_G1
        assert batch["待收条目数"] == 3
        assert batch["未办结条目数"] == 2  # B 答复丢失、C 未上送
        assert batch["处置单号"] == ""

    def test_edge_cache_config_exists(self):
        """边缘缓存已有配置和淘汰策略。"""
        from app.store import store
        configs = {
            row["网关编号"]: row for row in store.rows("edge_cache")
        }
        assert configs[G1]["淘汰策略"] == "LRU"
        assert configs[G1]["status"] == "已生效"
        assert configs[G2]["淘汰策略"] == "LFU"


# ==================== 打开批次与处置单 ====================

class TestOpenBatch:
    def test_open_creates_ticket(self):
        result = redelivery_service.open_batch(BATCH_G1)
        assert result["ok"] is True
        assert result["created"] is True
        ticket = result["ticket"]
        assert ticket["网关编号"] == G1
        assert ticket["批次编号"] == BATCH_G1
        assert ticket["status"] == "待办理"
        assert len(redelivery_service.list_tickets()) == 1

    def test_open_is_idempotent_returns_same_ticket(self):
        first = redelivery_service.open_batch(BATCH_G1)
        second = redelivery_service.open_batch(BATCH_G1)
        assert second["created"] is False
        assert second["ticket"]["单号"] == first["ticket"]["单号"]
        assert len(redelivery_service.list_tickets()) == 1

    def test_open_unknown_batch(self):
        result = redelivery_service.open_batch("OB-NOPE")
        assert result["ok"] is False


# ==================== 确认补投（核心验收） ====================

class TestConfirmRedelivery:
    def test_confirm_only_adds_c(self):
        """设备接入最终只新增 C；A 保持已收，B 只补回执。"""
        redelivery_service.open_batch(BATCH_G1)
        before = len(redelivery_service.ledger())

        result = redelivery_service.confirm_redelivery("RD-0001")
        assert result["ok"] is True
        assert result["新增接入"] == 1
        assert result["补齐回执"] == 1
        assert result["已有确认"] == 1

        ledger = redelivery_service.ledger()
        assert len(ledger) == before + 1  # 全量台账只多 C 一条

        g1_ledger = redelivery_service.ledger(G1)
        added = [r for r in g1_ledger if r["写入方式"] == "补投新增"]
        assert len(added) == 1
        assert added[0]["测点编号"] == "PT-PRES-01"
        assert added[0]["采样时间"] == "2026-11-20T08:30:00+08:00"
        assert added[0]["来源批次"] == BATCH_G1

        # B：回执补齐，接入时间不变，没有第二条读数
        b_rows = [r for r in g1_ledger if r["测点编号"] == "PT-HUMI-01"]
        assert len(b_rows) == 1
        assert b_rows[0]["回执状态"] == "已补回执"
        assert b_rows[0]["接入时间"] == "2026-11-20T08:20:05+08:00"

    def test_final_states_queryable_on_ticket(self):
        """A、B、C 均能查到终态，且结果回到原处置单。"""
        opened = redelivery_service.open_batch(BATCH_G1)
        ticket_no = opened["ticket"]["单号"]
        redelivery_service.confirm_redelivery(ticket_no)

        detail = redelivery_service.ticket_detail(ticket_no)
        assert _entry(detail, "EN-A")["接入状态"] == "已收"
        assert _entry(detail, "EN-B")["接入状态"] == "已补回执"
        assert _entry(detail, "EN-C")["接入状态"] == "已接入"
        assert detail["ticket"]["status"] == TICKET_DONE
        assert detail["ticket"]["办结时间"]

    def test_confirm_is_idempotent_on_repeat_and_refresh(self):
        """再点补投/刷新页面只补齐回执，不产生第二条实际读数。"""
        redelivery_service.open_batch(BATCH_G1)
        redelivery_service.confirm_redelivery("RD-0001")
        snapshot = copy.deepcopy(redelivery_service.ledger())

        again = redelivery_service.confirm_redelivery("RD-0001")
        assert again["ok"] is True
        assert again["新增接入"] == 0
        assert again["补齐回执"] == 0
        assert redelivery_service.ledger() == snapshot
        # 每个采样位置仍只有一条实际读数
        keys = [
            (r["网关编号"], r["测点编号"], r["采样时间"])
            for r in redelivery_service.ledger()
        ]
        assert len(keys) == len(set(keys))

    def test_scope_limited_to_batch_entries(self):
        """处置只对本网关本次离线批次的待收条目生效。"""
        redelivery_service.open_batch(BATCH_G1)
        redelivery_service.confirm_redelivery("RD-0001")
        # G1 台账 = 原有 A、B 两条 + 新增 C 一条
        assert len(redelivery_service.ledger(G1)) == 3
        # 台账中没有批次之外的写入
        for row in redelivery_service.ledger(G1):
            assert row["网关编号"] == G1


# ==================== 缓存释放与淘汰冲突 ====================

class TestCacheRelease:
    def test_clearable_requires_confirmation_or_recovery_source(self):
        """可清条目须已有接入确认或另有恢复来源；悬而未决的保持待确认。"""
        redelivery_service.open_batch(BATCH_G1)
        # A、B 已有接入确认 → 可释放；C 未上送且无恢复来源 → 待确认
        assert _cache_item(redelivery_service, "CI-0001")["释放状态"] == CACHE_CLEARABLE
        assert _cache_item(redelivery_service, "CI-0002")["释放状态"] == CACHE_CLEARABLE
        ci3 = _cache_item(redelivery_service, "CI-0003")
        assert ci3["释放状态"] == CACHE_PENDING
        assert ci3["释放依据"] == ""

    def test_release_keeps_pending_entries_processable(self):
        """补投前释放：只清已确认条目，C 的条目悬而未决可继续处理。"""
        redelivery_service.open_batch(BATCH_G1)
        result = redelivery_service.release_cache("RD-0001")
        assert result["释放条目数"] == 2
        assert result["待确认条目数"] == 1
        assert _cache_item(redelivery_service, "CI-0003")["释放状态"] == CACHE_PENDING
        # C 继续处理：确认补投后变为可释放
        redelivery_service.confirm_redelivery("RD-0001")
        ci3 = _cache_item(redelivery_service, "CI-0003")
        assert ci3["释放状态"] == CACHE_CLEARABLE
        assert ci3["释放依据"] == "接入台账已确认"

    def test_eviction_conflicts_with_open_ticket(self):
        """缓存清理与重连补投冲突：不释放任何条目，交回处置页。"""
        redelivery_service.open_batch(BATCH_G1)
        occupancy_before = redelivery_service.cache_occupancy_kb(G1)

        result = redelivery_service.evict_cache(G1)
        assert result["ok"] is False
        assert result["conflict"] is True
        assert result["ticket_no"] == "RD-0001"
        assert redelivery_service.cache_occupancy_kb(G1) == occupancy_before

    def test_continue_from_disposition_page_after_conflict(self):
        """冲突后从处置页继续：确认补投 → 办结 → 缓存清理放行。"""
        redelivery_service.open_batch(BATCH_G1)
        conflict = redelivery_service.evict_cache(G1)
        assert conflict["conflict"] is True

        ticket_no = conflict["ticket_no"]
        redelivery_service.confirm_redelivery(ticket_no)
        done = redelivery_service.ticket_detail(ticket_no)
        assert done["ticket"]["status"] == TICKET_DONE

        cleared = redelivery_service.evict_cache(G1)
        assert cleared["ok"] is True
        assert cleared["释放条目数"] == 3
        assert redelivery_service.cache_occupancy_kb(G1) == 0
        assert all(
            item["释放状态"] == CACHE_RELEASED
            for item in redelivery_service.cache_items(G1)
        )

    def test_release_via_ticket_after_confirm(self):
        redelivery_service.open_batch(BATCH_G1)
        redelivery_service.confirm_redelivery("RD-0001")
        result = redelivery_service.release_cache("RD-0001")
        assert result["释放条目数"] == 3
        assert result["释放占用KB"] == 36
        assert result["待确认条目数"] == 0


# ==================== 跨网关隔离 ====================

class TestCrossGatewayIsolation:
    def test_g2_untouched_by_g1_full_flow(self):
        """G1 全流程办理后，G2 的缓存占用和接收记录没有变化。"""
        g2_ledger_before = copy.deepcopy(redelivery_service.ledger(G2))
        g2_cache_before = copy.deepcopy(redelivery_service.cache_items(G2))
        g2_occupancy_before = redelivery_service.cache_occupancy_kb(G2)

        redelivery_service.open_batch(BATCH_G1)
        redelivery_service.confirm_redelivery("RD-0001")
        redelivery_service.release_cache("RD-0001")
        redelivery_service.evict_cache(G1)

        assert redelivery_service.ledger(G2) == g2_ledger_before
        assert redelivery_service.cache_items(G2) == g2_cache_before
        assert redelivery_service.cache_occupancy_kb(G2) == g2_occupancy_before

    def test_same_named_point_not_mixed(self):
        """接入端有 G2 上报的同名测点，G1 的补投不可混发。"""
        # G2 与 G1 的 A/C 使用相同测点编号与采样时间
        redelivery_service.open_batch(BATCH_G1)
        redelivery_service.confirm_redelivery("RD-0001")

        g2_rows = redelivery_service.ledger(G2)
        assert len(g2_rows) == 2
        assert all(row["写入方式"] == "实时上报" for row in g2_rows)
        assert all(row["来源批次"] == "" for row in g2_rows)
        # G1 新增的 C 只落在 G1 名下
        c_rows = [
            row for row in redelivery_service.ledger()
            if row["测点编号"] == "PT-PRES-01"
            and row["采样时间"] == "2026-11-20T08:30:00+08:00"
        ]
        assert {(row["网关编号"], row["写入方式"]) for row in c_rows} == {
            (G1, "补投新增"),
            (G2, "实时上报"),
        }
