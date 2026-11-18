<!--
  qa-bot 前端批次0（代理D，2026-10-03）：整页布局与编排（header/main/footer/jump）。
  行为真源：static/index.html（三段式骨架+事件绑定区 353-353-770 行）。
  DOM id/类/文案/aria-label 为 Playwright 回归断言面：逐字节对齐，禁止增改；
  模板不留 HTML 注释（DOM 快照保真）。主题防闪烁脚本在 index.html（基建），不归本件。
  批B（2026-10-03）：+消息操作条 act-*（复制/重新生成/完成时刻/用量徽标）与
  出处 chip 预览卡 pv-*。既有元素断言面零改动。
  批次A2（2026-10-03 视觉 2.0）：+布局壳 .shell/.shell-body 与侧栏预留壳
  （aside.rail + .rail-mask + header 汉堡钮 #railBtn）——§2.2 规格：≥1024px
  264px 常驻轨（chrome 层）、<1024px 抽屉+遮罩；壳内仅空状态占位，不接任何
  API（会话功能接线归下一轮，DOM/事件契约=aside.rail>.rail-body 列表挂载位
  +drawerOpen ref+#railBtn aria-expanded 契约）。header 显式 56px、token 2.0
  见 base.css。既有断言面（id/class/文案/aria）零改动。
  末轮集成（2026-10-03，批次D 前端侧栏接线+批次F）：.rail-body 占位替换为
  会话列表（rail-item：标题/相对时间/active/删除钮 hover 显；加载/空/失败
  三态）+rail 头"新会话"钮；点击会话=拉 messages 替换线程（错误轮 content
  前缀 '{"error"' 标 error 渲染）；移动抽屉选中即收；快捷键（桌面 only）=
  Esc 停流(优先)否则收抽屉 / Ctrl+Shift+O 新会话 / 空输入框 ↑ 召回上一问；
  视觉隐藏 aria-live 镜像区（流式毕"回答完成"/出错播报，绝不逐 token）。
  既有断言面（id/class/文案/aria）零改动（rail-item/rail-new/rail-retry 为
  新增面）。
  二期批A（2026-10-03 体验包）：+刷新回位（restoreConvId 一次性恢复上次
  所在会话，持久键 qabot_conv 见 store.ts）+重新生成带 regen 标记（服务端
  删旧轮案①，onRegen→send({regen:true})）。既有断言面零改动。
  二期批次B/C（2026-10-03）：B=旧记录导入（纯本地四条件检测→非模态询问条
  #importBar/#importYes/#importNo→三键白名单重建载荷 POST /api/conversations/
  import，标记键 qabot_import_done+快照键 qabot_legacy_snapshot 见
  lib/constants.ts，结果四态分支）；C1=会话重命名（hover 钮 .rail-item-ren→
  行内编辑 .rail-item-input：Enter/blur 提交 PATCH {"title"}、Esc 取消）；
  C3=会话搜索（.rail-search 本地 ref+computed 大小写不敏感过滤，无匹配
  .rail-empty 新占位，仅 convLoad==='ready' 渲染）。全部新增面走新类名，
  既有 DOM id/class/文案/aria 断言面零改动。
  防抖微批（2026-10-03 晚）：loadConvs loading 期再入不再直接吞——记一次
  待重拉、在途收束后补拉一发（?code= 登录回调撞首屏在途导致侧栏空到下轮
  发消息才自愈的既有面缺陷修复；取舍见 loadConvs 注释）。零 DOM 面。
  视觉5.0 T-b hero IA 重构批（2026-10-04）：hero 重排=居中极简（ADR-0017
  决策③④；取代 3.0 T2 masthead 与 4.0 方向1 左对齐刊头+三内容卡两批登记，
  历史契约档=运营/视觉3.0-20261004/T2-DOM契约.md §八，本轮删除/新增类名与
  文案逐条登记=运营/视觉5.0-现代极简-20261004/T-b-DOM差异清单.md）。
  T-b2 用户反馈批（2026-10-04 检查点后）：用户实见四张空态截图后指令①——
  hero 二次裁剪：T-b 批的 logo 标记件与眉题件（两类名，删除穷举登记=差异
  清单 §十三）DOM 整体删除。hero 终态（.thread.empty 挂点维持唯一子容器）=
  .hero-title 主标题（原衬线字盘常量表 W1 串写死模板——衬线管线随 5.0 退役、
  import 移除，无衬线 semibold；title 成视觉起点）→.hero-chips 建议 chips
  一排（.hero-chips 容器+.hero-chip button×5+内嵌 .hero-chip-txt 问句
  span；文案=既有真实条目精选零编造，五枚逐字零改）。
  同批指令②③备案区自然化：ICP 徽章装饰盾牌内联 SVG 删除，.icp 卡片式徽章带
  改纯文本小字链接单行居中（公安徽标 img 保留内联，高 14px=备案展示法规
  要求）；.icp 容器类与两 <a> 的 href/文本逐字保留（备案链接契约零动）。
  删除面：4.0 刊头件与三内容卡全套旧类（穷举清单见差异清单档，本注不复述
  防旧类名残留 grep 命中）。
  行为契约逐字保持：onMainClick 事件委托检 .hero-chip、取内嵌
  .hero-chip-txt 文本（trim 原串）填入 #input→grow()+focusInput()，不自动
  发送。既有其余断言面（id/class/文案/aria）零改动。
  5.0 反馈批2（2026-10-04 桌面布局校准）：①正文列加宽 --col 720→880
  （tokens.css 单值；skeleton.css 五消费点全 max/calc 钳制形态自动跟随）；
  ②阅读字号升档 .msg.bot .txt fs-16→fs-17（message.css，行高 1.75 零改；
  40em 行长上限退役——裁决与备选登记=运营/视觉5.0-现代极简-20261004/
  T-b-DOM差异清单.md §十四）；③桌面侧栏可折叠（双屏场景，用户反馈
  「左侧导航栏电脑上不能隐藏」）——≥1024 #railBtn 汉堡钮由隐藏改常显
  （chrome.css 原 display:none 覆写退役），点击切换 state.railCollapsed
  （.shell 条件类 rail-collapsed：rail 收零宽+.shell-body 吃满全宽+mask
  不启用+dur-2 过渡）；持久化=store.ts 新键 qabot_rail_collapsed（'1'=
  折叠/展开=删键零足迹；初值 localStorage 恢复=刷新恢复折叠态）；过程日志
  语义=折叠态仅 ≥1024 生效（isDesktop=matchMedia 与 CSS 媒体查询同值
  过程日志），<1024 抽屉口径零改（mask/开合/Esc 收契约原样），跨过程日志 resize
  各守各过程日志天然成立；aria-expanded 扩展双语义（≥1024=rail 可见态默认
  true/<1024=抽屉开态默认 false 原样），aria-label「会话列表」两态零改
  （状态由 aria-expanded 表达），aria-controls 现 DOM 本就未绑定（aside.rail
  无 id）「维持」=不新增；折叠态下汉堡钮为唯一入口，不加新浮钮（克制）。
  .jump 右缘对齐折叠态覆写在 skeleton.css（#jumpBtn 为 .shell 下一兄弟）。
  5.0 反馈批4（同日）：追问引导与点赞踩整组退役（组件面=BotMessage.vue）
  ——本件 BotMessage 标签 @fill/@askcode 绑定与 onFuFill 函数同批退役
  （askCode 本体仍在 useChat 接线与会话 401 路径在役）；hero 首屏
  .hero-chip 与 onMainClick 委托契约保留逐字零动（用户决策件，词族区分）。
  登记=差异清单 §十四/§十六。
  5.0 反馈批5（2026-10-04 A 级流程，数值冻结与 T-d3 并行同值）：①header
  登出钮退役（用户决策=仅 UI 入口退役）——钮 DOM 与点击 handler 整体删除、
  v-show="state.authed" 显隐消费面随钮消失；后端 /api/logout 与 cookie
  会话链路保留在役，useChat 401 过期路径（setAuthed(false)→askCode）与
  登录态链路（setAuthed/checkHealth 判级/qabot_auth 持久化）零动。
  ②清空钮图标化两态：#clearBtn 增 aria-label「清空对话」（逐字=原钮文案，
  可及名两态一致）＋内嵌垃圾桶 SVG（.clear-ico，aria-hidden，零外链零新
  资产）＋文字节点收进 span（.clear-txt）——≤540 文字隐藏图标显示（40×40
  触屏目标），>540 桌面文字态零改（样式面=skeleton.css 同批）。③桌面正文
  再升档（--col 940/--fs-18）=tokens.css/message.css 同批单点，本件模板与
  逻辑零波及。退役 id/类名/handler 字面本注刻意不复述（grep 清零口径），
  穷举登记=运营/视觉5.0-现代极简-20261004/T-b-DOM差异清单.md §十七。
  差评回流采集批（2026-10-17，扩源形状战 v5 计划 §2 决策位⑥；过程日志 106 号
  全链授权）：BotMessage 增 :question prop（pairedQuestion(i)=向前最近的
  user 消息题面——差评采集点载荷用，err 轮跳过；缺席=组件内按钮不渲染）；
  既有 DOM id/class/文案/aria 断言面零改动（差评钮/.badfb-* 为组件内新增面，
  避开 5.0 反馈批4 退役断言族 .fb-*/.fu-*）。
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import BotMessage from './components/BotMessage.vue';
import { useChat } from './composables/useChat';
import { state, save, lsGet, lsSet, lsDel } from './store';
import { KEY_MSGS, KEY_CODE, KEY_THEME, KEY_AUTH, KEY_CONV, KEY_IMPORT_DONE, KEY_LEGACY_SNAPSHOT } from './lib/constants';
import type { Conversation } from './types';

