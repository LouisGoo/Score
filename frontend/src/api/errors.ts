import { ApiError } from './client'

/**
 * 客户端处理方式：
 * - relogin：会话失效，清空该身份缓存后回到登录/加入页
 * - refresh：状态或版本已变化，刷新后由用户重新确认
 * - fix：修正输入后再提交
 * - wait：按 Retry-After 等待后由用户重试
 * - verify：结果未知或需核验，先查询状态，不自动重发
 * - stop：停止操作并提示
 */
export type ErrorAction = 'relogin' | 'refresh' | 'fix' | 'wait' | 'verify' | 'stop'

interface ErrorRule {
  action: ErrorAction
  /** 服务端未给出消息时的提示；服务端消息已面向用户，优先显示。 */
  fallback: string
  /** 补充给用户的下一步建议。 */
  hint?: string
}

const rules: Record<string, ErrorRule> = {
  // 网络层（客户端生成）
  NETWORK_ERROR: { action: 'verify', fallback: '网络连接失败', hint: '请检查网络；如刚提交过操作，请先刷新核对结果' },
  TIMEOUT: { action: 'verify', fallback: '请求超时', hint: '操作可能已生效，请先刷新核对结果' },
  // 认证与请求保护
  SESSION_EXPIRED: { action: 'relogin', fallback: '登录已失效', hint: '请重新登录或验证身份' },
  INVALID_CREDENTIALS: { action: 'fix', fallback: '账号、密码或身份码不正确' },
  CONFIRMATION_EXPIRED: { action: 'fix', fallback: '身份确认已过期', hint: '请重新输入身份码' },
  CSRF_INVALID: { action: 'refresh', fallback: '页面安全令牌已失效', hint: '请刷新页面后重试' },
  ORIGIN_FORBIDDEN: { action: 'stop', fallback: '请求来源不被允许', hint: '请通过正式地址访问' },
  FORBIDDEN: { action: 'stop', fallback: '没有操作权限' },
  RATE_LIMITED: { action: 'wait', fallback: '尝试过于频繁', hint: '请稍后再试' },
  AUTH_BUSY: { action: 'wait', fallback: '服务繁忙', hint: '请稍后再试' },
  JUDGE_SESSION_ACTIVE: { action: 'stop', fallback: '该评委已在其他设备登录', hint: '换机请联系主办方重置身份码' },
  SESSION_SWITCH_REQUIRED: { action: 'stop', fallback: '当前浏览器已登录其他评委', hint: '请先退出当前身份' },
  EVENT_CLOSED: { action: 'stop', fallback: '活动已结束，不能再加入' },
  SCREEN_GRANT_INVALID: { action: 'relogin', fallback: '大屏授权无效或已到期', hint: '请联系主持人重新生成大屏链接' },
  // 通用
  NOT_FOUND: { action: 'stop', fallback: '内容不存在或无权访问' },
  METHOD_NOT_ALLOWED: { action: 'stop', fallback: '请求方式不正确' },
  HTTP_ERROR: { action: 'stop', fallback: '请求无法处理' },
  VALIDATION_ERROR: { action: 'fix', fallback: '提交的内容不合法', hint: '请检查填写内容' },
  SERVICE_UNAVAILABLE: { action: 'wait', fallback: '服务暂时不可用', hint: '请稍后刷新核对，不要重复提交' },
  INTERNAL_ERROR: { action: 'verify', fallback: '服务器内部错误', hint: '请刷新核对结果，并记录请求编号' },
  // 活动草稿、身份码、发布
  EVENT_NOT_DRAFT: { action: 'refresh', fallback: '活动已不是草稿' },
  NUMBER_CONFLICT: { action: 'fix', fallback: '编号重复' },
  CREDENTIAL_CONFLICT: { action: 'fix', fallback: '身份码与本活动其他评委重复' },
  CREDENTIAL_UNCHANGED: { action: 'fix', fallback: '新身份码不能与当前身份码相同' },
  CREDENTIAL_KEY_UNAVAILABLE: { action: 'stop', fallback: '服务端未配置身份码密钥', hint: '请联系系统管理员' },
  CREDENTIAL_GENERATION_BUSY: { action: 'wait', fallback: '身份码生成繁忙', hint: '请稍后重试' },
  RESET_NOT_ALLOWED: { action: 'refresh', fallback: '当前活动状态不允许重置身份码' },
  PUBLISH_INVALID: { action: 'fix', fallback: '活动配置不满足发布条件' },
  PUBLISH_CONFLICT: { action: 'refresh', fallback: '发布期间名单或身份码有变化', hint: '请核对后重新发布' },
  PUBLIC_CODE_BUSY: { action: 'wait', fallback: '活动码生成繁忙', hint: '请稍后重试' },
  EVENT_NOT_PUBLISHED: { action: 'refresh', fallback: '活动尚未发布' },
  // 任务控制、收评与结果
  VERSION_CONFLICT: { action: 'refresh', fallback: '数据已变化', hint: '已刷新为最新状态，请重新确认操作' },
  ROUND_STATE_CONFLICT: { action: 'refresh', fallback: '任务状态不允许此操作' },
  EVENT_NOT_RUNNING: { action: 'refresh', fallback: '活动不在进行中' },
  EVENT_STATE_CONFLICT: { action: 'refresh', fallback: '活动状态不允许此操作' },
  ACTIVE_ROUND_EXISTS: { action: 'refresh', fallback: '已有正在评分或暂停的任务' },
  CLOSE_REASON_REQUIRED: { action: 'fix', fallback: '未收齐评分，请填写收评原因' },
  INSUFFICIENT_BALLOTS: { action: 'stop', fallback: '未达到最低有效份数', hint: '可重开补评或标记无结果' },
  RESULT_AVAILABLE: { action: 'refresh', fallback: '任务已形成成绩，不能标记无结果' },
  UNFINISHED_ROUNDS: { action: 'refresh', fallback: '仍有未处理的任务' },
  DISPLAY_STATE_CONFLICT: { action: 'refresh', fallback: '当前状态不允许此展示模式' },
  SCREEN_GRANT_LIMIT: { action: 'fix', fallback: '大屏授权数量已达上限', hint: '请先撤销旧授权' },
  // 评分提交
  ROUND_NOT_OPEN: { action: 'refresh', fallback: '当前任务未开放评分', hint: '草稿已保留' },
  DEADLINE_EXCEEDED: { action: 'verify', fallback: '已超过评分截止时间', hint: '请核对是否已有提交回执' },
  RULE_VERSION_MISMATCH: { action: 'refresh', fallback: '评分规则已变化', hint: '请重新确认评分' },
  SCORE_INVALID: { action: 'fix', fallback: '分数不符合范围或步长' },
  REVISION_CONFLICT: { action: 'refresh', fallback: '评分已在其他页面修改', hint: '请查看最新评分后重新确认' },
  REVISIONS_DISABLED: { action: 'stop', fallback: '本活动不允许改分' },
  IDEMPOTENCY_CONFLICT: { action: 'verify', fallback: '提交内容与原操作不一致', hint: '请核对已保存的评分' },
  BALLOT_NOT_FOUND: { action: 'stop', fallback: '尚未提交评分' },
  RECEIPT_NOT_FOUND: { action: 'verify', fallback: '暂未查到该次提交', hint: '请稍后再次核验' },
}

export const knownErrorCodes = Object.keys(rules)

export interface ErrorDescription {
  code: string
  action: ErrorAction
  message: string
  hint?: string
  requestId: string | null
  retryAfter: number | null
}

/** 把任意异常转换为可展示的说明；未知错误码按“停止并提示”处理。 */
export function describeError(error: unknown): ErrorDescription {
  if (!(error instanceof ApiError)) {
    return { code: 'UNKNOWN', action: 'stop', message: '发生未知错误', requestId: null, retryAfter: null }
  }
  const rule = rules[error.code] ?? { action: 'stop' as const, fallback: '请求无法处理' }
  return {
    code: error.code,
    action: rule.action,
    message: error.message || rule.fallback,
    hint: rule.hint,
    requestId: error.requestId,
    retryAfter: error.retryAfter,
  }
}
