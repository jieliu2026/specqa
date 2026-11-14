/* E3③ 转正迁移件（2026-10-08）：自 运营/测试体系-20261007/E3试点/vitest/tests/constants.test.ts
   迁入 frontend/tests/（配置迁 frontend 根后 import 路径改 ../src/…，用例主体逐字保持）。
   用例组③：lib/constants.ts 契约常量守恒（1 条）。
   这些值是 Playwright DOM 契约件（tests/test_frontend_*.py）断言文案的真源——
   前端侧手滑改文案会静默打爆回归网；此用例把照搬契约钉死在源头。 */

import { describe, expect, test } from 'vitest';
import {
  KEY_MSGS, SRC_MAXSHOW, CC_VERDICT, CC_LABEL,
  INSUFF_HEAD, INSUFF_FALLBACK, OFFTOPIC_TEXT,
} from '../src/lib/constants';

describe('constants.ts 契约守恒（E3 试点）', () => {

  test('⑧ 键名/白名单枚举/文案与批0 照搬契约一致（DOM 断言面真源）', () => {
    expect(KEY_MSGS).toBe('qabot_msgs');            // localStorage 键（旧版双向兼容）
    expect(SRC_MAXSHOW).toBe(2);                    // 出处条折叠阈值（+N 展开行为）
    expect(Object.keys(CC_VERDICT).sort()).toEqual(
      ['not_relevant', 'partial', 'supports', 'unsupported']);
    expect(CC_VERDICT.supports).toBe('支持');
    expect(CC_VERDICT.unsupported).toBe('不支持');
    expect(Object.keys(CC_LABEL).sort()).toEqual(['grounded', 'inferred', 'partial']);
    expect(CC_LABEL.grounded).toBe('引文有据');
    // 提示条文案（.offtopic/.ev 断言面逐字对齐）
    expect(INSUFF_HEAD).toBe('语料可能不足：');
    expect(INSUFF_FALLBACK).toBe('本题涉及精确数值/参数取值，检索语料未必充分覆盖，请以官方原文为准并建议人工复核。');
    expect(OFFTOPIC_TEXT).toBe('本次未命中语料，回答为通用模型输出');
  });
});