const mainRef = ref<HTMLElement | null>(null);
const inputRef = ref<HTMLTextAreaElement | null>(null);
const codeInputRef = ref<HTMLInputElement | null>(null);
const footerRef = ref<HTMLElement | null>(null);
const codeVal = ref('');
const showJump = ref(false);

/* ============ 批次A2：侧栏抽屉态（<1024px）＋5.0 反馈批2：桌面折叠态（≥1024px） ============
   <1024：遮罩点按收、Esc 收（末轮集成起 Esc 全局归 onGlobalKey：流式中停止
   优先，否则收抽屉——抽屉 Esc 收的 A2 契约保留）；遮罩由 !important 兜底
   不残留。
   5.0 反馈批2（2026-10-04）：≥1024 #railBtn 由隐藏改常显，点击语义分岔——
   桌面=切换 rail 折叠（state.railCollapsed，store watch 持久化
   qabot_rail_collapsed、初值恢复=刷新保持；chrome.css ≥1024 媒体块收零宽、
   .shell-body 吃满、mask 不启用）；<1024=抽屉开合原样。折叠态仅 ≥1024
   生效：样式（媒体查询）与 JS（matchMedia 同值过程日志）双闸各守，跨过程日志
   resize：<1024 忽略折叠态、回 ≥1024 按 store 恢复，零额外监听。 */
const drawerOpen = ref(false);

/* 桌面过程日志探测（照 touchMq 先例防御：matchMedia 不可得回退 false=点击走
   抽屉语义；CSS 侧媒体块照常——偏差窗仅限无 matchMedia 的古董引擎） */
let desktopMq: MediaQueryList | null = null;
try { desktopMq = (typeof window.matchMedia === 'function') ? window.matchMedia('(min-width: 1024px)') : null; } catch {}
const isDesktop = ref<boolean>(desktopMq ? desktopMq.matches : false);
function syncDesktop(): void { if (desktopMq) isDesktop.value = desktopMq.matches; }
if (desktopMq) { try { desktopMq.addEventListener('change', syncDesktop); } catch {} }

function onRailBtn(): void {
  if (isDesktop.value) state.railCollapsed = !state.railCollapsed; // ≥1024：折叠/展开 rail
  else drawerOpen.value = !drawerOpen.value;                        // <1024：抽屉开合（A2 原契约）
}

/* aria-expanded 双语义（反馈批2 扩展）：≥1024=rail 可见态（默认展开=true）；
   <1024=抽屉开态（默认关=false 原样）。aria-label「会话列表」两态零改、
   aria-controls 不新增（登记=差异清单 §十四）。 */
const railExpanded = computed<'true' | 'false'>(function () {
  return (isDesktop.value ? !state.railCollapsed : drawerOpen.value) ? 'true' : 'false';
});

/* 桌面能力探测（批次F 快捷键门）：hover:hover 才启用 Esc 停流/Ctrl+Shift+O/
   ↑ 召回（触屏无键盘语义；同 BotMessage 预览卡模态判据） */
const canHover: boolean = (function () {
  try { return typeof window.matchMedia === 'function' && window.matchMedia('(hover: hover)').matches; }
  catch { return false; }
})();

/* ============ 末轮集成：侧栏会话列表（GET /api/conversations） ============
   三态纪律：loading/ready（含空列表）/error（点击重试）；404=服务端
   conversations_enabled=false 的'off'态；401=未登录按空列表处理（登录成功
   后自动重拉，不打扰匿名首屏）。行形状运行时防御（id 必须 finite 正整数，
   title 截 100 字）。 */
