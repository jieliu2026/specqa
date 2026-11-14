/* ============ Markdown 安全渲染（仅 AI 消息展示层；msgs[].content 永存原始文本） ============
   纪律：任何文本先 esc() 全量转义、再做白名单结构转换，杜绝注入；
   链接仅放行 http(s) 且引号转百分号编码，防属性逃逸。
   批0 移植（2026-10-03）：自 static/index.html 的 esc()/inline()/mdToHtml() 逐逻辑移植，
   正则、控制流、转义次序与原版完全一致，仅做语法现代化（const/导出/类型标注）。
   批C（2026-10-03）：+公式渲染（KaTeX 占位符模式）与 ASN.1 围栏着色（asn1hl.ts）。
   公式管线（定案见 work/公式标记形态核查-20261003.md：渲染 \(...\)/\[...\]/$$...$$
   三组，单 $ 不开）：
   ① extractMathOutsideFences 先按围栏逻辑切块——围栏行直出、非围栏段才抽公式；
   ② extractMath 只抽成对闭合段 → \u0002N\u0002 占位（与行内码 \u0001 系分立），
     未闭合（流式半态）天然不抽=原文显示，闭合后重渲染自动成式；
     行内码 `...` 段整段跳过（与 inline() 的左贪心反引号配对一致），反引号内
     定界符不抽取；
   ③ 占位符无 &<>/*[]() 字符，穿透 esc()/链接/加粗斜体转换原样存活；
   ④ inline() 末段（\u0001 还原后）把占位换 katex.renderToString 产物——
     trust:false 拒 \href 等危险命令（KaTeX 默认红色错误呈现，不吞不炸），
     output:'htmlAndMathml' 保读屏语义；tex 不经 esc()（KaTeX 内部自转义）。 */

import katex from 'katex';
import { highlightAsn1 } from './asn1hl';

export function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

interface MathSeg { tex: string; display: boolean }

function renderMath(seg: MathSeg): string {
  try {
    return katex.renderToString(seg.tex, {
      throwOnError: false, strict: false, trust: false,
      output: 'htmlAndMathml', displayMode: seg.display,
    });
  } catch {
    /* throwOnError:false 下正常不抛（防御非字符串等异常输入）：退回原文文本，不吞不炸 */
    return esc(seg.tex);
  }
}

/* 公式抽取（成对闭合才成式；跨行允许——块级 \[..\] 常独占多行） */
function extractMath(text: string, math: MathSeg[]): string {
  let out = '';
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === '`') { // 行内码段直拷：反引号内的定界符不抽（与 inline() 配对一致）
      const j = text.indexOf('`', i + 1);
      if (j === -1) { out += text.slice(i); break; }
      out += text.slice(i, j + 1);
      i = j + 1;
      continue;
    }
    let del: [string, string, boolean] | null = null; // [open, close, display]
    if (c === '\\') {
      if (text[i + 1] === '[') del = ['\\[', '\\]', true];
      else if (text[i + 1] === '(') del = ['\\(', '\\)', false];
    } else if (c === '$' && text[i + 1] === '$') {
      del = ['$$', '$$', true]; // 单 $ 不开（定案；deepseek 偶发形态留观察）
    }
    if (del) {
      const end = text.indexOf(del[1], i + 2);
      if (end !== -1) {
        math.push({ tex: text.slice(i + 2, end), display: del[2] });
        out += '\u0002' + (math.length - 1) + '\u0002';
        i = end + del[1].length;
        continue;
      }
      /* 未闭合（流式半态）：定界符按原文落下、从其后继续扫（不吞后续配对段） */
    }
    out += c;
    i++;
  }
  return out;
}

/* 围栏切块 + 非围栏段抽公式（围栏识别与 mdToHtml 主循环同款正则，两侧一致） */
function extractMathOutsideFences(src: string, math: MathSeg[]): string {
  const lines = src.split('\n');
  const out: string[] = [];
  let buf: string[] = []; // 非围栏行缓冲：连续段合并抽取，支持跨行 \[..\]
  const flush = function (): void {
    if (buf.length) { out.push(extractMath(buf.join('\n'), math)); buf = []; }
  };
  let inFence = false;
  for (let k = 0; k < lines.length; k++) {
    const line = lines[k];
    if (!inFence && /^```([\w-]*)\s*$/.test(line)) { flush(); inFence = true; out.push(line); continue; }
    if (inFence) {
      if (/^```\s*$/.test(line)) inFence = false;
      out.push(line); // 围栏内容直出：主循环 esc() 直出，公式定界符不抽不渲染
      continue;
    }
    buf.push(line);
  }
  flush();
  return out.join('\n');
}

