/** 网关重连补投接口封装：离线批次、处置单、幂等补投、缓存释放与台账查询。 */
import { request } from './client'

export type RedeliveryBatch = {
  批次编号: string
  网关编号: string
  离线开始: string
  重连时间: string
  待收条目数: number
  未办结条目数: number
  处置单号: string
  status: string
}

export type RedeliveryEntry = {
  条目编号: string
  批次编号: string
  网关编号: string
  测点编号: string
  测点名称: string
  采样时间: string
  采样值: string
  接入状态: string
  处置结果: string
}

export type RedeliveryTicket = {
  单号: string
  网关编号: string
  批次编号: string
  status: string
  创建时间: string
  办结时间: string
  办理次数: number
}

export type CacheItem = {
  缓存条目: string
  配置编号: string
  网关编号: string
  关联条目: string
  测点编号: string
  采样时间: string
  占用KB: number
  恢复来源: string
  释放状态: string
  释放依据: string
}

export type LedgerRow = {
  台账编号: string
  网关编号: string
  测点编号: string
  测点名称: string
  采样时间: string
  采样值: string
  写入方式: string
  回执状态: string
  接入时间: string
  来源批次: string
}

export type TicketDetail = {
  ticket: RedeliveryTicket
  entries: RedeliveryEntry[]
  cache_items: CacheItem[]
  ledger: LedgerRow[]
  cache_occupancy_kb: number
}

export type OpenBatchResult = TicketDetail & {
  ok: boolean
  created: boolean
  message: string
}

export type ConfirmResult = TicketDetail & {
  ok: boolean
  message: string
  新增接入: number
  补齐回执: number
  已有确认: number
}

export type ReleaseResult = TicketDetail & {
  ok: boolean
  message: string
  释放条目数: number
  释放占用KB: number
  待确认条目数: number
}

export type EvictResult = {
  ok: boolean
  conflict: boolean
  message: string
  ticket_no?: string
  可释放条目数?: number
  待确认条目数?: number
  释放条目数?: number
  释放占用KB?: number
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}，数据未更新`)
  return (await response.json()) as T
}

async function postJson<T>(path: string): Promise<T> {
  const response = await request(path, { method: 'POST' })
  if (!response.ok) throw new Error(`接口返回 ${response.status}，操作未完成`)
  return (await response.json()) as T
}

export async function listBatches(gatewayId: string): Promise<RedeliveryBatch[]> {
  const payload = await getJson<{ items: RedeliveryBatch[] }>(
    `/api/redelivery/batches?gateway_id=${encodeURIComponent(gatewayId)}`,
  )
  return payload.items
}

export async function listTickets(gatewayId: string): Promise<RedeliveryTicket[]> {
  const payload = await getJson<{ items: RedeliveryTicket[] }>(
    `/api/redelivery/tickets?gateway_id=${encodeURIComponent(gatewayId)}`,
  )
  return payload.items
}

export function openBatch(batchNo: string): Promise<OpenBatchResult> {
  return postJson<OpenBatchResult>(
    `/api/redelivery/batches/${encodeURIComponent(batchNo)}/open`,
  )
}

export function getTicket(ticketNo: string): Promise<TicketDetail> {
  return getJson<TicketDetail>(`/api/redelivery/tickets/${encodeURIComponent(ticketNo)}`)
}

export function confirmRedelivery(ticketNo: string): Promise<ConfirmResult> {
  return postJson<ConfirmResult>(
    `/api/redelivery/tickets/${encodeURIComponent(ticketNo)}/confirm`,
  )
}

export function releaseCache(ticketNo: string): Promise<ReleaseResult> {
  return postJson<ReleaseResult>(
    `/api/redelivery/tickets/${encodeURIComponent(ticketNo)}/release-cache`,
  )
}

export function evictCache(gatewayId: string): Promise<EvictResult> {
  return postJson<EvictResult>(
    `/api/redelivery/cache/evict?gateway_id=${encodeURIComponent(gatewayId)}`,
  )
}

export async function listLedger(gatewayId: string): Promise<LedgerRow[]> {
  const payload = await getJson<{ items: LedgerRow[] }>(
    `/api/redelivery/ledger?gateway_id=${encodeURIComponent(gatewayId)}`,
  )
  return payload.items
}

export async function listCacheItems(
  gatewayId: string,
): Promise<{ items: CacheItem[]; cache_occupancy_kb: number }> {
  return await getJson<{ items: CacheItem[]; cache_occupancy_kb: number }>(
    `/api/redelivery/cache-items?gateway_id=${encodeURIComponent(gatewayId)}`,
  )
}