let convReloadQueued = false; // 防抖微批（2026-10-03）：loading 期再入的补拉标记
function loadConvs(): void {
  /* 防抖：在途请求不叠加；但再入不白吞——记一次待重拉，在途收束后补拉一发。
     取舍：①不豁免并发 GET（响应乱序落地会拿旧 401/旧列表覆盖新结果，需引
     入请求序号才安全，侵入大）；②不做完全重入（同上叠加+乱序两险）。选
     "记待重拉+收束后补拉"：任何调用方（?code=/legacy 登录回调、发消息后
     refreshConvs、删除/导入毕）撞在途最多延迟一发、零叠加零乱序，登录
     回调的重拉必然生效（?code= 路径首屏 GET 未带 cookie 回 401 后，补拉
     带 cookie 拿真列表——侧栏不再空到下轮发消息）。 */
  if (state.convLoad === 'loading') { convReloadQueued = true; return; }
  state.convLoad = 'loading';
  fetch('/api/conversations')
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok && Array.isArray(res.j.conversations)) {
        state.convs = (res.j.conversations as any[]).filter(function (c: any) {
          return c && typeof c.id === 'number' && isFinite(c.id) && c.id >= 1;
        }).map(function (c: any) {
          return {
            id: c.id,
            title: String(c.title || '（无标题）').slice(0, 100),
            updated_at: (typeof c.updated_at === 'number' && isFinite(c.updated_at)) ? c.updated_at : undefined,
            last_role: (typeof c.last_role === 'string') ? c.last_role : null,
          } as Conversation;
        });
        state.convLoad = 'ready';
        maybeRestoreConv();
      } else if (res.status === 401) {
        state.convs = [];
        state.convLoad = 'ready'; // 未登录：无会话可列（登录后重拉自愈）
        // 401 不消费恢复目标：匿名期列表未知，登录后重拉再判
      } else if (res.status === 404) {
        state.convs = [];
        state.convLoad = 'off'; // 服务端开关关：功能未启用占位
        restoreConvId = null;   // 功能未启用：恢复目标作废（一次性消费）
      } else {
        state.convLoad = 'error';
      }
    })
    .catch(function () { state.convLoad = 'error'; })
    .then(function () {
      /* 防抖微批：在途收束（含网络错兜底分支后必经）——有待重拉则补一发。
         标记先清再拉：补拉期间若又有再入，会重新置标记，逐次消化不叠加。 */
      if (!convReloadQueued) return;
      convReloadQueued = false;
      loadConvs();
    });
}

/* ============ 二期批A（2026-10-03）：刷新回位 ============
   持久键 qabot_conv（store.ts watch 写入）解析出上次所在会话 id；loadConvs
   列表就绪后若该 id 在列则走 restoreConv 恢复。一次性消费：在列=恢复，不在列
   （他端已删/50 帽外）=作废回退现状行为。 */
let restoreConvId: number | null = (function () {
  const n: number = parseInt(lsGet(KEY_CONV) || '', 10);
  return isFinite(n) && n >= 1 ? n : null;
})();
function maybeRestoreConv(): void {
  if (restoreConvId === null) return;
  const target = restoreConvId;
  restoreConvId = null; // 消费点：列表就绪即定（401/error 态不进此函数=不消费）
  const hit = state.convs.find(function (c) { return c.id === target; });
  if (hit) restoreConv(hit);
}

/* 二期批A：恢复专用路径——刻意不复用 onConvClick（其语义=用户主动切换线程，
   富字段直接让位服务端）。恢复场景的本地 msgs 是刷新前该会话的镜像（watch
   不变量：msgs 恒随 currentConvId 同步），故服务端恢复序列与本地逐位
   (role+content) 对齐处继承本地富字段——followups/usage/cc/cgate/offTopic/
   evInsufficient/evReason 均不落服务端，不合并则在"刷新回位"语义下丢失
   （integration⑫ followups 刷新持久化断言的守门）；sources 服务端权威、
   null 时本地兜底；失配位起全服务端（跨设备新轮/服务端已变更，本地旧镜像
   让位）。任何失败（401 窗口期过期/网络）=回退现状刷新行为：本地 msgs
   原样显示、选中态不设。 */
function restoreConv(c: Conversation): void {
  if (state.streaming) return; // 流式守卫（对齐 onConvClick）：流中恢复会整体替换 msgs 丢事件落点
  state.convSwitching = true;
  fetch('/api/conversations/' + c.id + '/messages')
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok && Array.isArray(res.j.messages)) {
        const prev = state.msgs;
        state.msgs = (res.j.messages as any[]).filter(function (mm: any) {
          return mm && typeof mm.content === 'string' && (mm.role === 'user' || mm.role === 'assistant');
        }).map(function (mm: any) {
          const o: any = { role: mm.role, content: mm.content };
          if (Array.isArray(mm.sources) && mm.sources.length) o.sources = mm.sources;
          // 错误轮契约（同 onConvClick）：content='{"error' 前缀 → 错误气泡
          if (mm.role === 'assistant' && mm.content.indexOf('{"error"') === 0) o.error = true;
          return o as (typeof state.msgs)[number];
        });
        const RICH = ['followups', 'usage', 'cc', 'cgate', 'offTopic',
                      'evInsufficient', 'evReason'] as const;
        for (let i = 0; i < state.msgs.length; i++) {
          const p = prev[i] as any;
          const o = state.msgs[i] as any;
          if (p && p.role === o.role && p.content === o.content) {
            if (o.sources === undefined && p.sources !== undefined) o.sources = p.sources;
            for (let k = 0; k < RICH.length; k++) {
              const key = RICH[k];
              if (p[key] !== undefined) o[key] = p[key];
            }
          }
        }
        // 尾部半答保留：服务端断流不落半截答案（批次D 定案），本地停止的
        // 半答是该轮唯一痕迹——本地比服务端多出的尾部首条若为 assistant、
        // 且服务端末条 user 与本地同位 user 对齐（同一问），保留该半答。
        // 本地多出整轮（首条为 user，理论仅跨设备差异态）不让位规则不适用
        // ——不保留，让位服务端。
        if (prev.length > state.msgs.length) {
          const tailFirst = prev[state.msgs.length] as any;
          const lastSrv = state.msgs[state.msgs.length - 1] as any;
          const lastPrevUser = prev[state.msgs.length - 1] as any;
          if (tailFirst && tailFirst.role === 'assistant' && lastSrv &&
              lastSrv.role === 'user' && lastPrevUser &&
              lastPrevUser.role === 'user' && lastPrevUser.content === lastSrv.content) {
            state.msgs.push(tailFirst as (typeof state.msgs)[number]);
          }
        }
        state.currentConvId = c.id;
        save();
        state.stick = true;
        nextTick(function () { scrollBottom(); });
        drawerOpen.value = false;
      }
      // 失败分支：不设选中态、不动本地线程（现状刷新行为即回退位）
    })
    .catch(function () { /* 网络失败：保持本地线程 */ })
    .then(function () { state.convSwitching = false; });
}

/* 相对时间（updated_at=epoch 秒）：刚刚/N 分钟前/N 小时前/N 天前/超 30 天落日期 */
function p2(n: number): string { return (n < 10 ? '0' : '') + n; }
function relTime(v: unknown): string {
  const n = (typeof v === 'number') ? v : parseFloat(String(v));
  if (!isFinite(n) || n <= 0) return '';
  const diff = Date.now() / 1000 - n;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  if (diff < 30 * 86400) return Math.floor(diff / 86400) + ' 天前';
  const d = new Date(n * 1000);
  return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
}

/* 新会话：清当前线程+qabot_msgs（不删服务端）、currentConvId=null（下次发送
   自动挂新服务端会话）；流式中先停流再清（防流中清空的孤儿写入）。 */
