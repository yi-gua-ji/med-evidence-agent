"""Fetch a small open-access PMC corpus for the local knowledge base."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.config import load_config  # noqa: E402
from medagent.env import load_env_file  # noqa: E402
from medagent.tools.pubmed import NcbiClient  # noqa: E402

TOPICS = [
    "SGLT2 inhibitors heart failure open access",
    "glucagon-like peptide-1 receptor agonists cardiovascular outcomes",
    "statin therapy primary prevention major vascular events",
    "hypertension blood pressure targets cardiovascular events",
    "beta blockers heart failure reduced ejection fraction mortality",
    "colchicine coronary artery disease inflammation",
]

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus"


async def main(per_topic: int = 3) -> int:
    load_env_file()
    cfg = load_config()
    client = NcbiClient(cfg)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen_pmcids: set[str] = set()
    saved = 0
    for topic in TOPICS:
        print(f"topic: {topic}")
        pmids = await client.esearch(topic, per_topic * 2)
        records = await client.efetch_pubmed(pmids)
        for record in records:
            pmcid = str(record.get("pmcid") or "").strip()
            if not pmcid or pmcid in seen_pmcids:
                continue
            article = await client.efetch_pmc(pmcid)
            if not article or len(article.get("text", "")) < 3000:
                continue
            title = article.get("title") or record.get("title") or pmcid
            pmc_stem = pmcid if pmcid.startswith("PMC") else "PMC" + pmcid
            path = OUT_DIR / f"{pmc_stem}.md"
            header = (
                f"# {title}\n\n"
                f"PMID: {record.get(chr(112)+chr(109)+chr(105)+chr(100), chr(34)+chr(34))} "
                f"PMCID: {pmc_stem}\n\n"
            )
            path.write_text(header + article.get("text", ""), encoding="utf-8")
            seen_pmcids.add(pmcid)
            saved += 1
            print(f"  saved {pmc_stem}: {title[:70]}")
            if saved >= per_topic * len(TOPICS):
                break
        if saved >= per_topic * len(TOPICS):
            break
    print(f"corpus files: {len(list(OUT_DIR.glob(chr(42))))}")
    return saved


if __name__ == "__main__":
    count = asyncio.run(main(per_topic=int(sys.argv[1]) if len(sys.argv) > 1 else 3))
    raise SystemExit(0 if count else 1)