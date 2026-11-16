"""Shared test helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def sample_pubmed_xml() -> str:
    """A tiny efetch db=pubmed XML payload with two articles."""
    return """<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID>32865377</PMID>
    <Article>
      <ArticleTitle>Cardiovascular and Renal Outcomes with Empagliflozin in Heart Failure</ArticleTitle>
      <Abstract><AbstractText Label="BACKGROUND">Empagliflozin reduces risk of cardiovascular death or hospitalization in heart failure.</AbstractText></Abstract>
      <Journal><Title>N Engl J Med</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
    </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pubmed">32865377</ArticleId><ArticleId IdType="pmc">PMC7570000</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation>
    <PMID>31535829</PMID>
    <Article>
      <ArticleTitle>Dapagliflozin in Patients with Heart Failure and Reduced Ejection Fraction</ArticleTitle>
      <Abstract><AbstractText>Dapagliflozin reduced the risk of worsening heart failure or cardiovascular death.</AbstractText></Abstract>
      <Journal><Title>N Engl J Med</Title><JournalIssue><PubDate><Year>2019</Year></PubDate></JournalIssue></Journal>
    </Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""


@pytest.fixture
def sample_pmc_xml() -> str:
    """A tiny JATS payload with a body and one figure."""
    return """<?xml version="1.0"?>
<article>
  <front><article-meta><title-group><article-title>Effects of SGLT2 inhibition in heart failure</article-title></title-group></article-meta></front>
  <body>
    <sec><title>Results</title>
      <p>Empagliflozin reduced the primary composite outcome in 14.9 percent of patients.</p>
      <p>Hospitalization for heart failure was also lower.</p>
    </sec>
    <fig id="fig1"><label>Figure 1</label>
      <caption><p>Kaplan-Meier curve of heart failure hospitalization.</p></caption>
      <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="fig1.jpg"/>
    </fig>
  </body>
</article>"""