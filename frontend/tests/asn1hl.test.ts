/* E3③ 转正迁移件（2026-10-08）：自 运营/测试体系-20261007/E3试点/vitest/tests/asn1hl.test.ts
   迁入 frontend/tests/（配置迁 frontend 根后 import 路径改 ../src/…，用例主体逐字保持）。
   用例组②：lib/asn1hl.ts ASN.1 手写着色器纯逻辑（2 条）。
   token 面：关键字（大小写不敏感）/字符串（""转义）/注释 --至行尾/数字/PDU 名（::= 左元）。 */

import { describe, expect, test } from 'vitest';
import { highlightAsn1 } from '../src/lib/asn1hl';

describe('asn1hl.ts 纯逻辑（E3 试点）', () => {

  test('⑥ highlightAsn1() 四类 token + PDU 名着色（3GPP 主场景）', () => {
    const out = highlightAsn1([
      '-- 3GPP 注释行',
      'BCCH-BCH-Message ::= SEQUENCE {',
      '  messageClass ENUMERATED {mandatory, informational},',
      '  payload SIZE (24..1736) OPTIONAL,',
      '  note "say ""quoted"" inside"',
      '}',
    ].join('\n'));
    // 注释至行尾
    expect(out).toContain('hl-cm">-- 3GPP 注释行');
    // PDU 名=赋值左元（词后紧跟 ::=），连字符标识符整词识别
    expect(out).toContain('hl-pdu">BCCH-BCH-Message');
    expect(out).toContain('hl-kw">::=');
    // 结构关键字大小写不敏感匹配
    expect(out).toContain('hl-kw">SEQUENCE');
    expect(out).toContain('hl-kw">ENUMERATED');
    expect(out).toContain('hl-kw">OPTIONAL');
    // 3GPP 行文关键字
    expect(out).toContain('hl-kw">mandatory');
    expect(out).toContain('hl-kw">informational');
    // 数字（含值域 24..1736）
    expect(out).toContain('hl-num">24');
    expect(out).toContain('hl-num">1736');
    // 字符串（"" 转义整段闭合）
    expect(out).toContain('hl-str">"say ""quoted"" inside"');
    // 非关键字普通词不着色（无 span 包裹）
    expect(out).not.toContain('hl-kw">messageClass');
    expect(out).not.toContain('hl-pdu">payload');
  });

  test('⑦ 注入面：token 内容一律 esc，无裸 <script>/<img>，& 不双重转义', () => {
    const out = highlightAsn1('<script>x</script> & "a<b>" -- 注 <i>释');
    expect(out).not.toMatch(/<(script|img|i)\b/);
    expect(out).toContain('&lt;script&gt;');
    expect(out).toContain('&amp;');            // & 转义
    expect(out).not.toContain('&amp;lt;');     // 不双重转义（先 & 后 < 的次序）
  });
});
