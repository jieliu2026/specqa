/* 防首帧闪烁：localStorage（手动选择）> 系统偏好，首帧前把主题挂到 <html>；
   受限 webview 访问 localStorage 抛 SecurityError，统一兜底。

   C2（2026-10-07）：原 index.html 头部内联脚本外提至此（CSP script-src 去
   unsafe-inline 的前置——内联脚本与 v-html 的 XSS 面同档，Report-Only 档即
   上报）。经 vite public 原样拷贝至 dist/assets/theme-init.js：/assets 是
   server.py 与验收 mock_server 既有唯一 dist 静态服务面（dist 根零路由，
   放根即 404）。经典同步脚本（无 async/defer/module）在 <head> 原位=解析期
   阻塞执行，首帧时序与内联形态逐字节等价。 */
(function () {
  var t = null;
  try { t = localStorage.getItem('qabot_theme'); } catch (e) {}
  if (t !== 'light' && t !== 'dark') {
    t = (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }
  document.documentElement.dataset.theme = t;
  var m = document.querySelector('meta[name="theme-color"]');
  if (m) m.content = (t === 'dark') ? '#1e1e1e' : '#ffffff';
})();
