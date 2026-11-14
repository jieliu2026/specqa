/* ============ 批C（2026-10-03）：手写 ASN.1 mini 着色器（3GPP 主场景，零依赖） ============
   不引 highlight.js：纯手写 tokenizer，只服务围栏语言标签 asn1/asn（其余语言
   不着色、无标签不猜——0 误染）。token 面：关键字（含 3GPP 行文 informational/
   mandatory 与类型 INTEGER/SEQUENCE 等）、字符串 "..."（"" 转义）、注释 -- 至
   行尾、数字、PDU 名（词后紧跟 ::= 的赋值左元）。
   安全纪律：所有 token 内容一律 esc() 后再拼进 span；类名为静态白名单
   （.hl-kw/.hl-str/.hl-cm/.hl-num/.hl-pdu），无任何动态属性 → 零注入面。
   esc 与 markdown.ts 同式（本件独立复制一份，避免与 markdown.ts 循环 import）。 */

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const KEYWORDS: ReadonlySet<string> = new Set([
  /* ASN.1 结构关键字（3GPP 语料常用面，大小写不敏感匹配——规范里全大写书写） */
  'begin', 'end', 'definitions', 'imports', 'exports', 'from', 'extension',
  'sequence', 'set', 'of', 'choice', 'optional', 'default', 'size', 'max', 'min',
  'integer', 'boolean', 'octet', 'string', 'bit', 'enumerated', 'null',
  'true', 'false', 'present', 'absent', 'with', 'components', 'component',
  'by', 'class', 'unique', 'printablestring', 'restricted', 'to',
  /* 3GPP 规范行文关键字（任务点名） */
  'informational', 'mandatory',
]);

function span(cls: string, t: string): string {
  return '<span class="' + cls + '">' + esc(t) + '</span>';
}

function isDigit(c: string): boolean { return c >= '0' && c <= '9'; }
function isAlpha(c: string): boolean {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}
function isWordChar(c: string): boolean { return isAlpha(c) || isDigit(c); }

export function highlightAsn1(code: string): string {
  const src = String(code);
  const n = src.length;
  let out = '';
  let i = 0;
  while (i < n) {
    const c = src[i];
    if (c === '-' && src[i + 1] === '-') { // 注释：至行尾（流式半态=到文本末尾，闭合行到达后重渲染自然截齐）
      const nl = src.indexOf('\n', i);
      const end = nl === -1 ? n : nl;
      out += span('hl-cm', src.slice(i, end));
      i = end;
      continue;
    }
    if (c === '"') { // 字符串（"" 转义；未闭合半态着到末尾，配对后重渲染截齐）
      let j = i + 1;
      let closed = false;
      while (j < n) {
        if (src[j] === '"') {
          if (src[j + 1] === '"') { j += 2; continue; }
          j++; closed = true; break;
        }
        j++;
      }
      const end = closed ? j : n;
      out += span('hl-str', src.slice(i, end));
      i = end;
      continue;
    }
    if (c === ':' && src.startsWith('::=', i)) { // 赋值算子
      out += span('hl-kw', '::=');
      i += 3;
      continue;
    }
    if (isDigit(c)) { // 数字（ASN.1 值域 SIZE (24..)/(0..255) 等的点号留给原文）
      let j = i;
      while (j < n && isDigit(src[j])) j++;
      if (src[j] === '.' && isDigit(src[j + 1] || '')) {
        j++;
        while (j < n && isDigit(src[j])) j++;
      }
      out += span('hl-num', src.slice(i, j));
      i = j;
      continue;
    }
    if (isAlpha(c)) { // 词（ASN.1 标识符允许中缀连字符：BCCH-BCH-Message/nonCriticalExtension）
      let j = i + 1;
      while (j < n) {
        if (isWordChar(src[j])) { j++; continue; }
        if (src[j] === '-' && isWordChar(src[j + 1] || '')) { j += 2; continue; }
        break;
      }
      const w = src.slice(i, j);
      let k = j;
      while (k < n && (src[k] === ' ' || src[k] === '\t')) k++;
      const cls = src.startsWith('::=', k)
        ? 'hl-pdu' // PDU 名：赋值左元
        : (KEYWORDS.has(w.toLowerCase()) ? 'hl-kw' : '');
      out += cls ? span(cls, w) : esc(w);
      i = j;
      continue;
    }
    out += esc(c); // 结构符/空白原样
    i++;
  }
  return out;
}
