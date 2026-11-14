/* qa-bot 前端批次0（代理D，2026-10-03）：send() 全流程——fetch+SSE 解析+Abort。
   行为真源：static/index.html 772-923 行（SSE 事件语义/错误映射/顺序逐条照搬）；
   债务修复 a）：delta 不再逐条整建 innerHTML，改累积缓冲、requestAnimationFrame
   每帧一次并入流式消息 content（Vue 组件级重渲天然只动该气泡）。 */

import { nextTick } from 'vue';
import type { Ref } from 'vue';
import { state, streamCls, save } from '../store';
import type { Source } from '../types';

export interface ChatDeps {
  askCode: (ph?: string) => void;   // 弹口令栏（场景化占位），HTTP 错误分支 finish 后调用
  setAuthed: (v: boolean) => void;  // 登录态 UI 副作用（auth_expired/login_required 分支）
  grow: () => void;                 // 输入框高度自适应（发送清空后收缩）
  focusInput: () => void;           // finish 后焦点回主输入框
  mainRef: Ref<HTMLElement | null>; // 贴底滚动容器
  refreshConvs?: () => void;        // 末轮集成：一轮收束后静默刷新侧栏会话列表
}

/* 末轮集成：followups 事件载荷校验（E2 契约）——非 string/超 200 字/条数 0 或 >3
   整体弃用（与服务端 _parse_followup_items 同构的保守口径，宁缺毋滥）。 */
function validFollowupItems(v: unknown): string[] | null {
  if (!Array.isArray(v) || v.length < 1 || v.length > 3) return null;
  const out: string[] = [];
  for (let i = 0; i < v.length; i++) {
    if (typeof v[i] !== 'string' || !v[i] || v[i].length > 200) return null;
    out.push(v[i]);
  }
  return out;
}

/* 末轮集成：规则法追问兜底（0 元先行）——done 后无 followups 时从 msg.sources
   前 2 条生成 chip 文案；doc_id 缺省跳过该条，locator 缺省退第二模板。 */
function ruleFollowups(sources: Source[] | undefined): string[] {
  if (!Array.isArray(sources) || !sources.length) return [];
  const out: string[] = [];
  for (let i = 0; i < Math.min(2, sources.length); i++) {
    const s = sources[i];
    if (!s || typeof s !== 'object') continue;
    const doc = (s.doc_id !== undefined && s.doc_id !== null) ? String(s.doc_id) : '';
    const loc = (s.locator !== undefined && s.locator !== null) ? String(s.locator) : '';
    if (!doc) continue; // doc_id 缺省：跳过该条（无锚点不成问句）
    if (loc) out.push('关于 ' + doc + ' ' + loc + '，还有哪些相关要求？');
    else out.push(doc + ' 与相邻条款如何衔接？');
    if (out.length >= 2) break;
  }
  return out;
}

