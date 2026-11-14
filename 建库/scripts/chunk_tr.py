#!/usr/bin/env python3
"""TR 精选切块驱动（2026-09-19 立，4 件；2026-09-22 期1 扩至 13 件；零百炼 API，只切块落档不嵌入）。

以现行 chunk_public.py 定稿版（题注回溯/逻辑列重建/公式词典）切 TR md：
- 不改 chunk_public.py 本体：仅 import 后 monkeypatch 两处 TS 专属闸——
  ① 文件名正则 _RE_GPP_FILE（TSxx.yyy-Vnn → TRxx.yyy-Vn.n.n）；
  ② _gpp_docinfo 的 doc 元数据（TR 4 件登记表：doc_id=TR 36.8xx 带空格形态、
    TR 研究报告 effective_status 口径、3gpp.org 直链）。
  其余切块逻辑（clause 富化/表行组+语境行/公式词典/题注回溯）与 3gpp 域完全同轨。
- 输出全指独立位 建库/chunks-tr/（同 pipeline_config 的 chunks-cr/ 独立目录先例），
  物理不触正位三档（chunks/3gpp.jsonl、chunks/监管.jsonl、chunks/切块统计.json）。
- 输入：chunks-tr/raw-tr/ 下 4 件 TR md 软链（run_domain 的 listdir 不递归，
  软链平铺；os.stat 跟随软链，fetch_date 取原始 md 的 mtime，输入不动即稳定）。
- 幂等：TR.jsonl 字节级稳定（chunk 内容不含时间戳；stats/report 档含
  generated_at 属快照，不算幂等口径——同 chunk_public 自身"幂等重切以两
  jsonl 为准"口径）。本脚本可独立重跑。
- 2026-09-22 期1 扩展注记：新增 9 件 TR（36.902/28.861/36.824/36.876/36.878/
  36.880/36.894/38.828/38.830），老 4 件登记与软链原样未动；重生成前旧
  TR.jsonl（295 块，md5 24de7d70…）已快照至 期1-20260922/work/TR.jsonl.pre-phase1，
  重生成后老 295 块行级字节一致+仅新增断言见 work/verify-phase1.json。

用法：python3 chunk_tr.py   （等价 chunk_public.py --domain 3gpp --config <TR切块配置>）
"""
import datetime
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import chunk_public as cp  # noqa: E402  同目录现行定稿版切块器

# TR 登记（原 4 件数据源：建库/raw/tr/清单-TR精选-20260918.md 一节/1.4 节；
# 2026-09-22 期1 扩库新增 9 件：题名=各件封面实核，url=fetch-manifest.json 实取直链，
# 28.861 为 28.862 替补件——前代理自行替补且虚报决策，用户 2026-09-22 事后追认）
TR_REGISTRY = {
    "TR 36.839": {
        "rel": 11, "pub_date": "2012-12",
        "title": "HetNet 移动性增强（LTE 异构网移动性研究：切换失败/RLF/ping-pong 建模与仿真）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.839/36839-b10.zip",
    },
    "TR 36.842": {
        "rel": 12, "pub_date": "2013-12",
        "title": "小站增强·密集部署（Small Cell Enhancements，高层设计）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.842/36842-c00.zip",
    },
    "TR 36.875": {
        "rel": 13, "pub_date": "2015-09",
        "title": "双连接扩展（LTE Dual Connectivity enhancements，SCG failure/MN-SN 移动性）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.875/36875-d10.zip",
    },
    "TR 36.805": {
        "rel": 9, "pub_date": "2009-12",
        "title": "MDT 起源研究（Minimization of Drive Tests：UE 测量日志/RLF 上报）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.805/36805-900.zip",
    },
    "TR 36.902": {
        "rel": 9, "pub_date": "2011-05",
        "title": "SON 用例与方案（E-UTRAN 自组织网络：自配置/自优化/自愈用例库）",
        "url": "https://www.etsi.org/deliver/etsi_tr/136900_136999/136902/09.03.01_60/tr_136902v090301p.pdf",
    },
    "TR 28.861": {
        "rel": 16, "pub_date": "2019-12",
        "title": "5G SON 增强研究（Study on the SON for 5G networks，NR 自优化用例与方案）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/28_series/28.861/28861-g00.zip",
    },
    "TR 36.824": {
        "rel": 11, "pub_date": "2012-06",
        "title": "LTE 覆盖增强（覆盖受限场景分析与门限类手段）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.824/36824-b00.zip",
    },
    "TR 36.876": {
        "rel": 13, "pub_date": "2015-09",
        "title": "密集小站高层进一步增强（超密集网双连接/移动性/邻区关系）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.876/36876-d00.zip",
    },
    "TR 36.878": {
        "rel": 13, "pub_date": "2016-01",
        "title": "高速场景性能增强（高铁切换维持与多普勒补偿）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.878/36878-d00.zip",
    },
    "TR 36.880": {
        "rel": 13, "pub_date": "2015-09",
        "title": "MDT 进一步增强（logged MDT 细化扩展）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.880/36880-d00.zip",
    },
    "TR 36.894": {
        "rel": 13, "pub_date": "2016-01",
        "title": "测量 gap 增强（异频/异系统测量 gap 对切换测量的影响）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/36_series/36.894/36894-d00.zip",
    },
    "TR 38.828": {
        "rel": 16, "pub_date": "2019-09",
        "title": "NR 交叉链路干扰与远端干扰管理（CLI/RIM）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/38_series/38.828/38828-g10.zip",
    },
    "TR 38.830": {
        "rel": 17, "pub_date": "2020-12",
        "title": "NR 覆盖增强研究（弱覆盖/RLF 恢复与测量增强）",
        "url": "https://www.3gpp.org/ftp/Specs/archive/38_series/38.830/38830-h00.zip",
    },
}