function onNewConv(): void {
  if (state.convSwitching) return;
  if (state.streaming) stop();
  restoreConvId = null; // 用户显式弃旧会话：挂起的恢复目标随之作废（防流中换数组丢事件落点）
  state.msgs = [];
  save();
  state.currentConvId = null;
  drawerOpen.value = false; // 移动抽屉收起（桌面态无效）
  nextTick(function () { focusInput(); });
}

/* 点击会话=拉取 messages 替换 state.msgs+save+贴底；convSwitching 锁防抖+
   流中禁切（流写入竞态）；404（他端已删）等静默回列表刷新自愈。 */
function onConvClick(c: Conversation): void {
  if (state.convSwitching || state.streaming) return;
  const cid = c.id;
  if (cid === state.currentConvId) { drawerOpen.value = false; return; } // 已是当前会话：仅收抽屉
  state.convSwitching = true;
  fetch('/api/conversations/' + cid + '/messages')
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok && Array.isArray(res.j.messages)) {
        state.msgs = (res.j.messages as any[]).filter(function (mm: any) {
          return mm && typeof mm.content === 'string' && (mm.role === 'user' || mm.role === 'assistant');
        }).map(function (mm: any) {
          const o: any = { role: mm.role, content: mm.content };
          if (Array.isArray(mm.sources) && mm.sources.length) o.sources = mm.sources;
          // 错误轮契约：assistant content=错误 SSE JSON 原文（如 {"error": "upstream_timeout"}）
          // 前缀 '{"error"' → 标 error 渲染成错误气泡（纯文本折行，不进 markdown）
          if (mm.role === 'assistant' && mm.content.indexOf('{"error"') === 0) o.error = true;
          return o as (typeof state.msgs)[number];
        });
        state.currentConvId = cid;
        save();
        state.stick = true;
        nextTick(function () { scrollBottom(); }); // 切换后贴底
        drawerOpen.value = false; // 移动抽屉选中即收
      } else if (res.status === 401) {
        askCode('请重新登录');
      } else {
        loadConvs(); // 404/坏档：列表刷新自愈（选中态不变）
      }
    })
    .catch(function () { /* 网络失败：保持原线程与选中态 */ })
    .then(function () { state.convSwitching = false; });
}

/* 删除会话：confirm → DELETE → 列表刷新；删的是当前会话则清空回新会话态。 */
function onConvDelete(c: Conversation): void {
  if (state.convSwitching) return;
  const title = c.title || '该会话';
  if (!confirm('删除会话「' + title + '」？删除后不可恢复。')) return;
  if (state.streaming && state.currentConvId === c.id) stop(); // 删当前会话先停流
  fetch('/api/conversations/' + c.id, { method: 'DELETE' })
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok) {
        if (state.currentConvId === c.id) {
          state.msgs = [];
          save();
          state.currentConvId = null; // 清空回新会话态（服务端行已删）
        }
        loadConvs();
      } else if (res.status === 401) {
        askCode('请重新登录');
      } else {
        loadConvs(); // 404（他端已删）等：刷新列表自愈
      }
    })
    .catch(function () { loadConvs(); });
}

/* ============ 二期批次C1（2026-10-03）：会话重命名（hover 钮+行内编辑） ============
   入口照 .rail-item-del 先例：hover 显、disabled 对齐删除钮口径（convSwitching
   锁；流式中允许改名——PATCH 独立于 SSE 流无竞态面）。行内编辑（title 原位换
   input，排除 prompt()：阻塞线程/样式失控/IME 不友好）：Enter/blur 提交
   PATCH {"title"}、Esc 取消（stopPropagation 防冒泡给全局 Esc——收抽屉/停流）；
   清空（strip 后空）提交=前端闸不发 PATCH 恢复原态；编辑期间该行删除钮禁用
   （同 item 并发防御）。成功=本地 convs 行 title 就地更新（不重拉列表）；
   401=askCode；失败/网络错=恢复原态静默不重拉。 */
const renId = ref<number | null>(null); // 编辑态会话 id（null=无编辑）
const renVal = ref('');                 // 编辑框值
const renBusy = ref(false);             // 提交中锁（防重复提交/Esc 抢跑）
function onConvRename(c: Conversation): void {
  if (state.convSwitching || renBusy.value) return;
  renId.value = c.id;
  renVal.value = c.title;
  nextTick(function () {
    const el = document.querySelector('.rail-item-input') as HTMLInputElement | null;
    if (el) { try { el.focus(); el.select(); } catch {} }
  });
}
function renExit(): void {
  renId.value = null;
  renVal.value = '';
}
function onRenSubmit(): void {
  if (renId.value === null || renBusy.value) return;
  const cid = renId.value;
  const t = renVal.value.trim();
  if (!t) { renExit(); return; } // 前端闸：strip 后空不发 PATCH、标题不变
  renBusy.value = true;
  fetch('/api/conversations/' + cid, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: t })
  })
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok) {
        const row = state.convs.find(function (c) { return c.id === cid; });
        if (row) row.title = t.slice(0, 100); // 本地就地更新（对齐 loadConvs 显示层防御口径）
      } else if (res.status === 401) {
        askCode('请重新登录'); // 对齐删除钮 askCode 口径，不自动重试
      }
      renExit(); // 成功=退出编辑态；失败/401=恢复原态（标题不变）
    })
    .catch(function () { renExit(); }) // 网络失败：编辑态退回原标题，静默不重拉
    .then(function () { renBusy.value = false; });
}
function onRenKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.stopPropagation(); // Esc 只作用于编辑框：不冒泡给全局键（收抽屉/停流）
    if (!e.isComposing && !renBusy.value) renExit(); // 提交在途不抢跑（响应统一收口）
    return;
  }
  const isEnter = e.key === 'Enter' || (!e.key && e.keyCode === 13);
  if (isEnter && !e.shiftKey && !e.isComposing) { e.preventDefault(); onRenSubmit(); }
}

/* ============ 二期批次C3（2026-10-03）：会话搜索（纯本地过滤，零后端） ============
   查询词为组件本地 ref 不入 store 持久化（刷新即清——搜索词是短期意图）；
   computed 大小写不敏感 includes 过滤 title（loadConvs 已保证 title 为 string）；
   trim 后空=全量直通。不受 convSwitching 锁影响（零请求）；loadConvs 重拉
   （发消息后 refreshConvs）时查询词保留、过滤自动套新列表。搜索框仅
   convLoad==='ready' 态渲染（loading 防闪、off/error 无列表可滤）。 */
const railQ = ref('');
const filteredConvs = computed<Conversation[]>(function () {
  const q = railQ.value.trim().toLowerCase();
  if (!q) return state.convs;
  return state.convs.filter(function (c) {
    return c.title.toLowerCase().includes(q);
  });
});

/* ============ 主题：显式选择记忆优先于系统偏好；同步浏览器外壳色（theme-color meta） ============ */
function applyTheme(t: string): void {
  document.documentElement.dataset.theme = t;
  const m = document.querySelector('meta[name="theme-color"]');
  if (m) (m as HTMLMetaElement).content = (t === 'dark') ? '#1e1e1e' : '#ffffff';
}
function onTheme(): void {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  lsSet(KEY_THEME, next);
}

