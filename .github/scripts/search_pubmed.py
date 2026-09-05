#!/usr/bin/env python3
"""
search_pubmed.py — 每周自动搜索 PubMed 新文献并生成 pending-papers.json

流程：
1. 用 PubMed E-utilities API 搜索过去 7 天的 cenobamate 新文献
2. 与现有 literature-data.json 中的 PMID 对比，找出新增文献
3. 按 8 个分类自动归类
4. 生成 pending-papers.json（格式与 literature-data.json 一致）
5. 输出新增文献数量供工作流判断是否创建 Issue
"""

import json
import urllib.request
import urllib.parse
import sys
import os
import re
from datetime import datetime, timezone, timedelta

# ─── 配置 ─────────────────────────────────────────────
PUBMED_SEARCH_TERM = "cenobamate"
RELDATE = 7  # 过去 7 天
RETMAX = 50  # 最多获取 50 篇
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 8 个分类（与 literature-data.json 一致）
CATEGORIES = [
    "真实世界研究",
    "临床试验",
    "安全性与耐受性",
    "药物相互作用",
    "特殊人群",
    "机制研究",
    "综述与Meta分析",
    "其他",
]

# 分类关键词映射（按优先级，先匹配到的分类优先）
CATEGORY_KEYWORDS = [
    # 综述与Meta分析（优先判断，避免被其他分类抢走）
    {
        "category": "综述与Meta分析",
        "keywords": [
            "meta-analysis", "meta analysis", "systematic review",
            "narrative review", "scoping review", "literature review",
            "umbrella review", "overview",
        ],
        "title_keywords": [
            "review", "overview", "meta-analysis", "meta analysis",
            "systematic review", "narrative review",
        ],
    },
    # 真实世界研究
    {
        "category": "真实世界研究",
        "keywords": [
            "real-world", "real world", "retrospective cohort",
            "retrospective study", "observational study",
            "electronic health records", "claims data",
            "pharmacy claims", "prescription patterns",
        ],
        "title_keywords": [
            "real-world", "real world", "retrospective",
            "observational", "pharmacy claims",
        ],
    },
    # 临床试验
    {
        "category": "临床试验",
        "keywords": [
            "randomized", "randomised", "randomized controlled trial",
            "randomised controlled trial", "rct", "phase 2", "phase ii",
            "phase 3", "phase iii", "placebo-controlled", "double-blind",
            "clinical trial", "open-label extension", "pivotal trial",
        ],
        "title_keywords": [
            "trial", "randomized", "randomised", "placebo",
            "phase 2", "phase ii", "phase 3", "phase iii",
        ],
    },
    # 安全性与耐受性
    {
        "category": "安全性与耐受性",
        "keywords": [
            "adverse event", "adverse events", "adverse effect",
            "adverse effects", "safety", "tolerability", "side effect",
            "side effects", "dress syndrome", "drug reaction with eosinophilia",
            "hepatotoxicity", "dizziness", "somnolence", "discontinuation",
            "titration", "withdrawal", "tolerability profile",
        ],
        "title_keywords": [
            "safety", "tolerability", "adverse", "side effect",
            "dress", "toxicity", "tolerability profile",
        ],
    },
    # 药物相互作用
    {
        "category": "药物相互作用",
        "keywords": [
            "drug interaction", "drug-drug interaction", "pharmacokinetic interaction",
            "drug interaction profile", "concomitant", "co-administration",
            "coadministration", "cyp", "cytochrome p450", "enzyme inducer",
            "enzyme inhibitor", "pharmacokinetic",
        ],
        "title_keywords": [
            "drug interaction", "drug-drug interaction",
            "pharmacokinetic", "co-administration", "coadministration",
        ],
    },
    # 特殊人群
    {
        "category": "特殊人群",
        "keywords": [
            "pediatric", "paediatric", "children", "infant", "adolescent",
            "elderly", "older adult", "older patients", "pregnancy",
            "pregnant", "breastfeeding", "lactation", "neonatal",
            "renal impairment", "hepatic impairment", "comorbidity",
            "cognitive impairment", "developmental disability",
        ],
        "title_keywords": [
            "pediatric", "paediatric", "children", "elderly",
            "older", "pregnancy", "pregnant", "adolescent",
        ],
    },
    # 机制研究
    {
        "category": "机制研究",
        "keywords": [
            "mechanism", "mechanism of action", "pharmacodynamics",
            "pharmacology", "in vitro", "in vivo", "animal model",
            "preclinical", "molecular", "sodium channel", "gaba",
            "binding site", "electrophysiology", "neuroprotection",
            "channel", "receptor", "synaptic",
        ],
        "title_keywords": [
            "mechanism", "pharmacodynamics", "pharmacology",
            "in vitro", "in vivo", "preclinical", "molecular",
            "sodium channel", "electrophysiology",
        ],
    },
]


