/* 视觉 3.0 T0.5（2026-10-04）：base.css 六模块拆分。import 顺序=级联保序口径：
   tokens → chrome → skeleton → message → markdown → motion，与原单文件的
   规则先后一致（同特异度覆写保持先基后覆，如 --jump-b 基础在 skeleton、
   540px 覆写在 message）；各文件内部规则仍按原 base.css 出现顺序排列。 */
import './styles/tokens.css';
/* 视觉 5.0 T-a（2026-10-04）：display 衬线层 @font-face 样式件 import 随
   衬线字体管线退役删除（ADR-0017 决策③）；其余 import 级联保序零改 */
import './styles/chrome.css';
import './styles/skeleton.css';
import './styles/message.css';
import './styles/markdown.css';
import './styles/motion.css';
/* 批C（2026-10-03）：KaTeX 自托管样式（vite 把 katex.min.css 及其 woff2 字体
   一并收进 dist/assets，同源加载零 CDN） */
import 'katex/dist/katex.min.css';

import { createApp } from 'vue';
import App from './App.vue';

createApp(App).mount('#app');
