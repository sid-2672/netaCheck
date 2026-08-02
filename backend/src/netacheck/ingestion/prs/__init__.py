"""PRS India ingestion pipeline.

Scrapes parliamentary attendance and legislative activity data from
https://prsindia.org for Indian Members of Parliament.

Pipeline:
    PrsScraper → PrsParser → PrsNormalizer → PrsWriter
"""
