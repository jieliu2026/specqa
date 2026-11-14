import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin } from 'vite'

/* ============ 批次A2（2026-10-03 视觉 2.0）：KaTeX 字体裁剪 ============
   katex.min.css 每个 @font-face 带 woff2/woff/ttf 三源，vite 默认三类全收进
   dist（~59 件 ≈1MB 死重复）。现代浏览器（Chrome/Edge/Safari/Firefox 近年
   版本）全支持 woff2，构建期把 woff/ttf 的 url() 段剥除，只留 woff2 源——
   自写 transform 钩子，零新依赖。 */
function katexWoff2Only(): Plugin {
  return {
    name: 'katex-woff2-only',
    enforce: 'pre', // 必须先于 vite 内建 css 管线（url() 被替换为 __VITE_ASSET__ 占位符前）
    transform(code, id) {
      if (!/katex[^/]*\.css$/.test(id)) return null
      const stripped = code
        .replace(/,\s*url\([^)]*\.woff\)\s*format\("woff"\)/g, '')
        .replace(/,\s*url\([^)]*\.ttf\)\s*format\("(?:truetype|opentype)"\)/g, '')
      return stripped === code ? null : { code: stripped, map: null }
    },
  }
}

// https://vite.dev/config/
/* ============ 视觉 5.0 T-a（2026-10-04）：display 子集字盘守护插件整体移除
   （衬线字体管线退役=ADR-0017 决策③；字盘常量表/子集 woff2/字盘单源校验
   同批清理，其专属 node:child_process / node:fs / node:url import 一并移除；
   katexWoff2Only 保留不动） ============ */
export default defineConfig({
  base: '/',
  plugins: [vue(), katexWoff2Only()],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
})
