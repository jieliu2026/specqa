/* E3③ 转正迁移件（2026-10-08）：自 运营/测试体系-20261007/E3试点/vitest/tests/BotMessage.ssr.test.ts
   迁入 frontend/tests/（配置迁 frontend 根后 import 路径改 ../src/…，用例主体逐字保持）。
   用例组④：components/BotMessage.vue 组件冒烟（SSR 渲染，2 条）。
   选 SSR 而非 DOM 挂载的原因：@vue/server-renderer 随 vue 包自带（零额外装包）；
   冒烟面=渲染分支正确性，交互面（hover 卡/复制/Esc）仍归 Playwright DOM 契约件管——分工见试点报告。 */

import { describe, expect, test } from 'vitest';
import { createSSRApp, h } from 'vue';
import { renderToString } from 'vue/server-renderer';
import BotMessage from '../src/components/BotMessage.vue';
import { INSUFF_FALLBACK, OFFTOPIC_TEXT } from '../src/lib/constants';
import type { Msg } from '../src/types';

async function render(msg: Msg, extra: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(BotMessage, { msg, botLabel: '网优工程师的qa-bot', ...extra }),
  });
  return renderToString(app);
}

describe('BotMessage.vue SSR 冒烟（E3 试点）', () => {

  test('⑨ 正常消息全要素：md 正文/出处条配对/CC 徽标/程序闸/用量徽标/时间', async () => {
    const ts = 1759900000000; // 固定时刻；期望值用同一 Date API 计算（免时区 flake）
    const d = new Date(ts);
    const p2 = (n: number) => (n < 10 ? '0' : '') + n;
    const html = await render({
      role: 'assistant',
      content: '**结论**：见 [TS 38.331](https://www.3gpp.org/)',
      sources: [{
        doc_id: 'TS 38.331', version: 'v17.2.0', locator: '§6.2.2',
        score: 0.87, quote: 'BCCH-BCH-Message ::= SEQUENCE',
      }],
      cc: { overall: 'grounded', per_source: [{ doc_id: 'TS 38.331', verdict: 'supports' }] },
      cgate: { ok: true, hard: 0 },
      usage: 1334,
      ts,
    }, { last: true });

    expect(html).toContain('class="msg bot"');                      // 非 err 态
    expect(html).toContain('网优工程师的qa-bot');                    // 角色标签
    expect(html).toContain('<strong>结论</strong>');                // md 正文经 v-html
    expect(html).toContain('target="_blank" rel="noopener noreferrer"');
    expect(html).toContain('[1] TS 38.331 v17.2.0 §6.2.2');         // 出处 chip 文本
    expect(html).toContain('支持');                                  // 逐源 verdict 徽标
    expect(html).toContain('引文有据');                              // overall 总标 chip
    expect(html).toContain('引用核验✓');                             // 程序闸 ok
    expect(html).toContain('1.3k tok');                             // usage 1334 → 1.3k
    expect(html).toContain(p2(d.getHours()) + ':' + p2(d.getMinutes())); // 完成时刻 HH:MM
    expect(html).toContain('act-copy');                              // 操作条四件
    expect(html).toContain('act-regen');
    expect(html).not.toContain('disabled');                          // 末条+非流式 → regen 可用
    expect(html).not.toContain('srcs-x');                            // 1 源 ≤ SRC_MAXSHOW → 无 +N 折叠钮
    expect(html).not.toContain('pv-card');                           // SSR 初始态无预览卡
    expect(html).not.toContain(OFFTOPIC_TEXT);                       // 无提示条
  });

  test('⑩ 分支态：error 纯文本不经 md、offTopic/evInsufficient 提示条与兜底文案', async () => {
    const errHtml = await render({ role: 'assistant', content: '<b>服务暂不可用</b>', error: true });
    expect(errHtml).toContain('class="msg bot err"');
    expect(errHtml).toContain('&lt;b&gt;服务暂不可用&lt;/b&gt;');     // 纯文本插值（Vue 转义）
    expect(errHtml).not.toContain('<p>');                            // 不走 mdToHtml
    expect(errHtml).not.toContain('网优工程师的qa-bot');              // err 态无角色标签
    expect(errHtml).not.toContain(' tok');                           // 无用量徽标

    const offHtml = await render({ role: 'assistant', content: '通用回答', offTopic: true });
    expect(offHtml).toContain(OFFTOPIC_TEXT);
    expect(offHtml).not.toContain('class="msg bot err"');

    const evHtml = await render({ role: 'assistant', content: '尝试回答', evInsufficient: true, evReason: '低分' });
    expect(evHtml).toContain('语料可能不足：低分');

    const evFb = await render({ role: 'assistant', content: '尝试回答', evInsufficient: true });
    expect(evFb).toContain('语料可能不足：' + INSUFF_FALLBACK);      // reason 缺失走兜底文案
  });

  test('⑪ 意图缺口批甲：insightGap 通识标注行（复用 offtopic 提示位+gap 修饰类）', async () => {
    // note 全文自服务端，{{ }} 插值转义（对抗载荷文本化）
    const gapHtml = await render({
      role: 'assistant', content: '尝试给通用框架',
      insightGap: '以下为通用优化思路，非本库出处内容；<img src=x onerror=alert(29)>',
    });
    expect(gapHtml).toContain('class="offtopic gap"');
    expect(gapHtml).toContain('以下为通用优化思路，非本库出处内容；');
    expect(gapHtml).toContain('&lt;img src=x onerror=alert(29)&gt;');  // Vue 转义文本形态
    expect(gapHtml).not.toContain('<img src=x');                      // 未成元素
    expect(gapHtml).not.toContain('语料可能不足');                     // 不误染 ev 前缀（无前端拼装）

    // 空串不渲染（note 缺失=不落地，无兜底文案）；err 态抑制标注行
    const noGap = await render({ role: 'assistant', content: 'x', insightGap: '' });
    expect(noGap).not.toContain('offtopic gap');
    const errGap = await render({ role: 'assistant', content: 'x', error: true, insightGap: '标注' });
    expect(errGap).not.toContain('offtopic gap');
  });

  test('⑫ 话术批（2026-10-16）：off_topic 渠道引导行（otNote 复用提示位+note 修饰类）', async () => {
    // note 全文自服务端，{{ }} 插值转义（对抗载荷文本化）；基础行随行挂 withnote（整块单虚线收末行）
    const noteHtml = await render({
      role: 'assistant', content: '通用回答', offTopic: true,
      otNote: '卫星通信（NTN）内容暂未收录，可参考 3GPP NTN 系列规范（TS 38.300 等）<img src=x onerror=alert(31)>',
    });
    expect(noteHtml).toContain(OFFTOPIC_TEXT);                          // 基础行仍在（note 是追加不是替换）
    // Vue SSR 静态+动态 class 合并按字母序输出（withnote offtopic），断言用
    // 顺序无关正则（2026-10-16 首跑红灯修正，不绑 class 串实现序）
    expect(noteHtml).toMatch(/class="[^"]*\bwithnote\b[^"]*"/);
    expect(noteHtml).toContain('class="offtopic note"');
    expect(noteHtml).toContain('卫星通信（NTN）内容暂未收录');
    expect(noteHtml).toContain('&lt;img src=x onerror=alert(31)&gt;');  // Vue 转义文本形态
    expect(noteHtml).not.toContain('<img src=x');                       // 未成元素

    // otNote 缺席=旧单行形态（零 withnote/note 类）；err 态抑制；孤儿 otNote（无 offTopic）不渲染
    const plain = await render({ role: 'assistant', content: 'x', offTopic: true });
    expect(plain).toContain(OFFTOPIC_TEXT);
    expect(plain).not.toContain('offtopic note');
    expect(plain).not.toContain('withnote');
    const errNote = await render({ role: 'assistant', content: 'x', error: true, offTopic: true, otNote: '引导' });
    expect(errNote).not.toContain('offtopic');
    const orphan = await render({ role: 'assistant', content: 'x', otNote: '引导' });
    expect(orphan).not.toContain('offtopic');
  });

  test('⑬ 差评回流采集批（2026-10-17，决策位⑥）：act-badfb 钮渲染门与初始收起态', async () => {
    // question prop 在席（非 err、非流式）→ act-bar 尾「差评」钮在场；
    // 展开行 .badfb-row 初始收起（SSR 零交互态零 fetch）
    const qHtml = await render(
      { role: 'assistant', content: '尝试回答', ts: 1759900000000 },
      { question: '切换成功率怎么优化？' });
    expect(qHtml).toContain('act-badfb');
    expect(qHtml).toContain('>差评</button>');
    expect(qHtml).not.toContain('badfb-row');        // 初始收起：标签行不渲染
    expect(qHtml).not.toContain('badfb-tag');
    expect(qHtml).not.toContain('没答到点');

    // question 缺席（历史恢复无配对/ SSR 冒烟默认）→ 钮不渲染（服务端必填同口径）
    const noQ = await render({ role: 'assistant', content: '尝试回答' });
    expect(noQ).not.toContain('act-badfb');

    // err 态抑制（无答面可评）；空白 question=缺席同判
    const errHtml = await render(
      { role: 'assistant', content: '出错了', error: true },
      { question: 'q' });
    expect(errHtml).not.toContain('act-badfb');
    const blankQ = await render(
      { role: 'assistant', content: '尝试回答' }, { question: '   ' });
    expect(blankQ).not.toContain('act-badfb');

    // 退役断言族不回潮：E1 点赞/踩对类名仍全零（本批只有单差评点）
    for (const retired of ['fb-btn', 'fb-up', 'fb-down', 'fb-done', 'fu-bar', 'fu-chip']) {
      expect(qHtml).not.toContain(retired);
    }
  });
});
