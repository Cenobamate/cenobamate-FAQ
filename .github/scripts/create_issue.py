#!/usr/bin/env python3
"""
create_issue.py — 读取 pending_papers_list.json，生成 Issue body 并通过 GitHub API 创建 Issue
"""

import json
import os
import sys
import urllib.request

def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("PAT_TOKEN", "")
    
    if not token:
        print("❌ PAT_TOKEN 未设置", file=sys.stderr)
        sys.exit(1)
    
    # 读取 pending papers
    with open("pending_papers_list.json", "r", encoding="utf-8") as f:
        papers = json.load(f)
    
    count = len(papers)
    
    # 获取北京时间
    from datetime import datetime, timezone, timedelta
    bj_tz = timezone(timedelta(hours=8))
    bj_time = datetime.now(bj_tz)
    date_str = bj_time.strftime("%Y-%m-%d")
    datetime_str = bj_time.strftime("%Y-%m-%d %H:%M")
    
    # 生成 Issue body
    lines = []
    lines.append(f"## 📚 本周新增 cenobamate 文献")
    lines.append("")
    lines.append(f"**日期**: {datetime_str} (北京时间)")
    lines.append(f"**新增文献数量**: {count} 篇")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    for i, paper in enumerate(papers, 1):
        lines.append(f"### {i}. {paper['title']}")
        lines.append("")
        lines.append(f"| 字段 | 内容 |")
        lines.append(f"|------|------|")
        lines.append(f"| PMID | [{paper['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/) |")
        lines.append(f"| 第一作者 | {paper['authors']} |")
        lines.append(f"| 期刊 | {paper['journal']} |")
        lines.append(f"| 发表日期 | {paper['date']} |")
        lines.append(f"| 分类建议 | **{paper['category']}** |")
        lines.append(f"| 中文摘要 | {paper['summary']} |")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    lines.append(f"## ✅ 确认推送")
    lines.append("")
    lines.append(f"如确认将以上 {count} 篇文献推送到文献速查页面，请在此 Issue 回复：")
    lines.append("")
    lines.append("```")
    lines.append("确认推送")
    lines.append("```")
    lines.append("")
    lines.append("如需修改某篇文献的分类，请在回复中注明，例如：")
    lines.append("```")
    lines.append(f"确认推送，但 PMID {papers[0]['pmid']} 改为"临床试验"")
    lines.append("```")
    lines.append("")
    lines.append("> ⏰ 本 Issue 将在确认后自动推送文献到 `literature-data.json` 并关闭。")
    
    body = "\n".join(lines)
    title = f"[待确认] 本周新增cenobamate文献 {date_str}"
    
    # 通过 GitHub API 创建 Issue
    issue_data = json.dumps({
        "title": title,
        "body": body,
        "labels": ["pending-confirmation", "pubmed-update"]
    }).encode("utf-8")
    
    url = f"https://api.github.com/repos/{repo}/issues"
    req = urllib.request.Request(url, data=issue_data, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            issue_url = result.get("html_url", "N/A")
            issue_number = result.get("number", "N/A")
            print(f"✅ Issue 已创建: {issue_url}")
            print(f"   Issue 编号: #{issue_number}")
            print(f"   标题: {title}")
            print(f"   文献数量: {count}")
    except Exception as e:
        print(f"❌ 创建 Issue 失败: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