export function inline(s: string, math?: MathSeg[]): string {
  const codes: string[] = [];
  let e = esc(s).replace(/`([^`]+)`/g, function (_m: string, c: string) {
    codes.push('<code>' + c + '</code>');
    return '\u0001' + (codes.length - 1) + '\u0001'; // 占位：护住行内码不被加粗斜体再加工
  });
  e = e.replace(/\[([^\]]+)\]\((https?:[^\s)]+)\)/g, function (_m: string, txt: string, url: string) {
    return '<a href="' + url.replace(/"/g, '%22') + '" target="_blank" rel="noopener noreferrer">' + txt + '</a>';
  });
  e = e.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  e = e.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*/g, '$1<em>$2</em>');
  e = e.replace(/\u0001(\d+)\u0001/g, function (_m: string, i: string) { return codes[+i]; });
  if (math) {
    e = e.replace(/\u0002(\d+)\u0002/g, function (m: string, i: string) {
      const seg = math[+i];
      return seg ? renderMath(seg) : m; // 非本段占位（原文混入控制字符伪形态）原样落回
    });
  }
  return e;
}

export function mdToHtml(src: string): string {
  const math: MathSeg[] = [];
  const lines = extractMathOutsideFences(String(src), math).split('\n');
  const out: string[] = [];
  let paras: string[] = [];
  let i = 0;
  function flushPara(): void {
    if (!paras.length) return;
    out.push('<p>' + paras.map(function (p: string) { return inline(p, math); }).join('<br>') + '</p>');
    paras = [];
  }
  function cellsOf(row: string): string[] {
    return row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c: string) { return c.trim(); });
  }
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```([\w-]*)\s*$/);
    if (fence) { // 围栏代码块（流式尾块未闭合时按到末尾处理）
      flushPara();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      if (i < lines.length) i++; // 跳过闭合围栏
      const lang = fence[1] || 'text';
      /* 批C：asn1/asn 标签走手写着色器；其余语言（含空标签/text/json/python/bash）
         保持现状不着色——模型不带语言标签则不猜，0 误染（范围收敛，A2 再议） */
      const body = (lang === 'asn1' || lang === 'asn')
        ? highlightAsn1(buf.join('\n'))
        : esc(buf.join('\n'));
      out.push('<div class="codeblock"><div class="cb-bar"><span class="cb-lang">'
        + esc(lang) + '</span>'
        + '<button class="cb-copy" type="button">复制</button></div>'
        + '<pre><code>' + body + '</code></pre></div>');
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { // 标题降一级映射（# → h2），不与页面级标题争位
      flushPara();
      const lv = Math.min(h[1].length + 1, 5);
      out.push('<h' + lv + '>' + inline(h[2], math) + '</h' + lv + '>');
      i++; continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flushPara(); out.push('<hr>'); i++; continue; }
    if (/^>\s?/.test(line)) { // 引用块
      flushPara();
      const q: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { q.push(lines[i].replace(/^>\s?/, '')); i++; }
      out.push('<blockquote>' + q.map(function (t: string) { return inline(t, math); }).join('<br>') + '</blockquote>');
      continue;
    }
    if (line.indexOf('|') !== -1 && i + 1 < lines.length &&
        /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1]) && lines[i + 1].indexOf('-') !== -1) { // GFM 表格
      flushPara();
      const head = cellsOf(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].indexOf('|') !== -1 && lines[i].trim() !== '') {
        rows.push(cellsOf(lines[i])); i++;
      }
      let t = '<div class="tablewrap"><table><thead><tr>';
      head.forEach(function (c: string) { t += '<th>' + inline(c, math) + '</th>'; });
      t += '</tr></thead><tbody>';
      rows.forEach(function (r: string[]) {
        t += '<tr>';
        for (let c2 = 0; c2 < head.length; c2++) t += '<td>' + inline(r[c2] || '', math) + '</td>';
        t += '</tr>';
      });
      out.push(t + '</tbody></table></div>');
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.、)]\s+(.*)$/);
    if (ul || ol) { // 列表（同类连续项归并；异类即断开）
      flushPara();
      const tag = ul ? 'ul' : 'ol';
      const re = ul ? /^\s*[-*]\s+(.*)$/ : /^\s*\d+[.、)]\s+(.*)$/;
      out.push('<' + tag + '>');
      while (i < lines.length) {
        const m2 = lines[i].match(re);
        if (!m2) break;
        out.push('<li>' + inline(m2[1], math) + '</li>');
        i++;
      }
      out.push('</' + tag + '>');
      continue;
    }
    if (line.trim() === '') { flushPara(); i++; continue; }
    paras.push(line);
    i++;
  }
  flushPara();
  return out.join('');
}