/* ============ 主输入框 ============ */
function grow(): void {
  const el = inputRef.value;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}
function focusInput(): void {
  if (inputRef.value) inputRef.value.focus();
}
function onInputKey(e: KeyboardEvent): void {
  /* 批次F：输入框空时 ↑=召回上一问文本（桌面 only；触屏软键盘 ↑ 无语义） */
  if (e.key === 'ArrowUp' && canHover && !state.inputText) {
    for (let i = state.msgs.length - 1; i >= 0; i--) {
      if (state.msgs[i].role === 'user') {
        const q = String(state.msgs[i].content || '');
        if (q) {
          state.inputText = q;
          e.preventDefault();
          nextTick(function () { grow(); }); // 等 v-model 补丁落 DOM 后再量高度
        }
        break; // 只看最近一条 user（无上一问则交还默认行为）
      }
    }
    return;
  }
  const isEnter = e.key === 'Enter' || (!e.key && e.keyCode === 13);
  if (isEnter && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
}

/* 触屏设备把"Enter 发送"提示换成中性文案（软键盘无 Enter 语义）。
   债务修复 c）：不再只在启动时判一次，跟随 (hover: none) 媒体查询变化重判 */
let touchMq: MediaQueryList | null = null;
try { touchMq = (typeof window.matchMedia === 'function') ? window.matchMedia('(hover: none)') : null; } catch {}
function syncTouchPh(): void {
  state.inputPh = (touchMq && touchMq.matches) ? '输入你的问题…' : '输入你的问题…（Enter 发送）';
}
syncTouchPh();
if (touchMq) { try { touchMq.addEventListener('change', syncTouchPh); } catch {} }

/* ============ 贴底滚动纪律：滚动位置变化时判定是否脱离底部，脱离则亮回底浮钮 ============ */
function scrollBottom(): void {
  const m = mainRef.value;
  if (m) m.scrollTop = m.scrollHeight; // 瞬时回底：流式中内容仍在增长，平滑滚动会追不上落点
}
function onScroll(): void {
  const m = mainRef.value;
  if (!m) return;
  state.stick = m.scrollHeight - m.scrollTop - m.clientHeight < 48;
  showJump.value = !state.stick;
}
function onJump(): void {
  scrollBottom();
}

/* ============ 登录/健康 ============ */
function askCode(ph?: string): void {
  state.codeShow = true;
  if (ph) state.codePh = ph; // 场景化文案（会话过期/需重新登录），缺省沿用现占位
  nextTick(() => { if (codeInputRef.value) codeInputRef.value.focus(); });
}
function setAuthed(v: boolean): void {
  state.authed = v; // 登录态（5.0 反馈批5：原 header 登出钮显隐 v-show 消费面随钮退役；authed 在役消费=checkHealth POST 判级＋qabot_auth 持久化＋useChat 401 路径回置）
  if (v) lsSet(KEY_AUTH, '1'); else lsDel(KEY_AUTH);
}
function loginFail(info: any): void {
  // 口令栏保持展开：清输入+红边+占位提示（口令本身绝不回显、不落任何存储）
  state.code = '';
  lsDel(KEY_CODE); // 残留的旧明文口令一并出清（登录失败=不可信）
  state.codeShow = true;
  codeVal.value = '';
  state.codeErr = true;
  let ph = '登录失败，请重试';
  if (info && info.error === 'bad_passcode') ph = '口令不正确，请重新输入';
  else if (info && info.error === 'too_many_attempts') {
    // 登录限速（429：同 IP 错 5 次锁 10 分钟）：秒数动态文案优先，
    // 缺 retry_after_s 时退后端 message，再退静态兜底
    const wait = Number(info.retry_after_s);
    ph = isFinite(wait) && wait > 0
      ? '尝试次数过多，请 ' + Math.ceil(wait) + ' 秒后再试'
      : (info.message || '尝试次数过多，请稍后再试');
  }
  state.codePh = ph;
  setTimeout(() => {
    state.codeErr = false;
    if (codeInputRef.value) codeInputRef.value.focus();
  }, 100);
}
function attemptLogin(pc: string): void {
  pc = String(pc || '').trim();
  if (!pc) return;
  fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ passcode: pc })
  }).then(function (r) {
    return r.json().then(function (j: any) { return { ok: r.ok, j: j }; });
  }).then(function (res) {
    if (res.ok && res.j && res.j.ok) {
      state.code = '';
      lsDel(KEY_CODE);        // 明文口令即刻出清（兼容旧键名也在）
      setAuthed(true);
      state.codeShow = false;
      state.codePh = '请输入访问口令';
      checkHealth();          // 登录后重查健康：cookie 会话换完整字段（bot_name 等）
      loadConvs();            // 末轮集成：登录成即拉会话列表（匿名期的空列表自愈）
    } else {
      loginFail(res.j);
    }
  }).catch(function () { loginFail(null); });
}
function onCodeBtn(): void {
  const pc = codeVal.value.trim();
  if (!pc) return;
  attemptLogin(pc); // 口令只上送 /api/login 换 HttpOnly cookie，不再落 localStorage
}
function onCodeKey(e: KeyboardEvent): void {
  if (e.key === 'Enter') { e.preventDefault(); onCodeBtn(); }
}
/* 5.0 反馈批5（2026-10-04）：登出 handler 随 header 登出钮退役整体删除
   （用户决策=仅 UI 入口退役）——后端 /api/logout 与 cookie 会话链路保留
   在役；会话失效的在役路径=cookie 过期/useChat 401→setAuthed(false)→
   askCode 重登提示，qabot_auth 清理面不变。退役登记=运营/视觉5.0-现代
   极简-20261004/T-b-DOM差异清单.md §十七.1。 */
/* 健康检查分级：已存口令或已登录则 POST 换完整字段（bot_name/has_key）；GET 只回 {ok:true}
   ——口令绝不经 URL 传递（防落入访问日志）。两者皆无时状态灯按 ok 判活（has_key 不可见=
   未知不判死），bot_name 待口令/登录补查后回填。 */
function checkHealth(): void {
  const usePost = !!state.code || state.authed;
  const req = usePost
    ? fetch('/api/health', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passcode: state.code })
      })
    : fetch('/api/health');
  try {
    req.then(function (r) { return r.json(); })
      .then(function (h: any) {
        if (h && h.bot_name) {
          state.botLabel = h.bot_name; // #botName 文案+role 标签同源
          document.title = h.bot_name;
        }
        /* 批B：模型名（POST 全量态才有；GET 未过级回包无此字段=置空）。
           typeof string 才落+截 100 保险；title 挂 #statusDot 悬停提示 */
        state.model = (h && typeof h.model === 'string') ? h.model.slice(0, 100) : '';
        state.dotState = (h && h.ok && h.has_key !== false) ? 'ok' : 'down';
      }).catch(function () { state.dotState = 'down'; });
  } catch { state.dotState = 'down'; }
}

/* 批B：状态灯悬停提示——down=服务异常；ok 带模型名=「服务正常 · 模型 X」，
   未过级 GET 只有 ok（无 model）=状态描述不含模型名；init（健康未回）不挂 title */
