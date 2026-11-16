"""XML parsing tests for the PubMed tool (no network)."""

from __future__ import annotations

from medagent.tools.pubmed import parse_pmc_article, parse_pubmed_records


def test_parse_pubmed_records(sample_pubmed_xml):
    records = parse_pubmed_records(sample_pubmed_xml)
    assert len(records) == 2
    first = records[0]
    assert first["pmid"] == "32865377"
    assert first["pmcid"] == "PMC7570000"
    assert "Empagliflozin" in first["title"]
    assert first["year"] == "2020"
    assert "cardiovascular death" in first["abstract"]


def test_parse_pmc_article(sample_pmc_xml):
    article = parse_pmc_article(sample_pmc_xml, "PMC7570000")
    assert "SGLT2" in article["title"]
    assert "14.9 percent" in article["text"]
    assert len(article["figures"]) == 1
    figure = article["figures"][0]
    assert figure["label"] == "Figure 1"
    assert figure["image_url"].startswith("https://pmc.ncbi.nlm.nih.gov/articles/PMC7570000/bin/")
    assert figure["image_url"].endswith("fig1.jpg")


def test_parse_pmc_article_handles_missing_figure_href():
    xml = "<article><body><fig><label>Figure 2</label><caption>no graphic</caption></fig></body></article>"
    article = parse_pmc_article(xml, "123")
    assert article["figures"][0]["href"] == ""
    assert "image_url" not in article["figures"][0]