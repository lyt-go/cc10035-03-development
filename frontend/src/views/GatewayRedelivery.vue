<template>
  <section class="page" data-module="gateway_redelivery">
    <header class="page-head">
      <div>
        <h2>网关重连补投处置</h2>
        <p class="page-desc">
          打开离线批次核对待收条目，确认补投后接入结果回到原处置单，并按接入确认情况释放边缘缓存。
        </p>
      </div>
      <div class="page-actions">
        <label class="gateway-picker">
          <span>网关</span>
          <select v-model="gatewayId" data-testid="gateway-select" @change="changeGateway">
            <option v-for="gw in gatewayOptions" :key="gw" :value="gw">{{ gw }}</option>
          </select>
        </label>
        <button class="btn" data-testid="evict-cache" type="button" @click="runEvict">
          缓存清理
        </button>
      </div>
    </header>

    <p v-if="conflictMessage" class="conflict-banner" data-testid="conflict-banner">
      {{ conflictMessage }}
    </p>
    <p v-if="pageMessage" class="action-message" data-testid="page-message">
      {{ pageMessage }}
    </p>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">离线批次</span>
        <strong class="stat-value" data-testid="stat-batches">{{ batches.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">未办结处置单</span>
        <strong class="stat-value" data-testid="stat-open-tickets">{{ openTicketCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待确认缓存条目</span>
        <strong class="stat-value" data-testid="stat-pending-cache">{{ pendingCacheCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">缓存占用KB</span>
        <strong class="stat-value" data-testid="stat-occupancy">{{ cacheOccupancy }}</strong>
      </article>
    </div>

    <h3 class="section-title">离线批次</h3>
    <table class="data-table" data-testid="batch-table">
      <thead>
        <tr>
          <th>批次编号</th><th>离线开始</th><th>重连时间</th>
          <th>待收条目数</th><th>未办结条目</th><th>状态</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="batch in batches" :key="batch.批次编号" :data-testid="`batch-${batch.批次编号}`">
          <td>{{ batch.批次编号 }}</td>
          <td>{{ batch.离线开始 }}</td>
          <td>{{ batch.重连时间 }}</td>
          <td>{{ batch.待收条目数 }}</td>
          <td>{{ batch.未办结条目数 }}</td>
          <td>{{ batch.status }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`open-batch-${batch.批次编号}`"
              @click="openOfflineBatch(batch.批次编号)"
            >
              {{ batch.处置单号 ? '打开处置单' : '打开批次' }}
            </button>
          </td>
        </tr>
        <tr v-if="!batches.length">
          <td colspan="7" class="empty-state">本网关暂无离线批次</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">重连处置单</h3>
    <table class="data-table" data-testid="ticket-table">
      <thead>
        <tr>
          <th>单号</th><th>批次编号</th><th>状态</th>
          <th>办理次数</th><th>创建时间</th><th>办结时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="ticket in tickets" :key="ticket.单号" :data-testid="`ticket-${ticket.单号}`">
          <td>{{ ticket.单号 }}</td>
          <td>{{ ticket.批次编号 }}</td>
          <td>{{ ticket.status }}</td>
          <td>{{ ticket.办理次数 }}</td>
          <td>{{ ticket.创建时间 }}</td>
          <td>{{ ticket.办结时间 || '—' }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`open-ticket-${ticket.单号}`"
              @click="loadTicket(ticket.单号)"
            >
              办理
            </button>
          </td>
        </tr>
        <tr v-if="!tickets.length">
          <td colspan="7" class="empty-state">暂无可办理的重连处置单，可先打开离线批次</td>
        </tr>
      </tbody>
    </table>

    <template v-if="detail">
      <h3 class="section-title">
        处置单 {{ detail.ticket.单号 }}
        <span class="ticket-status" data-testid="ticket-status">{{ detail.ticket.status }}</span>
      </h3>
      <p class="ticket-meta">
        网关 {{ detail.ticket.网关编号 }} ｜ 批次 {{ detail.ticket.批次编号 }} ｜
        办理次数 {{ detail.ticket.办理次数 }} ｜ 缓存占用 {{ detail.cache_occupancy_kb }}KB
      </p>

      <h4 class="section-subtitle">待收条目核对</h4>
      <table class="data-table" data-testid="entry-table">
        <thead>
          <tr>
            <th>条目编号</th><th>测点编号</th><th>测点名称</th>
            <th>采样时间</th><th>采样值</th><th>接入状态</th><th>处置结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in detail.entries" :key="entry.条目编号"
              :data-testid="`entry-${entry.条目编号}`" :data-status="entry.接入状态">
            <td>{{ entry.条目编号 }}</td>
            <td>{{ entry.测点编号 }}</td>
            <td>{{ entry.测点名称 }}</td>
            <td>{{ entry.采样时间 }}</td>
            <td>{{ entry.采样值 }}</td>
            <td>{{ entry.接入状态 }}</td>
            <td>{{ entry.处置结果 }}</td>
          </tr>
        </tbody>
      </table>
      <div class="confirm-bar">
        <label class="verify-check">
          <input v-model="verified" type="checkbox" data-testid="verify-entries" />
          已核对待收条目（{{ detail.entries.length }} 条）
        </label>
        <button
          class="btn primary"
          data-testid="confirm-redelivery"
          type="button"
          :disabled="!verified || confirming"
          @click="confirmRedeliveryNow"
        >
          {{ confirming ? '补投中…' : '确认补投' }}
        </button>
      </div>
      <p v-if="actionMessage" class="action-message" data-testid="action-message">
        {{ actionMessage }}
      </p>

      <h4 class="section-subtitle">边缘缓存条目</h4>
      <table class="data-table" data-testid="cache-table">
        <thead>
          <tr>
            <th>缓存条目</th><th>配置编号</th><th>关联条目</th><th>测点编号</th>
            <th>占用KB</th><th>释放状态</th><th>释放依据</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in detail.cache_items" :key="item.缓存条目"
              :data-testid="`cache-${item.缓存条目}`" :data-status="item.释放状态">
            <td>{{ item.缓存条目 }}</td>
            <td>{{ item.配置编号 }}</td>
            <td>{{ item.关联条目 || '—' }}</td>
            <td>{{ item.测点编号 }}</td>
            <td>{{ item.占用KB }}</td>
            <td>
              {{ item.释放状态 }}
              <span v-if="item.释放状态 === '待确认'" class="pending-hint">（继续处理）</span>
            </td>
            <td>{{ item.释放依据 || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="confirm-bar">
        <button
          class="btn"
          data-testid="release-cache"
          type="button"
          :disabled="!clearableCount || releasing"
          @click="releaseCacheNow"
        >
          {{ releasing ? '释放中…' : `释放可清条目（${clearableCount}）` }}
        </button>
      </div>

      <h4 class="section-subtitle">接入台账（{{ gatewayId }}）</h4>
      <table class="data-table" data-testid="ledger-table">
        <thead>
          <tr>
            <th>台账编号</th><th>测点编号</th><th>测点名称</th><th>采样时间</th>
            <th>采样值</th><th>写入方式</th><th>回执状态</th><th>接入时间</th><th>来源批次</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in detail.ledger" :key="row.台账编号" :data-testid="`ledger-${row.台账编号}`">
            <td>{{ row.台账编号 }}</td>
            <td>{{ row.测点编号 }}</td>
            <td>{{ row.测点名称 }}</td>
            <td>{{ row.采样时间 }}</td>
            <td>{{ row.采样值 }}</td>
            <td>{{ row.写入方式 }}</td>
            <td>{{ row.回执状态 }}</td>
            <td>{{ row.接入时间 }}</td>
            <td>{{ row.来源批次 || '—' }}</td>
          </tr>
          <tr v-if="!detail.ledger.length">
            <td colspan="9" class="empty-state">本网关暂无接入台账记录</td>
          </tr>
        </tbody>
      </table>
    </template>

    <footer class="page-foot">
      <span>处置只对本网关本次离线批次的待收条目生效，同名测点跨网关不混发。</span>
      <span v-if="errorMessage" class="error-text" data-testid="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listEntries } from '@/api/backend-service'
import {
  confirmRedelivery,
  evictCache,
  getTicket,
  listBatches,
  listCacheItems,
  listTickets,
  openBatch,
  releaseCache,
} from '@/api/redelivery'
import type {
  RedeliveryBatch,
  RedeliveryTicket,
  TicketDetail,
} from '@/api/redelivery'

const route = useRoute()
const router = useRouter()

const gatewayId = ref(String(route.query.gateway || 'GATE-0001'))
const gatewayOptions = ref<string[]>([gatewayId.value])
const batches = ref<RedeliveryBatch[]>([])
const tickets = ref<RedeliveryTicket[]>([])
const detail = ref<TicketDetail | null>(null)
const verified = ref(false)
const confirming = ref(false)
const releasing = ref(false)
const actionMessage = ref('')
const conflictMessage = ref('')
const pageMessage = ref('')
const errorMessage = ref('')
const cacheOccupancy = ref(0)
const pendingCacheCount = ref(0)

const openTicketCount = computed(
  () => tickets.value.filter((ticket) => ticket.status !== '已办结').length,
)
const clearableCount = computed(
  () =>
    detail.value
      ? detail.value.cache_items.filter((item) => item.释放状态 === '可释放').length
      : 0,
)

async function reloadOverview() {
  const [batchItems, ticketItems, cache] = await Promise.all([
    listBatches(gatewayId.value),
    listTickets(gatewayId.value),
    listCacheItems(gatewayId.value),
  ])
  batches.value = batchItems
  tickets.value = ticketItems
  cacheOccupancy.value = cache.cache_occupancy_kb
  pendingCacheCount.value = cache.items.filter((item) => item.释放状态 === '待确认').length
}

async function loadTicket(ticketNo: string) {
  detail.value = await getTicket(ticketNo)
  verified.value = false
  await router.replace({
    query: { ...route.query, gateway: gatewayId.value, ticket: ticketNo },
  })
}

async function openOfflineBatch(batchNo: string) {
  errorMessage.value = ''
  conflictMessage.value = ''
  pageMessage.value = ''
  try {
    const result = await openBatch(batchNo)
    detail.value = result
    verified.value = false
    actionMessage.value = result.message
    await reloadOverview()
    await router.replace({
      query: { ...route.query, gateway: gatewayId.value, ticket: result.ticket.单号 },
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '打开批次失败'
  }
}

async function confirmRedeliveryNow() {
  if (!detail.value) return
  confirming.value = true
  errorMessage.value = ''
  conflictMessage.value = ''
  try {
    const result = await confirmRedelivery(detail.value.ticket.单号)
    detail.value = result
    actionMessage.value = result.message
    await reloadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补投失败'
  } finally {
    confirming.value = false
  }
}

async function releaseCacheNow() {
  if (!detail.value) return
  releasing.value = true
  errorMessage.value = ''
  try {
    const result = await releaseCache(detail.value.ticket.单号)
    detail.value = result
    actionMessage.value = result.message
    await reloadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缓存释放失败'
  } finally {
    releasing.value = false
  }
}

async function runEvict() {
  errorMessage.value = ''
  conflictMessage.value = ''
  pageMessage.value = ''
  try {
    const result = await evictCache(gatewayId.value)
    if (result.conflict && result.ticket_no) {
      // 缓存清理与重连补投冲突：留在处置页，直接打开未办结的处置单继续处理
      conflictMessage.value = result.message
      await loadTicket(result.ticket_no)
    } else {
      pageMessage.value = result.message
    }
    if (detail.value) {
      detail.value = await getTicket(detail.value.ticket.单号)
    }
    await reloadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缓存清理失败'
  }
}

async function changeGateway() {
  detail.value = null
  actionMessage.value = ''
  conflictMessage.value = ''
  pageMessage.value = ''
  await router.replace({ query: { gateway: gatewayId.value } })
  await reloadOverview()
}

onMounted(async () => {
  try {
    const payload = await listEntries('gateway_mgmt', {})
    const ids = payload.items
      .map((row) => String(row['网关编号'] ?? ''))
      .filter((id) => id)
    if (ids.length) {
      gatewayOptions.value = ids
      if (!ids.includes(gatewayId.value)) gatewayId.value = ids[0]
    }
  } catch {
    // 网关列表读取失败时保留默认选项，页面其余部分照常加载
  }
  await reloadOverview()
  const ticketNo = String(route.query.ticket || '')
  if (ticketNo) {
    try {
      detail.value = await getTicket(ticketNo)
    } catch {
      detail.value = null
    }
  }
})
</script>