const dotTitle = computed<string>(function () {
  if (state.dotState === 'down') return '服务异常';
  if (state.dotState === 'ok') return state.model ? '服务正常 · 模型 ' + state.model : '服务正常';
  return '';
});

/* ============ 清空对话 ============ */
function onClear(): void {
  if (!confirm('确定清空当前对话？')) return;
  state.msgs = [];
  save();
  nextTick(() => { if (state.stick && state.msgs.length) scrollBottom(); }); /* 方向1 T-b：清空回空态不贴底（hero 溢出时贴底=刊头卷出首屏，见 T2 §8.4） */
}

/* ============ 事件委托：代码块复制 / 空状态 hero-chip（出处条 +N/收起在 BotMessage 内自持） ============
   视觉5.0 T-b（2026-10-04）：委托选择器随 hero IA 重构改 .hero-chip（行为契约
   框架逐字沿 T2-DOM契约.md §三：取内嵌文本节点填入不发送；登记=差异清单档）。 */
function copyText(t: string, btn: HTMLElement): void {
  const done = function () {
    btn.textContent = '已复制';
    setTimeout(function () { btn.textContent = '复制'; }, 1200);
  };
  const fallback = function () { // 非安全上下文（如局域网 http）无 clipboard API 时的兜底
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch {}
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(done, fallback);
  } else fallback();
}
function onMainClick(e: MouseEvent): void {
  const main = mainRef.value;
  if (!main) return;
  let el = e.target as HTMLElement | null;
  while (el && el !== main) {
    if (el.classList && el.classList.contains('cb-copy')) {
      const block = el.parentNode ? el.parentNode.parentNode as HTMLElement | null : null;
      const code = block ? block.querySelector('pre code') : null;
      if (code) copyText(code.textContent || '', el);
      return;
    }
    if (el.classList && el.classList.contains('hero-chip')) {
      /* 5.0 T-b 行为契约（T2 §三框架逐字维持）：取 chip 内 .hero-chip-txt 文本
         （trim 后原串；chip 唯一文本节点=问句，装饰不入框——禁整 chip
         textContent 口径沿袭）；填入不自动发送 */
      const txt = el.querySelector('.hero-chip-txt');
      state.inputText = txt && txt.textContent ? txt.textContent.trim() : '';
      nextTick(function () { grow(); }); // 等 v-model 补丁落 DOM 后再量高度
      focusInput();
      return;
    }
    el = el.parentNode as HTMLElement | null;
  }
}

/* ============ send 全流程（composables/useChat） ============
   末轮集成：refreshConvs=一轮收束后静默刷新侧栏列表（updated_at 重排序自愈）。 */
const { send, stop } = useChat({ askCode, setAuthed, grow, focusInput, mainRef, refreshConvs: loadConvs });
function onSendBtn(): void {
  if (state.streaming) stop(); // 流式中=停止生成
  else send();
}

/* ============ 批次F：全局快捷键（桌面 hover:hover only） ============
   Esc=流式中停止（优先）否则收抽屉（A2 抽屉 Esc 契约保留）；Ctrl/Cmd+Shift+O=
   新会话。触屏无键盘语义不启用（canHover 门）。 */
function onGlobalKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    if (state.streaming && canHover) { stop(); return; }
    if (drawerOpen.value) drawerOpen.value = false;
    return;
  }
  if (canHover && (e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'o' || e.key === 'O')) {
    e.preventDefault();
    onNewConv();
  }
}

/* 5.0 反馈批4（2026-10-04）：追问 chip 点击填入回抛（onFuFill）随组件退役
   删除——hero 首屏 .hero-chip 的 onMainClick 委托填入契约逐字保留零动
   （用户决策件；穷举登记=差异清单 §十六） */

/* ============ 差评回流采集批（2026-10-17，决策位⑥）：配对题面取数 ============
   模板 v-for 下标传入，向前找最近的 user 消息原文（err 轮 user 气泡可能
   缺席——找不到回空串=组件内差评钮不渲染，与服务端 question 必填同口径）。
   纯读函数零副作用，不入存储。 */
function pairedQuestion(i: number): string {
  const msgs = state.msgs;
  for (let k = i - 1; k >= 0; k--) {
    const m = msgs[k];
    if (m && m.role === 'user' && !m.error) return String(m.content || '');
  }
  return '';
}

/* ============ 批B：重新生成（BotMessage act-regen 回抛）；二期批A 改替换语义 ============
   仅末条 assistant 可达（组件侧 disabled+此处双保险）：确认无流式后删除
   末条 user+assistant 问答对，把原问题回填 inputText 重走 send({regen:true})
   ——本地同批B（等价于用户原文重发）；二期批A 起新增 regen 标记让服务端在
   写本轮前删旧轮（案①服务端替换——批B 时代服务端库照旧追加，切回会话旧
   答重现；现两端语义对齐，历史真干净）。 */
function onRegen(): void {
  if (state.streaming) return;
  const msgs = state.msgs;
  let ai = -1;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant') { ai = i; break; }
  }
  if (ai < 0 || ai !== msgs.length - 1) return;      // 非末条 assistant：不可达防御
  if (ai === 0 || msgs[ai - 1].role !== 'user') return; // 无配对 user 问：不猜
  const q = String(msgs[ai - 1].content || '');
  if (!q.trim()) return;
  msgs.splice(ai - 1, 2); // 删问答对（send 会以原文重建 user 气泡，避免重复提问）
  state.inputText = q;
  send({ regen: true });
}

/* ============ 恢复历史与登录态（监听已随模板绑定就绪；逐项兜底） ============ */
let restored: any = [];
try { restored = JSON.parse(lsGet(KEY_MSGS) || '[]'); } catch { restored = []; }
if (!Array.isArray(restored)) restored = [];
state.msgs = restored.filter(function (m: any) { return m && typeof m.content === 'string' && m.content; });
state.msgs.forEach(function (m: any) { delete m.pending; }); // 清除断流/断电遗留的 pending 标记
setAuthed(lsGet(KEY_AUTH) === '1');

/* ============ 二期批次B（2026-10-03）：旧记录导入询问（纯本地检测+询问式） ============
   检测四条件（判据 §二，零网络依赖、lsGet 自带 SecurityError 兜底）：①qabot_msgs
   可解析且合法消息（role∈{user,assistant} 且 content 非空 string）≥1（不要求
   配对完整——legacy 断流孤条照单保真）；②标记键 qabot_import_done 不在位（任何
   非空值=declined/imported 均不弹）；③legacy 判别：qabot_conv 不在位且消息集
   无 usage/followups（两者均为 Vue 时代信号——Vue 任意一轮成功问答都会写
   qabot_conv，usage/followups 是 Vue 白名单才写、static 从不写的字段）；④弹窗
   门=convLoad 落 ready（401 匿名 ready 态照弹，登录后可导；off/error 不弹）。
   与批A 恢复链互不阻塞：条幅只等 convLoad 布尔态，不挂恢复链完成。 */
