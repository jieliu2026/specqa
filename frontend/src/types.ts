/* 批0 立档（2026-10-03）：消息与出处类型，对齐 static/index.html 的 msgs[] 形态
   与服务端 SSE 字段（sources/citation_check/citation_gate 等）。 */

export interface Source {
  id?: string;
  doc_id?: string;
  version?: string;
  locator?: string;
  score?: number;
  quote?: string;
}

export interface Msg {
  role: 'user' | 'assistant';
  content: string;
  error?: boolean;
  pending?: boolean;
  /* 批B（2026-10-03）：done 事件 usage.total_tokens（入库，白名单序列化）与
     消息完成时刻（transient：不入库，刷新即无——操作条时间戳/徽标用） */
  usage?: number;
  ts?: number;
  sources?: Source[];
  offTopic?: boolean;
  /* 话术批（2026-10-16）：off_topic 事件可选 note（按缺失主题的渠道引导，
     服务端内容、截长 200，渲染层 {{ }} 插值转义；入库白名单——提示语义非瞬态） */
  otNote?: string;
  evInsufficient?: boolean;
  evReason?: string;
  /* 意图缺口批甲（2026-10-09）：通识标注条文本（insight_gap 事件 note，
     服务端内容、截长 200，渲染层 {{ }} 插值转义；入库白名单） */
  insightGap?: string;
  cc?: { overall: string; per_source: { doc_id: string; verdict: string }[] };
  cgate?: { ok: boolean; hard: number; cites: number };
  /* 末轮集成（2026-10-03）：追问建议（E2 followups 事件 items 或规则法兜底产物，
     string[] 入库白名单）；traceId=该轮 X-QA-Trace-Id（transient 不入库——刷新后
     旧消息无反馈钮，防跨会话误用旧 trace） */
  followups?: string[];
  traceId?: string;
}

/* 末轮集成：服务端会话列表行（GET /api/conversations 回包形态；updated_at=epoch 秒） */
export interface Conversation {
  id: number;
  title: string;
  updated_at?: number;
  last_role?: string | null;
}
