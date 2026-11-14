/* E3③ vitest 转正配置（2026-10-08；试点=运营/测试体系-20261007/E3试点/vitest试点报告-20261008.md，
   授权=用户 2026-10-08 批准 E3 三试点正式化，拍板登记=断点三节 43 由主会话完成）。
   跑法：cd frontend && npx vitest run  （或 npm run test:unit）
   迁移注记：自 E3试点/vitest/vitest.config.mjs 迁入 frontend 根后，试点期两处绕障退化为标准写法：
   ① 裸导入 'vue' 沿 frontend/node_modules 自然解析——试点的 resolve.alias（^vue($|/) 锚定）删除；
   ② @vitejs/plugin-vue 直接标准 import——试点的 file URL 动态绝对路径加载删除。
   测试面：frontend/tests/ 下全部 *.test.ts（纯逻辑 8 条 + 组件 SSR 冒烟 2 条，node 环境无 DOM）；
   交互/浏览器面仍归 Playwright DOM 契约件（tests/test_frontend_*.py）管，两层不互踩（分工见试点报告 §六）。 */

import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',   /* 纯逻辑 + SSR 渲染冒烟（@vue/server-renderer 随 vue 自带），无需 DOM 环境 */
    watch: false,
  },
});
