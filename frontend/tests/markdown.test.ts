/* E3③ 转正迁移件（2026-10-08）：自 运营/测试体系-20261007/E3试点/vitest/tests/markdown.test.ts
   迁入 frontend/tests/（配置迁 frontend 根后 import 路径改 ../src/…，用例主体逐字保持）。
   用例组①：lib/markdown.ts 安全渲染纯逻辑（5 条）。
   行为真源=批0 自 static/index.html 的逐逻辑移植 + 批C 公式管线；
   断言面锁定：转义次序、行内码保护、链接白名单、注入面归零、结构映射、公式抽取。 */

import { describe, expect, test } from 'vitest';
import { esc, inline, mdToHtml } from '../src/lib/markdown';

describe('markdown.ts 纯逻辑（E3 试点）', () => {

  test('① esc() 转义与次序：& 先于 < >（防 &amp;lt; 双重转义/逃逸）', () => {
    expect(esc('a<b>&c')).toBe('a&lt;b&gt;&amp;c');
    expect(esc('&<>"\'')).toBe('&amp;&lt;&gt;"\''); // 引号不转（文本位安全由白名单结构兜底）
    expect(esc('<script>alert(1)</script>')).toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
  });

  test('② inline()：行内码段保护 + 链接白名单（仅 http(s)、引号百分号编码）', () => {
    // 行内码内的 markdown 标记不再加工（占位符护住，还原后完整保留）
    expect(inline('`**x**` 等')).toContain('<code>**x**</code>');
    // 加粗/斜体（前导非 * 非词字符边界）
    expect(inline('**粗**和*斜*')).toContain('<strong>粗</strong>');
    expect(inline('前文 *斜体* 尾')).toContain('<em>斜体</em>');
    // 链接白名单：http(s) 放行 + target=_blank + rel 双保险
    expect(inline('[文本](https://example.com/a?b=1)'))
      .toContain('<a href="https://example.com/a?b=1" target="_blank" rel="noopener noreferrer">文本</a>');
    // javascript: 伪协议不转链（原文落回，无 <a>）
    expect(inline('[点我](javascript:alert(1))')).not.toContain('<a ');
    // url 内双引号转 %22 防属性逃逸
    expect(inline('[x](https://e.com/?"onmouseover="evil)')).not.toContain('"onmouseover=');
  });

  test('③ mdToHtml() 注入面：标签全转义、无裸 <script>/<img>/<iframe>/<b 事件属性>', () => {
    const h = mdToHtml('<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n<iframe src=//evil></iframe>');
    expect(h).not.toMatch(/<(script|img|iframe)\b/);
    expect(h).toContain('&lt;script&gt;');
    expect(h).toContain('&lt;img src=x onerror=alert(2)&gt;');
    // 事件属性即使藏在结构块内也不得存活
    expect(mdToHtml('> 引用 <b onmouseover=alert(3)>x</b>')).not.toContain('<b ');
  });

  test('④ mdToHtml() 结构映射：标题降级/有序无序列表/GFM 表格/引用/hr/段落', () => {
    expect(mdToHtml('# 大标题')).toContain('<h2>大标题</h2>');   // # → h2 降一级
    expect(mdToHtml('#### 四级')).toContain('<h5>四级</h5>');   // 上限 h5
    expect(mdToHtml('- 甲\n- 乙')).toContain('<ul><li>甲</li><li>乙</li></ul>');
    expect(mdToHtml('1. 甲\n2. 乙')).toContain('<ol><li>甲</li><li>乙</li></ol>');
    expect(mdToHtml('（一）、中文序号')).not.toContain('<ol>');  // 中文序号非 \d+ 不开列表
    const t = mdToHtml('| A | B |\n|---|---|\n| 1 | 2 |');
    expect(t).toContain('<div class="tablewrap"><table>');
    expect(t).toContain('<th>A</th><th>B</th>');
    expect(t).toContain('<td>1</td><td>2</td>');
    expect(mdToHtml('> 引用行')).toContain('<blockquote>引用行</blockquote>');
    expect(mdToHtml('---')).toContain('<hr>');
    expect(mdToHtml('第一行\n第二行')).toContain('<p>第一行<br>第二行</p>');
  });

  test('⑤ 公式管线：\\(..\\)/$$..$$ 成式、单 $ 不开、围栏内不抽、未闭合原样', () => {
    const inlineF = mdToHtml('质能 \\(E=mc^2\\) 方程');
    expect(inlineF).toContain('katex');                 // KaTeX 渲染产物落地
    expect(inlineF).toContain('katex-html');            // output:'htmlAndMathml' 的 html 层
    expect(inlineF).not.toContain('\\(');               // 定界符不残留

    const dispF = mdToHtml('$$\\int_0^1 x\\,dx$$');
    expect(dispF).toContain('katex-display');           // $$..$$ 块级 displayMode
    expect(dispF).not.toContain('$$');

    expect(mdToHtml('价格 $5 和 $6 之间')).not.toContain('katex');  // 单 $ 不开（定案）
    const fenced = mdToHtml('```text\n$$x$$\n```');
    expect(fenced).not.toContain('katex');              // 围栏内容直出不抽公式
    expect(fenced).toContain('$$x$$');                  // 定界符按原文存活
    expect(fenced).toContain('<div class="codeblock">');

    const half = mdToHtml('流式半态 \\(E=');             // 未闭合：原文落下不渲染
    expect(half).toContain('\\(E=');
    expect(half).not.toContain('katex');
  });
});