# 输入软链平铺表：软链名 → 原始 md 绝对路径（run_domain 的 listdir 不递归）
TR_LINKS = {
    "TR36.839-V11.1.0.md": "<repo>/建库/raw/tr/36.839/TR36.839-V11.1.0.md",
    "TR36.842-V12.0.0.md": "<repo>/建库/raw/tr/36.842/TR36.842-V12.0.0.md",
    "TR36.875-V13.1.0.md": "<repo>/建库/raw/tr/36.875/TR36.875-V13.1.0.md",
    "TR36.805-V9.0.0.md": "<repo>/建库/raw/tr/36.805/TR36.805-V9.0.0.md",
    "TR36.902-V9.3.1.md": "<repo>/建库/raw/tr/36.902/TR36.902-V9.3.1.md",
    "TR28.861-V16.0.0.md": "<repo>/建库/raw/tr/28.861/TR28.861-V16.0.0.md",
    "TR36.824-V11.0.0.md": "<repo>/建库/raw/tr/36.824/TR36.824-V11.0.0.md",
    "TR36.876-V13.0.0.md": "<repo>/建库/raw/tr/36.876/TR36.876-V13.0.0.md",
    "TR36.878-V13.0.0.md": "<repo>/建库/raw/tr/36.878/TR36.878-V13.0.0.md",
    "TR36.880-V13.0.0.md": "<repo>/建库/raw/tr/36.880/TR36.880-V13.0.0.md",
    "TR36.894-V13.0.0.md": "<repo>/建库/raw/tr/36.894/TR36.894-V13.0.0.md",
    "TR38.828-V16.1.0.md": "<repo>/建库/raw/tr/38.828/TR38.828-V16.1.0.md",
    "TR38.830-V17.0.0.md": "<repo>/建库/raw/tr/38.830/TR38.830-V17.0.0.md",
}

# 覆盖配置（只动 IO 路径；切块参数全默认=定稿版开关全开；价 0.5 元/百万 token
# = pipeline_config DEFAULTS 现值）。路径相对 BASE_DIR=建库/。
CFG_OVERLAY = {
    "gpp_raw_dir": "chunks-tr/raw-tr",
    "gpp_asn1_dir": "chunks-tr/raw-tr/asn1",   # 不存在 → 无 ASN.1 卡（TR 无 ASN.1 附件）
    "gpp_manifest": "raw/tr/清单-TR精选-20260918.md",
    "out_gpp": "chunks-tr/TR.jsonl",
    "out_stats": "chunks-tr/TR切块统计.json",
    "out_report": "chunks-tr/TR切块统计报告.md",
}


def _tr_docinfo(md_path, cfg):
    """TR 版 doc 元数据（复刻 _gpp_docinfo 骨架；版本从文件名三段全量取）。"""
    base = os.path.splitext(os.path.basename(md_path))[0]   # TR36.839-V11.1.0
    m = re.match(r"^TR(\d{2})\.(\d{3})-V(\d{1,2})\.(\d{1,2})\.(\d{1,2})$", base)
    if not m:
        return None
    doc_id = "TR %s.%s" % (m.group(1), m.group(2))           # "TR 36.839"（带空格形态）
    reg = TR_REGISTRY.get(doc_id)
    if reg is None:                                          # 未登记件不入语料
        return None
    exact = "%s.%s.%s" % (m.group(3), m.group(4), m.group(5))
    return {
        "source_domain": "3gpp", "doc_id": doc_id,
        "doc_title": reg["title"], "chapter": doc_id,
        "version": "Rel-%s V%s" % (reg["rel"], exact),
        "pub_date": reg["pub_date"],
        "effective_status": "TR 研究报告（Rel-%s；技术背景件非规范正文，无现行性口径，"
                            "结论以对应 TS 规范为准）" % reg["rel"],
        "src": md_path, "layer": "公开源", "corpus_type": "3gpp",
        "source_url": reg["url"],
        "fetch_date": datetime.date.fromtimestamp(os.path.getmtime(md_path)).isoformat(),
        "_grp_rows": cfg["table_group_rows"], "_tbl_chars": cfg["table_max_chars"],
        "_tbl_serialize": cfg.get("table_serialize", True),
        "_tbl_ctx": cfg.get("table_ctx_line", True),
    }


def main():
    raw_dir = cp.pipeline_config.resolve_path(CFG_OVERLAY["gpp_raw_dir"])
    os.makedirs(raw_dir, exist_ok=True)
    # 软链平铺（幂等：存在且指向正确则跳过，否则重建）
    for name, target in sorted(TR_LINKS.items()):
        link = os.path.join(raw_dir, name)
        if os.path.islink(link) and os.readlink(link) == target:
            continue
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(target, link)
    # 配置档落盘（固定内容，幂等；供复核与独立重跑）
    cfg_path = cp.pipeline_config.resolve_path("chunks-tr/TR切块配置.json")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(CFG_OVERLAY, f, ensure_ascii=False, indent=1)
    # monkeypatch 两处 TS 专属闸后，全量复用 chunk_public.main 收尾
    # （run_domain/assign_ids/查重/write_jsonl/build_stats/统计与报告写出）
    cp._RE_GPP_FILE = re.compile(r"^TR\d{2}\.\d{3}-V\d{1,2}\.\d{1,2}\.\d{1,2}\.md$")
    cp._gpp_docinfo = _tr_docinfo
    return cp.main(["--domain", "3gpp", "--config", cfg_path])


if __name__ == "__main__":
    sys.exit(main())
