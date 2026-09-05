#!/usr/bin/env python3
"""
merge_papers.py — 将 pending-papers.json 中的文献合并到 literature-data.json

流程：
1. 读取 pending-papers.json
2. 读取现有 literature-data.json
3. 将新文献追加到 literature 数组末尾
4. 更新 lastUpdated 日期
5. 写回 literature-data.json
6. 输出合并的文献数量
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta


def main():
    pending_path = os.environ.get("PENDING_FILE", "pending-papers.json")
    lit_path = os.environ.get("LITERATURE_FILE", "literature-data.json")

    # 读取 pending papers
    if not os.path.exists(pending_path):
        print(f"❌ 文件不存在: {pending_path}", file=sys.stderr)
        # 输出 0 以防工作流失败
        print("::set-output name=paper_count::0")
        sys.exit(1)

    with open(pending_path, "r", encoding="utf-8") as f:
        pending_data = json.load(f)

    pending_papers = pending_data.get("literature", [])
    print(f"📋 pending-papers.json 中有 {len(pending_papers)} 篇文献")

    if not pending_papers:
        print("⚠️ 无待合并文献")
        print("::set-output name=paper_count::0")
        return

    # 读取现有 literature-data.json
    if not os.path.exists(lit_path):
        print(f"❌ 文件不存在: {lit_path}", file=sys.stderr)
        sys.exit(1)

    with open(lit_path, "r", encoding="utf-8") as f:
        lit_data = json.load(f)

    existing_pmids = set()
    for paper in lit_data.get("literature", []):
        pmid = paper.get("pmid", "")
        if pmid:
            existing_pmids.add(str(pmid))

    # 获取现有最大 ID
    max_id = 0
    for paper in lit_data.get("literature", []):
        if isinstance(paper.get("id"), int) and paper["id"] > max_id:
            max_id = paper["id"]

    # 过滤掉已存在的文献（防止重复）
    new_papers = []
    for paper in pending_papers:
        if str(paper.get("pmid", "")) not in existing_pmids:
            new_papers.append(paper)

    print(f"🆕 去重后新增: {len(new_papers)} 篇（过滤 {len(pending_papers) - len(new_papers)} 篇已有文献）")

    # 重新分配 ID
    for i, paper in enumerate(new_papers):
        paper["id"] = max_id + i + 1

    # 追加到 literature 数组末尾
    lit_data["literature"].extend(new_papers)

    # 更新 lastUpdated
    bj_tz = timezone(timedelta(hours=8))
    lit_data["lastUpdated"] = datetime.now(bj_tz).strftime("%Y-%m-%d")

    # 写回 literature-data.json
    with open(lit_path, "w", encoding="utf-8") as f:
        json.dump(lit_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 已合并 {len(new_papers)} 篇文献到 {lit_path}")
    print(f"   文献总数: {len(lit_data['literature'])}")
    print(f"   lastUpdated: {lit_data['lastUpdated']}")

    # 输出文献数量供工作流使用
    # GitHub Actions 输出
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
        f.write(f"paper_count={len(new_papers)}\n")
    print(f"::set-output name=paper_count::{len(new_papers)}")


if __name__ == "__main__":
    main()