const importBarClosed = ref(false); // 条幅终态（成功/拒绝/404 收起）
const importBusy = ref(false);      // 两钮 loading 锁（防重复点击）
const importErr = ref(false);       // 429/400/网络错：条幅保留+提示可重试
let legacyCandidate = false;
(function detectLegacyMsgs(): void {
  try {
    if (lsGet(KEY_IMPORT_DONE)) return; // 条件②：标记键在位不再弹
    if (lsGet(KEY_CONV)) return;        // 条件③a：qabot_conv 在位=Vue 时代数据
    let arr: any;
    try { arr = JSON.parse(lsGet(KEY_MSGS) || ''); } catch { arr = null; }
    if (!Array.isArray(arr)) return;
    let legal = 0;
    for (let i = 0; i < arr.length; i++) {
      const m = arr[i];
      if (!m || typeof m !== 'object') continue;
      if (m.usage !== undefined || m.followups !== undefined) return; // 条件③b：Vue 信号
      if ((m.role === 'user' || m.role === 'assistant') &&
          typeof m.content === 'string' && m.content) legal++;
    }
    if (legal < 1) return;              // 条件①：合法消息 ≥1
    legacyCandidate = true;
  } catch { /* 受限 webview 等异常面：不弹 */ }
})();
const importBarVisible = computed<boolean>(function () {
  return legacyCandidate && !importBarClosed.value && state.convLoad === 'ready';
});
function onImportNo(): void {
  if (importBusy.value) return;
  lsSet(KEY_IMPORT_DONE, 'declined'); // 拒绝：刷新后永不再弹；qabot_msgs 原件一字不动
  importBarClosed.value = true;
}
/* 确认导入：两钮置 loading→（首动作）qabot_msgs 原文一字不改快照写
   KEY_LEGACY_SNAPSHOT（Vue 正常流永不写此键=不被 save() 覆写，"导错可重来"
   的回退位真形态）→三键白名单重建载荷（role/content/sources；user 条 sources
   丢弃、transient/富显示字段一律不上船）+尾部 200 条截断+单条 16000 截断→
   POST import。结果四态：成功=标记 imported+条幅隐+loadConvs+跳转新会话
   （onConvClick 同款）；401=askCode 条幅保留不落标记（登录成功回调既有
   loadConvs，条幅仍在可再点，不挂自动续导）；404=条幅收起不落标记；
   429/400/网络错=条幅保留+提示可重试不落标记。导入流程自身不写不删
   qabot_msgs。 */
function onImportYes(): void {
  if (importBusy.value) return;
  importBusy.value = true;
  importErr.value = false;
  const raw = lsGet(KEY_MSGS);
  if (raw !== null) lsSet(KEY_LEGACY_SNAPSHOT, raw); // 一次性快照（原文存档）
  let arr: any;
  try { arr = JSON.parse(raw || ''); } catch { arr = null; }
  if (!Array.isArray(arr)) arr = [];
  const payload: { role: string; content: string; sources?: unknown[] }[] = [];
  for (let i = 0; i < arr.length; i++) {
    const m = arr[i];
    if (!m || typeof m !== 'object') continue;
    if (m.role !== 'user' && m.role !== 'assistant') continue; // 白名单外整条丢弃
    if (typeof m.content !== 'string' || !m.content) continue;  // 同恢复 filter 口径
    const o: { role: string; content: string; sources?: unknown[] } = {
      role: m.role,
      content: m.content.length > 16000 ? m.content.slice(0, 16000) : m.content,
    };
    if (m.role === 'assistant' && Array.isArray(m.sources)) {
      // 仅 array-of-object 形态收（判据 §一.2）：非对象项剔除，剔后为空则整组不上船
      const ss = m.sources.filter(function (s: any) { return s && typeof s === 'object'; });
      if (ss.length) o.sources = ss;
    }
    payload.push(o);
  }
  const clipped = payload.length > 200 ? payload.slice(payload.length - 200) : payload; // 尾部取向
  fetch('/api/conversations/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: clipped })
  })
    .then(function (r) {
      return r.json().then(function (j: any) { return { ok: r.ok, status: r.status, j: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, j: null as any }; });
    })
    .then(function (res) {
      if (res.ok && res.j && res.j.ok) {
        lsSet(KEY_IMPORT_DONE, 'imported');
        importBarClosed.value = true;
        const nid = (typeof res.j.id === 'number' && isFinite(res.j.id) && res.j.id >= 1)
          ? res.j.id : null;
        loadConvs(); // 列表刷新（导入毕即最新）
        if (nid !== null) jumpImportedConv(nid, 25); // 跳转进导入会话
      } else if (res.status === 401) {
        askCode('请重新登录'); // 条幅保留、不落标记；用户再点导入即成
      } else if (res.status === 404) {
        importBarClosed.value = true; // 功能关：条幅收起不落标记
      } else {
        importErr.value = true; // 429/400：条幅保留+提示可重试
      }
    })
    .catch(function () { importErr.value = true; }) // 网络错：条幅保留+提示可重试
    .then(function () { importBusy.value = false; });
}
/* 跳转进导入会话：loadConvs 异步就绪后从列表行取该会话走 onConvClick（拉
   messages 渲染+侧栏 active——"导入的东西去哪了"由直接落位消除）。轮询等
   列表行出现（~2.5s 上限），未出现则留在当前面（列表刷新后仍可见可点）。 */
function jumpImportedConv(nid: number, tries: number): void {
  const hit = state.convs.find(function (c) { return c.id === nid; });
  if (hit) { onConvClick(hit); return; }
  if (tries > 0) setTimeout(function () { jumpImportedConv(nid, tries - 1); }, 100);
}

/* ============ 挂载：jump 自适应、?code= 流、健康检查、data-ready ============ */
let footRo: ResizeObserver | null = null;
onMounted(function () {
  if (state.stick && state.msgs.length) scrollBottom(); // 旧版首帧 render() 的贴底（方向1 T-b：+msgs 守卫——空态 hero 溢出时贴底会把刊头卷出首屏，3.0 hero 不溢出故原为无害 no-op，语义不变）
  /* 债务修复 b）：回底浮钮随页脚实际高度自适应（内联 var 覆盖基建 CSS 两档默认） */
  const f = footerRef.value;
  if (f && typeof ResizeObserver !== 'undefined') {
    const upd = function () {
      document.documentElement.style.setProperty('--jump-b', f.offsetHeight + 9 + 'px');
    };
    try {
      footRo = new ResizeObserver(upd);
      footRo.observe(f);
      upd();
    } catch {}
  }
  let urlCode: string | null = null;
  try { urlCode = new URLSearchParams(location.search).get('code'); } catch {}
  if (urlCode) {
    // ?code= 兼容：立即 POST /api/login 换 cookie；成功后清 URL 参数（防进
    // 浏览器历史/服务端访问日志），qabot_code 明文键登录成功即删
    try { history.replaceState(null, '', location.pathname); } catch {}
    attemptLogin(urlCode);
  } else {
    const legacyCode = lsGet(KEY_CODE); // 旧版存量明文口令：自动换 cookie 后即删（无感升级）
    if (legacyCode) attemptLogin(legacyCode);
  }
  checkHealth();
  loadConvs(); // 末轮集成：首屏拉会话列表（未登录 401 按空列表，登录后重拉）
  document.body.setAttribute('data-ready', '1'); // DOM 快照据此判断脚本初始化是否成功
  document.addEventListener('keydown', onGlobalKey); // 批次A2 抽屉 Esc 收起→末轮集成全局快捷键
});
onBeforeUnmount(function () {
  if (footRo) { try { footRo.disconnect(); } catch {} footRo = null; }
  if (touchMq) { try { touchMq.removeEventListener('change', syncTouchPh); } catch {} }
  if (desktopMq) { try { desktopMq.removeEventListener('change', syncDesktop); } catch {} } // 5.0 反馈批2
  document.removeEventListener('keydown', onGlobalKey);
});
</script>