export function useChat(deps: ChatDeps) {
  let ctrl: AbortController | null = null; // 流式请求的 AbortController（停止生成用）

  function scrollBottom(): void {
    const m = deps.mainRef.value;
    if (m) m.scrollTop = m.scrollHeight; // 瞬时贴底：流式中内容仍在增长，平滑滚动追不上落点
  }

  function stop(): void {
    if (ctrl) ctrl.abort(); // 流式中=停止生成
  }

  /* 二期批A（2026-10-03）：opts.regen=重新生成标记（onRegen 专用）——仅在
     显式续写会话（currentConvId 在位）时带 X-QA-Regen:1 头，服务端写本轮
     user 消息前先删该会话末轮（案①服务端替换，历史真干净）；缺省/非法
     conv id 不带（服务端自动建新会话=无旧轮可删）。 */
  async function send(opts?: { regen?: boolean }): Promise<void> {
    const text = state.inputText.trim();
    if (!text || state.streaming) return;
    if (!state.code && !state.authed) { deps.askCode(); return; } // 凭据=服务端 cookie（authed）或暂存口令（code，双轨兼容）
    state.streaming = true;
    streamCls.waiting = true;
    streamCls.waitlong = false;
    streamCls.typing = false;
    /* 债务修复 a）rAF 批量状态 */
    let pend = '';            // delta 缓冲串（每帧一次并入）
    let rafId = 0;            // 待触发的 rAF id（0=无）
    let flushed = false;      // 首帧冲刷过（清 waiting 加 typing 只做一次）
    let erred = false;        // 流中 error 事件已到（此后不再补 typing）
    let aborted = false;      // 用户主动停止（finish 播报纪律：不播"回答完成/出错"）
    let waitTimer: ReturnType<typeof setTimeout> | null = null; // 首 delta 前 2 秒起换"正在检索语料…"文案
    const clearWait = () => { if (waitTimer) { clearTimeout(waitTimer); waitTimer = null; } };
    const lastMsg = () => state.msgs[state.msgs.length - 1];
    const applyPend = () => {
      if (pend) {
        const last = lastMsg();
        if (last) last.content += pend;
        pend = '';
      }
    };
    /* 同步冲刷（finish/停止/流中 error 前调用，保证顺序与半答不丢字） */
    const syncFlush = () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      applyPend();
    };
    const dropPend = () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      pend = '';
    };
    /* 首帧冲刷：并入缓冲、清 waiting 加 typing、贴底 */
    const flushFrame = () => {
      rafId = 0;
      applyPend();
      if (!flushed && !erred) {
        flushed = true;
        streamCls.waiting = false;
        streamCls.typing = true;
        clearWait();
      }
      nextTick(() => { if (state.stick) scrollBottom(); }); // DOM 更新后再贴底
    };
    try {
      state.inputText = '';
      nextTick(function () { deps.grow(); }); // 等 v-model 补丁落 DOM 后再量高度（清空后正确回缩）
      state.msgs.push({ role: 'user', content: text });
      state.msgs.push({ role: 'assistant', content: '', pending: true });
      save();
      /* 旧版时序保真：render()（贴底判定读 stick 旧值）先于 stick=true 执行 */
      const wasStick = state.stick;
      state.stick = true; // 用户刚提交新问题，恢复贴底跟随
      if (wasStick) nextTick(() => { if (state.stick) scrollBottom(); });
      waitTimer = setTimeout(() => { streamCls.waitlong = true; }, 2000);

      ctrl = new AbortController();
      /* 末轮集成：X-QA-Conv-Id 显式续写（可选 int；currentConvId 为 null 时不带=
         服务端自动建新会话，回读响应头更新本地态）。 */
      const chatHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
      if (state.currentConvId !== null && isFinite(state.currentConvId)) {
        chatHeaders['X-QA-Conv-Id'] = String(state.currentConvId);
        if (opts && opts.regen) chatHeaders['X-QA-Regen'] = '1';
      }
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: chatHeaders,
        signal: ctrl.signal,
        body: JSON.stringify({
          passcode: state.code,
          messages: state.msgs
            .filter((msg) => !msg.error && !msg.pending && msg.content)
            .map((msg) => ({ role: msg.role, content: msg.content }))
        })
      });
      /* 末轮集成：响应头读点——X-QA-Conv-Id（每轮回实际 id：续写被服务端静默
         换新会话时前端跟随更新）与 X-QA-Trace-Id（反馈关联，transient 存 msg：
         刷新即无=旧消息不显示反馈钮）。头缺席（旧后端/开关关）静默跳过。 */
      const hdrConv = resp.headers.get('X-QA-Conv-Id');
      if (hdrConv !== null && /^\d+$/.test(hdrConv)) {
        const cid = parseInt(hdrConv, 10);
        if (cid >= 1 && isFinite(cid)) state.currentConvId = cid;
      }
      const hdrTrace = resp.headers.get('X-QA-Trace-Id');
      if (hdrTrace) {
        const t0 = lastMsg();
        if (t0) t0.traceId = hdrTrace.slice(0, 64); // 8hex 恒态；截长保险
      }
      if (!resp.ok) {
        let info: any = {};
        try { info = await resp.json(); } catch {}
        let t: string;
        if (info.error === 'bad_passcode') t = '访问口令不正确，请重新输入。';
        else if (info.error === 'auth_expired') t = '会话已过期，请重新输入口令。';
        else if (info.error === 'login_required') t = '请重新登录后再提问。';
        else if (info.error === 'rate_limited') t = '提问太频繁啦，请稍等一分钟再试。';
        else if (info.error === 'input_too_long') t = '对话太长了，请点击"清空对话"后重新开始。';
        else t = '服务暂时不可用（' + (info.error || resp.status) + '），请稍后再试。';
        const last = lastMsg();
        if (last) { last.content = t; last.error = true; }
        save();
        finish();
        if (info.error === 'bad_passcode') deps.askCode(); // finish 后再弹口令栏，焦点落在口令输入框
        else if (info.error === 'auth_expired') { // 会话失效：撤 UI 登录态+弹口令栏
          deps.setAuthed(false);
          deps.askCode('会话已过期，请重新输入');
        } else if (info.error === 'login_required') {
          deps.setAuthed(false);
          deps.askCode('请重新登录');
        }
        return;
      }
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = '', got = false, otShown = false, insShown = false, gapShown = false;
      const handle = (part: string) => {
        if (part.indexOf('data:') !== 0) return;
        let ev: any;
        try { ev = JSON.parse(part.slice(5).trim()); } catch { return; }
        const last = lastMsg();
        if (!last) return;
        if (ev.error) {
          syncFlush(); // 冲刷在途缓冲，保证错误后缀追加在已出文本之后
          clearWait();
          streamCls.waiting = false;
          last.content += (got ? '\n' : '') + '（出错了：' + (ev.error === 'upstream_timeout' ? '上游响应超时' : '上游服务异常') + '，请重试）';
          last.error = true;
          got = true;
          erred = true;
        } else if (ev.sources) {
          // 检索出处事件（流式正文之前到达）：随消息存本地历史，渲染时挂出处条
          if (Array.isArray(ev.sources)) last.sources = ev.sources;
        } else if (ev.type === 'off_topic') {
          // 低分未命中语料（流式正文之前到达）：气泡顶部一行提示；一次性。
          // 话术批（2026-10-16）：可选 note=按缺失主题的渠道引导（服务端内容，
          // 截长 200，渲染层插值转义；旧事件无 note 字段=零第二行，向后兼容）
          if (!otShown) {
            otShown = true;
            last.offTopic = true;
            const on = (typeof ev.note === 'string') ? ev.note.slice(0, 200) : '';
            if (on) last.otNote = on;
          }
        } else if (ev.type === 'evidence_insufficient') {
          // 高危面题证据不足注意条（sources 之前到达）：reason 截长 200，渲染层转义
          if (!insShown) {
            insShown = true;
            last.evInsufficient = true;
            last.evReason = (typeof ev.reason === 'string') ? ev.reason.slice(0, 200) : '';
          }
        } else if (ev.type === 'insight_gap') {
          // 意图缺口批甲（sources 之前到达）：通识标注条，复用 offtopic 提示位；
          // note 属服务端内容，截长 200，渲染层 {{ }} 插值转义；一次性
          if (!gapShown) {
            gapShown = true;
            const gn = (typeof ev.note === 'string') ? ev.note.slice(0, 200) : '';
            if (gn) last.insightGap = gn;
          }
        } else if (ev.type === 'citation_check') {
          // 引文核实徽标：overall string + per_source Array 才落，白名单外渲染层不渲染
          if (typeof ev.overall === 'string' && Array.isArray(ev.per_source)) {
            last.cc = { overall: ev.overall, per_source: ev.per_source };
          }
        } else if (ev.type === 'citation_gate') {
          // 引用程序闸：只收 bool/数值（零注入面），非法形态不落地
          if (typeof ev.ok === 'boolean') {
            last.cgate = { ok: ev.ok, hard: +ev.hard || 0, cites: +ev.cites || 0 };
          }
        } else if (ev.type === 'followups') {
          // 末轮集成：E2 追问事件（done 之后、仅尾开到达）——items 过校验则优先
          // 于规则法兜底；非 string/超 200 字/条数 0 或 >3 整体弃用（不落地）。
          const items = validFollowupItems(ev.items);
          if (items) last.followups = items;
        } else if (ev.done === true && ev.usage) {
          // 批B：done 事件带 usage（server.py ~1320 yield {"done":true,"usage":...}）。
          // 只认 total_tokens 且 typeof number 才落（畸形/缺失=不落地，渲染层不显示）
          const tt = (ev.usage as Record<string, unknown>).total_tokens;
          if (typeof tt === 'number') last.usage = tt;
        } else if (ev.delta) {
          got = true;
          pend += ev.delta;
          if (!rafId) rafId = requestAnimationFrame(flushFrame); // 每帧批量并入一次
        }
      };
      while (true) {
        const r = await reader.read();
        if (r.done) break;
        buf += decoder.decode(r.value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (let i = 0; i < parts.length; i++) handle(parts[i]);
        if (state.stick) scrollBottom(); // 上滑脱离底部时不硬拽
      }
      buf += decoder.decode(); // 冲刷跨 chunk 的多字节残余
      if (buf) handle(buf);    // 兜底：末尾事件可能没有 \n\n 终止
      syncFlush();
      if (!got && !lastMsg().error) {
        const last = lastMsg();
        last.content = '（本轮没有返回内容，请重试）';
        last.error = true;
      }
      /* 末轮集成：追问规则法兜底（生产现状尾关无 followups 事件）——done 后
         仍无 msg.followups 且本轮非错误，从 sources 前 2 条生成；事件已到则跳过。 */
      const fm = lastMsg();
      if (fm && fm.role === 'assistant' && !fm.error && !fm.followups) {
        const ruleItems = ruleFollowups(fm.sources);
        if (ruleItems.length) fm.followups = ruleItems;
      }
      delete lastMsg().pending;
      save();
    } catch (e) {
      if ((e as any) && (e as any).name === 'AbortError') {
        // 用户主动停止：保留已生成部分、不标记错误；一字未出则给中性占位
        aborted = true;
        syncFlush(); // 停止前同步冲刷缓冲（半答不丢字）
        const am = lastMsg();
        if (am) {
          delete am.pending;
          if (!am.content) am.content = '（已停止生成）';
        }
        save();
      } else {
        dropPend();
        const em = '网络异常，请检查网络后重试。';
        const m = lastMsg();
        if (m) { m.content = em; m.error = true; }
        save();
      }
    }
    finish();
    function finish() {
      clearWait();
      syncFlush(); // finish 前同步冲刷（幂等：缓冲已空则无操作）
      const lm = lastMsg();
      if (lm && lm.role === 'assistant') lm.ts = Date.now(); // 批B：完成时刻（transient 不入库）
      streamCls.waiting = false;
      streamCls.waitlong = false;
      streamCls.typing = false;
      state.streaming = false;
      ctrl = null;
      /* 末轮集成：aria-live 播报纪律——绝不逐 token 播报；自然收束播"回答完成"、
         出错播"回答出错，请重试"；主动停止不播。先清空再 nextTick 落文=连续两轮
         同文案也能再次触发播报（同值变更屏读器不重读）。 */
      state.announce = '';
      if (!aborted) {
        const atext = (lm && lm.error) ? '回答出错，请重试' : '回答完成';
        nextTick(function () { state.announce = atext; });
      }
      if (deps.refreshConvs) {
        try { deps.refreshConvs(); } catch {} // 静默刷新侧栏（列表态自持，失败不伤主链路）
      }
      deps.focusInput();
      nextTick(() => { if (state.stick) scrollBottom(); }); // 旧版 finish→render() 的贴底
    }
  }

  return { send, stop };
}