def fetch_url(url, timeout=30):
    """安全地获取 URL 内容"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "cenobamate-FAQ-bot/1.0 (https://github.com/Cenobamate/cenobamate-FAQ)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"⚠️ URL 获取失败: {url}\n   错误: {e}", file=sys.stderr)
        return None


def search_pubmed():
    """用 E-utilities esearch 搜索 PubMed"""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": PUBMED_SEARCH_TERM,
        "reldate": RELDATE,
        "datetype": "pdat",
        "retmax": RETMAX,
        "retmode": "json",
        "sort": "pub_date",
    })
    url = f"{EUTILS_BASE}/esearch.fcgi?{params}"
    print(f"🔍 搜索 PubMed: {url}")
    raw = fetch_url(url)
    if not raw:
        return []
    data = json.loads(raw)
    id_list = data.get("esearchresult", {}).get("idlist", [])
    count = data.get("esearchresult", {}).get("count", "0")
    print(f"   PubMed 返回 {count} 条结果，获取 PMID 列表: {id_list}")
    return id_list


def fetch_paper_details(pmids):
    """用 efetch 获取每篇文章的详情"""
    if not pmids:
        return []

    # efetch 一次获取所有文章
    ids_param = ",".join(pmids)
    url = f"{EUTILS_BASE}/efetch.fcgi?db=pubmed&id={ids_param}&retmode=xml"
    print(f"📄 获取文献详情: {url}")
    raw = fetch_url(url, timeout=60)
    if not raw:
        return []

    # 用 xml.etree 解析
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    papers = []

    for article in root.findall(".//PubmedArticle"):
        paper = parse_pubmed_article(article)
        if paper:
            papers.append(paper)

    # 去重（按 PMID）
    seen = set()
    unique = []
    for p in papers:
        if p["pmid"] not in seen:
            seen.add(p["pmid"])
            unique.append(p)

    print(f"   解析到 {len(unique)} 篇文献详情")
    return unique


def get_text(elem, tag, default=""):
    """安全获取 XML 元素文本"""
    found = elem.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return default


def parse_pubmed_article(article_elem):
    """解析单篇 PubMed 文章 XML"""
    try:
        # PMID
        pmid_elem = article_elem.find(".//PMID")
        pmid = pmid_elem.text.strip() if pmid_elem is not None and pmid_elem.text else ""

        # Article 元素
        article = article_elem.find(".//Article")
        if article is None:
            article = article_elem

        # 标题
        title_elem = article.find(".//ArticleTitle")
        title = ""
        if title_elem is not None:
            title = "".join(title_elem.itertext()).strip()

        # 作者
        author_list = article.find(".//AuthorList")
        authors_str = ""
        if author_list is not None:
            authors = []
            for author in author_list.findall(".//Author"):
                last = get_text(author, "LastName")
                initials = get_text(author, "Initials")
                if last:
                    if initials:
                        authors.append(f"{last} {initials}")
                    else:
                        authors.append(last)
                else:
                    # 集体作者
                    collective = get_text(author, "CollectiveName")
                    if collective:
                        authors.append(collective)
            if authors:
                if len(authors) <= 3:
                    authors_str = ", ".join(authors)
                else:
                    authors_str = f"{authors[0]}, et al."

        # 期刊
        journal_elem = article.find(".//Journal")
        journal = ""
        if journal_elem is not None:
            journal_title = journal_elem.find(".//Title")
            if journal_title is not None and journal_title.text:
                journal = journal_title.text.strip()
            else:
                journal_title = journal_elem.find(".//ISOAbbreviation")
                if journal_title is not None and journal_title.text:
                    journal = journal_title.text.strip()

        # 发表日期
        date_str = ""
        year = None
        pub_date = article.find(".//PubDate")
        if pub_date is not None:
            year_text = get_text(pub_date, "Year")
            month_text = get_text(pub_date, "Month")
            day_text = get_text(pub_date, "Day")
            if year_text:
                year = int(year_text)
                if month_text:
                    # 月份可能是英文缩写
                    month_map = {
                        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
                        "January": "01", "February": "02", "March": "03",
                        "April": "04", "May": "05", "June": "06", "July": "07",
                        "August": "08", "September": "09", "October": "10",
                        "November": "11", "December": "12",
                    }
                    month_num = month_map.get(month_text, month_text if month_text.isdigit() else "01")
                    if day_text:
                        date_str = f"{year_text}-{month_num}-{day_text}"
                    else:
                        date_str = f"{year_text}-{month_num}"
                else:
                    date_str = year_text
        else:
            # 尝试 MedlineDate
            medline_date = article.find(".//MedlineDate")
            if medline_date is not None and medline_date.text:
                date_str = medline_date.text.strip()
                # 尝试提取年份
                year_match = re.search(r"(20\d{2})", date_str)
                if year_match:
                    year = int(year_match.group(1))

        if not year and date_str:
            year_match = re.search(r"(20\d{2})", date_str)
            if year_match:
                year = int(year_match.group(1))

        # 摘要
        abstract_elem = article.find(".//Abstract")
        abstract = ""
        if abstract_elem is not None:
            abstract_parts = abstract_elem.findall(".//AbstractText")
            parts = []
            for part in abstract_parts:
                label = part.get("Label", "")
                text = "".join(part.itertext()).strip()
                if label:
                    parts.append(f"{label}: {text}")
                else:
                    parts.append(text)
            abstract = " ".join(parts)

        if not pmid or not title:
            return None

        return {
            "pmid": pmid,
            "title": title,
            "authors": authors_str if authors_str else "Unknown",
            "journal": journal if journal else "Unknown",
            "date": date_str if date_str else "Unknown",
            "year": year if year else 2026,
            "abstract": abstract,
        }
    except Exception as e:
        print(f"⚠️ 解析文章失败: {e}", file=sys.stderr)
        return None


def classify_paper(paper):
    """根据标题和摘要关键词分类"""
    title_lower = paper.get("title", "").lower()
    abstract_lower = paper.get("abstract", "").lower()
    combined = f"{title_lower} {abstract_lower}"

    for cat_rule in CATEGORY_KEYWORDS:
        # 先检查标题关键词
        for kw in cat_rule.get("title_keywords", []):
            if kw in title_lower:
                return cat_rule["category"]
        # 再检查摘要关键词
        for kw in cat_rule.get("keywords", []):
            if kw in combined:
                return cat_rule["category"]

    return "其他"


def generate_chinese_summary(paper):
    """
    根据英文摘要提取关键信息生成一句话中文摘要（100字以内）
    使用规则提取，不调用付费 API
    """
    abstract = paper.get("abstract", "")
    title = paper.get("title", "")

    if not abstract:
        # 如果没有摘要，根据标题生成
        return generate_summary_from_title(title)

    abstract_lower = abstract.lower()

    # 提取关键数字
    numbers = re.findall(r'(\d+\.?\d*)\s*%', abstract)
    key_numbers = [f"{n}%" for n in numbers[:3]]  # 最多取3个百分比

    # 判断研究类型
    study_type = ""
    if "meta-analysis" in abstract_lower or "systematic review" in abstract_lower:
        study_type = "综述/Meta分析"
    elif "randomized" in abstract_lower or "randomised" in abstract_lower or "placebo" in abstract_lower:
        study_type = "随机对照试验"
    elif "retrospective" in abstract_lower or "real-world" in abstract_lower or "real world" in abstract_lower:
        study_type = "真实世界/回顾性研究"
    elif "case report" in abstract_lower or "case series" in abstract_lower:
        study_type = "病例报告"
    elif "in vitro" in abstract_lower or "in vivo" in abstract_lower or "preclinical" in abstract_lower:
        study_type = "临床前研究"
    elif "pharmacokinetic" in abstract_lower:
        study_type = "药代动力学研究"

    # 提取主要发现
    findings = []

    # 搜索 efficacy 相关
    if "seizure" in abstract_lower and ("reduction" in abstract_lower or "decrease" in abstract_lower):
        findings.append("发作频率降低")
    if "responder" in abstract_lower or "50% reduction" in abstract_lower:
        findings.append("≥50%应答率")
    if "seizure-free" in abstract_lower or "seizure free" in abstract_lower:
        findings.append("无发作率")
    if "retention" in abstract_lower or "discontinuation" in abstract_lower:
        findings.append("保留率/停药率")
    if "adverse" in abstract_lower or "safety" in abstract_lower:
        findings.append("安全性数据")
    if "tolerability" in abstract_lower:
        findings.append("耐受性数据")
    if "drug interaction" in abstract_lower or "pharmacokinetic" in abstract_lower:
        findings.append("药物相互作用/药代动力学")
    if "pediatric" in abstract_lower or "children" in abstract_lower:
        findings.append("儿童人群数据")
    if "elderly" in abstract_lower or "older" in abstract_lower:
        findings.append("老年人群数据")

    # 组装摘要
    parts = []
    if study_type:
        parts.append(study_type)
    if findings:
        parts.append("，".join(findings[:3]))
    if key_numbers:
        parts.append(f"关键数据：{', '.join(key_numbers)}")

    if not parts:
        # 回退：截取摘要前80字符
        return f"本研究探讨cenobamate相关主题。{abstract[:80]}..."

    summary = "。".join(parts) + "。"

    # 截断到100字
    if len(summary) > 100:
        summary = summary[:97] + "..."

    return summary


def generate_summary_from_title(title):
    """没有摘要时，从标题生成简要描述"""
    title_lower = title.lower()

    if "review" in title_lower or "meta" in title_lower:
        return "综述类文献，总结cenobamate相关研究进展。"
    elif "safety" in title_lower or "adverse" in title_lower or "tolerability" in title_lower:
        return "安全性/耐受性相关研究。"
    elif "pediatric" in title_lower or "children" in title_lower or "elderly" in title_lower:
        return "特殊人群相关研究。"
    elif "interaction" in title_lower or "pharmacokinetic" in title_lower:
        return "药物相互作用/药代动力学研究。"
    elif "trial" in title_lower or "randomized" in title_lower:
        return "临床试验研究。"
    elif "real-world" in title_lower or "retrospective" in title_lower:
        return "真实世界/回顾性研究。"
    else:
        return "cenobamate相关研究。"


def load_existing_pmids(lit_data_path):
    """加载现有 literature-data.json 中的 PMID 列表"""
    if not os.path.exists(lit_data_path):
        print(f"⚠️ 文件不存在: {lit_data_path}")
        return set()

    with open(lit_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pmids = set()
    for paper in data.get("literature", []):
        pmid = paper.get("pmid", "")
        if pmid:
            pmids.add(str(pmid))

    print(f"📚 现有文献库中有 {len(pmids)} 个 PMID")
    return pmids


def main():
    print("=" * 60)
    print("🔬 Cenobamate 每周 PubMed 文献搜索")
    print(f"   时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
    print("=" * 60)

    # 加载现有 PMID
    lit_data_path = os.environ.get("LITERATURE_DATA_PATH", "literature-data.json")
    existing_pmids = load_existing_pmids(lit_data_path)

    # 搜索 PubMed
    pmids = search_pubmed()
    if not pmids:
        print("\n📭 PubMed 未返回结果，结束。")
        # 写入空结果文件供工作流判断
        with open("new_paper_count.txt", "w") as f:
            f.write("0")
        return

    # 获取详情
    papers = fetch_paper_details(pmids)
    if not papers:
        print("\n📭 未获取到文献详情，结束。")
        with open("new_paper_count.txt", "w") as f:
            f.write("0")
        return

    # 过滤已存在的
    new_papers = [p for p in papers if p["pmid"] not in existing_pmids]
    print(f"\n🆕 新增文献: {len(new_papers)} 篇（已过滤 {len(papers) - len(new_papers)} 篇已有文献）")

    if not new_papers:
        print("📭 本周无新增文献，静默结束。")
        with open("new_paper_count.txt", "w") as f:
            f.write("0")
        return

    # 分类 + 生成中文摘要
    for paper in new_papers:
        paper["category"] = classify_paper(paper)
        paper["summary"] = generate_chinese_summary(paper)
        # 清理不需要的字段
        paper.pop("abstract", None)
        print(f"   [{paper['category']}] PMID:{paper['pmid']} - {paper['title'][:60]}...")

    # 生成 pending-papers.json
    # 获取现有最大 ID
    max_id = 0
    if os.path.exists(lit_data_path):
        with open(lit_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for paper in data.get("literature", []):
                if isinstance(paper.get("id"), int) and paper["id"] > max_id:
                    max_id = paper["id"]

    # 分配 ID
    for i, paper in enumerate(new_papers):
        paper["id"] = max_id + i + 1

    # 重新排列字段顺序，与 literature-data.json 一致
    formatted_papers = []
    for paper in new_papers:
        formatted_papers.append({
            "id": paper["id"],
            "pmid": paper["pmid"],
            "title": paper["title"],
            "authors": paper["authors"],
            "journal": paper["journal"],
            "date": paper["date"],
            "category": paper["category"],
            "year": paper["year"],
            "summary": paper["summary"],
        })

    pending_data = {
        "lastUpdated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
        "categories": CATEGORIES,
        "literature": formatted_papers,
    }

    output_path = "pending-papers.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pending_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已生成 {output_path}，包含 {len(formatted_papers)} 篇新文献")

    # 写入数量供工作流判断
    with open("new_paper_count.txt", "w") as f:
        f.write(str(len(formatted_papers)))

    # 输出文献列表供 Issue 生成
    with open("pending_papers_list.json", "w", encoding="utf-8") as f:
        json.dump(formatted_papers, f, ensure_ascii=False, indent=2)

    print(f"\n📊 汇总:")
    print(f"   新增文献: {len(formatted_papers)} 篇")
    for cat in CATEGORIES:
        count = sum(1 for p in formatted_papers if p["category"] == cat)
        if count > 0:
            print(f"   {cat}: {count} 篇")


if __name__ == "__main__":
    main()