<template>
  <div class="shell" :class="{ 'rail-collapsed': state.railCollapsed }">
    <aside class="rail" :class="{ open: drawerOpen }" aria-label="会话列表">
      <div class="rail-head"><span class="rail-title">会话</span><button class="rail-new" id="railNewBtn" type="button" :disabled="state.convSwitching" @click="onNewConv">新会话</button></div>
      <div v-if="state.convLoad === 'ready'" class="rail-search-row"><input class="rail-search" type="text" v-model="railQ" placeholder="搜索会话" aria-label="搜索会话"></div>
      <div class="rail-body" :class="{ lock: state.convSwitching }">
        <div v-if="state.convLoad === 'loading'" class="rail-empty">加载中…</div>
        <div v-else-if="state.convLoad === 'error'" class="rail-empty rail-retry" role="button" tabindex="0" @click="loadConvs" @keydown.enter="loadConvs">加载失败，点击重试</div>
        <div v-else-if="state.convLoad === 'off'" class="rail-empty">会话功能未启用</div>
        <div v-else-if="!state.convs.length" class="rail-empty">暂无历史会话</div>
        <div v-else-if="!filteredConvs.length" class="rail-empty">无匹配会话</div>
        <template v-else><div v-for="c in filteredConvs" :key="c.id" class="rail-item" :class="{ active: c.id === state.currentConvId }" @click="onConvClick(c)"><input v-if="renId === c.id" class="rail-item-input" type="text" v-model="renVal" :disabled="renBusy" @click.stop @blur="onRenSubmit" @keydown="onRenKey"><template v-else><span class="rail-item-main"><span class="rail-item-title">{{ c.title }}</span><span v-if="relTime(c.updated_at)" class="rail-item-time">{{ relTime(c.updated_at) }}</span></span><button class="rail-item-ren" type="button" aria-label="重命名会话" :disabled="state.convSwitching || renBusy" @click.stop="onConvRename(c)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button></template><button class="rail-item-del" type="button" aria-label="删除会话" :disabled="state.convSwitching || renId === c.id" @click.stop="onConvDelete(c)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div></template>
      </div>
    </aside>
    <div class="rail-mask" v-show="drawerOpen" @click="drawerOpen = false"></div>
    <div class="shell-body">
      <header>
        <button class="railbtn" id="railBtn" type="button" aria-label="会话列表" :aria-expanded="railExpanded" @click="onRailBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button>
        <span class="dot" id="statusDot" :data-state="state.dotState" :title="dotTitle || undefined"></span>
        <span class="name" id="botName">{{ state.botLabel }}</span>
        <button class="iconbtn" id="themeBtn" type="button" aria-label="切换深浅主题" @click="onTheme"><svg class="ico-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg><svg class="ico-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg></button>
        <button class="clear" id="clearBtn" type="button" aria-label="清空对话" @click="onClear"><svg class="clear-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg><span class="clear-txt">清空对话</span></button>
      </header>
      <main id="main" ref="mainRef" @scroll="onScroll" @click="onMainClick"><div v-if="importBarVisible" class="import-bar" id="importBar" role="status"><div class="import-bar-main"><span class="import-bar-txt">检测到本地旧记录，导入吗？</span><span v-if="importErr" class="import-bar-err">导入未成功，请稍后重试</span></div><div class="import-bar-btns"><button class="import-btn pri" id="importYes" type="button" :disabled="importBusy" @click="onImportYes">{{ importBusy ? '导入中…' : '导入' }}</button><button class="import-btn" id="importNo" type="button" :disabled="importBusy" @click="onImportNo">暂不导入</button></div></div><div class="thread" id="thread" :class="{ empty: !state.msgs.length }"><template v-if="!state.msgs.length"><div class="hero"><div class="hero-title">你好，这里是 qa-bot——无线网络优化工程师的问答机，有什么想问的尽管说。</div><div class="hero-chips"><button class="hero-chip" type="button"><span class="hero-chip-txt">这份规范适用于哪些场景？</span></button><button class="hero-chip" type="button"><span class="hero-chip-txt">主要条款有什么要求？</span></button><button class="hero-chip" type="button"><span class="hero-chip-txt">和上一版相比有什么变化？</span></button><button class="hero-chip" type="button"><span class="hero-chip-txt">BFR 和 DAPS 切换同时激活时，RRC 层怎么仲裁？</span></button><button class="hero-chip" type="button"><span class="hero-chip-txt">BFR 失败后的回退流程是什么？</span></button></div></div></template><template v-else><template v-for="(m, i) in state.msgs" :key="i"><div v-if="m.role === 'user'" class="msg user">{{ m.content }}</div><BotMessage v-else :msg="m" :bot-label="state.botLabel" :live="state.streaming && i === state.msgs.length - 1" :last="i === state.msgs.length - 1" :question="pairedQuestion(i)" @regen="onRegen"></BotMessage></template></template></div></main>
      <footer ref="footerRef">
        <div class="codebar" id="codebar" :class="{ show: state.codeShow }">
          <input id="codeInput" type="text" v-model="codeVal" :placeholder="state.codePh" autocomplete="off" :style="state.codeErr ? 'border-color: var(--err)' : null" @keydown="onCodeKey">
          <button id="codeBtn" type="button" @click="onCodeBtn">确定</button>
        </div>
        <div class="row">
          <textarea id="input" ref="inputRef" rows="1" v-model="state.inputText" :placeholder="state.inputPh" @input="grow" @keydown="onInputKey"></textarea>
          <button class="send" id="sendBtn" type="button" :class="{ stop: state.streaming }" @click="onSendBtn">{{ state.streaming ? '停止' : '发送' }}</button>
        </div>
        <div class="disclaimer">内容由 AI 生成，请注意甄别与核实重要信息</div>
        <div class="disclaimer coverage">已收录：规范类语料（demo 库：企业运维规范 51 块；生产库约 8.3 万块，版权约束不入公开仓）</div>
        <!-- 公开版：备案脚注按发布形态移除 -->
      </footer>
    </div>
  </div>
  <button class="jump" id="jumpBtn" type="button" :class="{ show: showJump }" aria-label="回到底部" @click="onJump"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7"/></svg></button>
  <div class="sr-only" role="status" aria-live="polite">{{ state.announce }}</div>
</template>
