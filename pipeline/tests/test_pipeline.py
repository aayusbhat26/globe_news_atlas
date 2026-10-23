import numpy as np
import pytest
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pipeline.ingestion.gdelt_fetcher import GDELTFetcher
from pipeline.config import WINDOWS
from pipeline.ingestion.news_crawler import CrawlCandidate, CrawlResult, NewsCrawler
from pipeline.modelling.classifier import Classifier
from pipeline.modelling.clusterer import StoryClusterer
from pipeline.orchestration.flows import PipelineFlow
from pipeline.storage.huggingface_sync import HuggingFaceSync
from pipeline.storage.search_index import build_search_index
from pipeline.storage.parquet_store import LocalParquetStore
from pipeline.modelling.replay import ReplayBuilder
from pipeline.llm.client import LLMClient, LLMProvider
from pipeline.transforms.deduplicator import Deduplicator
from pipeline.transforms.geocoder import Geocoder
from pipeline.transforms.entity_extractor import EntityExtractor
from pipeline.transforms.country_codes import canonical_country, countries_in_text
from pipeline.transforms.disambiguator import Disambiguator
from pipeline.modelling.scorer import Scorer
from pipeline.modelling.coverage_analyser import CoverageAnalyser
from pipeline.modelling.summariser import Summariser
from pipeline.modelling.verifier import Verifier


def test_gdelt_export_parser_column_layout():
    row = [""] * 61
    row[0] = "123456789"
    row[5], row[6], row[7] = "GOV", "PRESIDENT", "USA"
    row[15], row[16], row[17] = "GOV", "STATE", "USA"
    row[25] = "1"
    row[26], row[27], row[28] = "040", "040", "04"
    row[29], row[30] = "1", "1.0"
    row[31], row[32], row[33], row[34] = "3", "2", "5", "-1.5"
    row[51], row[52], row[53] = "3", "Paris, France", "FR"
    row[56], row[57] = "48.8566", "2.3522"
    row[59] = "20261020200000"
    row[60] = "https://example.com/story"

    record = GDELTFetcher()._parse_row(row)

    assert record is not None
    assert record["lat"] == pytest.approx(48.8566)
    assert record["lng"] == pytest.approx(2.3522)
    assert record["location_name"] == "Paris, France"
    assert record["category"] == "diplomacy"
    assert record["source_metadata"]["event_code"] == "040"
    assert record["source_metadata"]["num_articles"] == 5
    assert record["url"] == "https://example.com/story"


def test_deduplicator_wire_syndication():
    dedup = Deduplicator()
    articles = [
        {
            "id": "wire_reuters_01",
            "domain": "reuters.com",
            "title": "Major clean energy treaty signed in Geneva by 50 nations",
            "snippet": "Geneva energy treaty established landmark standards for grid transmission.",
        },
        {
            "id": "syndicated_copy_01",
            "domain": "localnewspaper.com",
            "title": "Major clean energy treaty signed in Geneva by 50 nations",
            "snippet": "Geneva energy treaty established landmark standards for grid transmission.",
        },
    ]
    results = dedup.process_articles(articles)
    assert results[0]["is_duplicate"] is False
    assert results[1]["is_syndicated"] is True
    assert results[1]["duplicate_of"] == "wire_reuters_01"


def test_geocoder_disputed_locations():
    geocoder = Geocoder()
    res = geocoder.geocode("Kashmir")
    assert res is not None
    assert res["precision"] == "region"
    assert res["is_disputed"] == "Kashmir Region"


def test_remote_geocoder_cache_reuse(monkeypatch):
    geocoder = Geocoder(enable_remote=True)
    geocoder.geonames_username = ""
    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{"lat": "12.34", "lon": "56.78"}]

    def fake_get(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("url"))
        return FakeResponse()

    monkeypatch.setattr(geocoder._request_session, "get", fake_get)
    first = geocoder.geocode("Zzremoteplace")
    second = geocoder.geocode("Zzremoteplace")

    assert first is not None
    assert second is not None
    assert first["lat"] == pytest.approx(12.34)
    assert first["is_disputed"] is None
    assert second["is_disputed"] is None
    assert len(calls) == 1


def test_title_location_beats_outlet_city():
    geocoder = Geocoder()
    title_entities = {"locations": [], "countries": ["France"]}
    body_entities = {"locations": ["New York"], "countries": ["France"]}
    res = geocoder.geocode_article(
        {"title": "A Doom Loop Threatens France as Populism Confronts Markets"},
        body_entities,
        title_entities,
    )
    assert res is not None
    assert res["precision"] == "country"
    assert res["name"] == "France"


def test_multilingual_country_and_demonym_detection():
    entities = EntityExtractor().extract(
        "Cauca, epicentro de LabInnova America Latina, iniciativa para mostrar el agro colombiano"
    )
    assert "Colombia" in entities["countries"]
    assert countries_in_text("La crisis de la deuda deja al Gobierno de Francia sin margen")[0] == "France"
    assert canonical_country("États-Unis") == "United States"
    assert canonical_country("Côte d’Ivoire") == "Côte d'Ivoire"


def test_disambiguator():
    disambiguator = Disambiguator()
    res_country = disambiguator.disambiguate("Georgia", "Tbilisi parliament votes on Black Sea trade pact.")
    assert res_country == "georgia"

    res_us = disambiguator.disambiguate("Washington", "The White House announced new executive orders today.")
    assert res_us == "washington"

    res_other = disambiguator.disambiguate("Washington", "Seattle coffee exports rose this quarter.")
    assert res_other == "seattle"


def test_coverage_analyser_gap_detection():
    analyser = CoverageAnalyser()
    # Story with Left coverage but zero Right coverage
    articles = [
        {"outlet_id": "theguardian", "alignment": "left"},
        {"outlet_id": "lemonde", "alignment": "left"},
        {"outlet_id": "elpais", "alignment": "left"},
    ]
    res = analyser.analyze(articles)
    assert res["has_coverage_gap"] is True
    assert res["spectrum"]["left"] == 3
    assert res["spectrum"]["right"] == 0


def test_scorer_single_source():
    scorer = Scorer()
    res_single = scorer.score_event(outlet_count=1, social_buzz=0.1, severity="low")
    assert res_single["is_single_source"] is True

    res_multi = scorer.score_event(outlet_count=8, social_buzz=0.6, severity="high")
    assert res_multi["is_single_source"] is False
    assert res_multi["importance"] > 0.6


def test_extractive_summary_uses_publisher_snippet():
    summariser = Summariser()
    summary = summariser._extractive([
        {
            "id": "src_1",
            "outlet": "NDTV",
            "title": "Ex-AAP Sarpanch Arrested In Punjab Over Links To Cop Caught With 15 kg Heroin",
            "snippet": "Investigators suspect that the former sarpanch and the cop were working together.",
        }
    ])
    assert "NDTV reports" in summary
    assert "Investigators suspect" in summary
    assert summary.count("Ex-AAP Sarpanch") == 1


def test_verifier_grounding():
    verifier = Verifier()
    articles = [{"title": "Kyiv signed infrastructure treaty with European consortium", "snippet": "Energy grid repairs pledge."}]

    # Valid summary grounded in the supplied reporting
    valid_summary = "Kyiv and European consortium signed infrastructure pact for grid repairs."
    res_valid = verifier.verify(valid_summary, articles)
    assert res_valid["overall_pass"] is True

    # Citation markers are stripped before storage and rejected if they reach the verifier
    cited_summary = "Kyiv signed an infrastructure pact for grid repairs [src_1]."
    assert verifier.verify(cited_summary, articles)["overall_pass"] is False

    # Hallucinated or missing citation summary
    invalid_summary = "A sudden meteor struck the facility causing massive disruption."
    res_invalid = verifier.verify(invalid_summary, articles)
    assert res_invalid["overall_pass"] is False


def test_time_windows_are_minute_accurate():
    assert WINDOWS == {"1h": 60, "24h": 1440, "7d": 10080, "30d": 43200}


def test_severity_uses_event_terms_not_coverage_volume():
    classifier = Classifier()
    routine = classifier.classify(
        "Flood watch issued for parts of New Mexico", "", source_count=8
    )
    assert routine["severity"] == "medium"
    deadly = classifier.classify("Earthquake kills 100 people", source_count=1)
    assert deadly["severity"] == "high"


def test_longer_country_names_shadow_their_substrings():
    assert countries_in_text("South Sudan") == ["South Sudan"]
    assert countries_in_text("Papua New Guinea") == ["Papua New Guinea"]


def test_clusterer_splits_unrelated_same_language_titles():
    articles = [
        {"title": "Israel's mainstream parties vote with the far right"},
        {"title": "Israeli voters turn to the far right before election"},
        {"title": "En Alberta, le soulagement des partisans d'un Canada uni"},
        {"title": "La mer Noire, angle mort de la defense de l'Otan"},
    ]
    # Identical embeddings force one agglomerative cluster; coherence must split it.
    embeddings = np.ones((4, 8))
    clusters = StoryClusterer(distance_threshold=0.9).cluster(articles, embeddings)
    sizes = sorted(len(cluster) for cluster in clusters)
    assert sizes == [1, 1, 2]


def test_clusterer_ignores_generic_country_and_org_overlap():
    articles = [
        {"title": "United Nations condemns drone strikes on civilians and infrastructure in Sudan"},
        {"title": "United Nations report highlights significant increase in U.S. climate pollution"},
        {"title": "UK fighter jets to protect Saudi Arabia from Houthi attacks"},
        {"title": "Why did Saudi Arabia execute a Bangladeshi couple over an obscene act at Mecca mosque?"},
    ]
    clusters = StoryClusterer(distance_threshold=0.9).cluster(articles, np.ones((4, 8)))
    assert sorted(len(cluster) for cluster in clusters) == [1, 1, 1, 1]


def test_clusterer_does_not_chain_separate_saudi_stories():
    titles = [
        "Why did Saudi Arabia execute a Bangladeshi couple over an obscene act at Mecca mosque? Why Dhaka is seeking answers",
        "UK fighter jets to protect Saudi Arabia from Houthi attacks",
        "UK to deploy fighter jets to defend Saudi Arabia",
        "Exclusive: Full text of the Mecca defence pact signed by Turkey, Saudi Arabia and Pakistan",
        "WW1 to Houthis: British jets for Saudi Arabia build on long military bond",
        "Pakistan army chief latest Iran visit more focused on Saudi Arabia-Houthi conflict: Sources",
        "UK to Send Fighter Jets to Help Defend Saudi Arabia From Houthi Attacks",
    ]
    clusters = StoryClusterer(distance_threshold=0.9).cluster(
        [{"title": title} for title in titles],
        np.ones((len(titles), 8)),
    )
    assert sorted(len(cluster) for cluster in clusters) == [1, 1, 1, 4]
    execution = next(cluster for cluster in clusters if "Bangladeshi" in cluster[0]["title"])
    assert len(execution) == 1
    jets = next(cluster for cluster in clusters if len(cluster) == 4)
    assert all("jets" in article["title"].lower() for article in jets)


def test_clusterer_groups_same_event_reports_with_shared_nationalities():
    titles = [
        "Saudi Arabia Executes Bangladeshi Man and Woman in Mecca",
        "Saudi Arabia Executes Two Bangladeshi Nationals",
        "Bangladesh In Diplomatic Bind After Citizens' Execution By Saudi Arabia",
        "Growing anger in Bangladesh over Saudi executions. We demand justice",
        "Why did Saudi Arabia execute a Bangladeshi couple over an obscene act at Mecca mosque? Why Dhaka is seeking answers",
        "UK fighter jets to protect Saudi Arabia from Houthi attacks",
        "UK to deploy fighter jets to defend Saudi Arabia",
        "WW1 to Houthis: British jets for Saudi Arabia build on long military bond",
        "UK to Send Fighter Jets to Help Defend Saudi Arabia From Houthi Attacks",
        "How the Mecca defense agreement between Turkey, Pakistan and Saudi Arabia will work",
    ]
    clusters = StoryClusterer(distance_threshold=0.9).cluster(
        [{"title": title} for title in titles],
        np.ones((len(titles), 8)),
    )
    assert sorted(len(cluster) for cluster in clusters) == [1, 4, 5]
    execution = next(cluster for cluster in clusters if len(cluster) == 5)
    assert all("execut" in article["title"].lower() for article in execution)
    jets = next(cluster for cluster in clusters if len(cluster) == 4)
    assert all("jets" in article["title"].lower() for article in jets)


def test_clusterer_reunites_event_reports_across_embedding_clusters():
    articles = [
        {"title": "Saudi Arabia Executes Bangladeshi Man and Woman in Mecca"},
        {"title": "Bangladesh In Diplomatic Bind After Citizens' Execution By Saudi Arabia"},
        {"title": "UK fighter jets to protect Saudi Arabia from Houthi attacks"},
    ]
    embeddings = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ])
    clusters = StoryClusterer(distance_threshold=0.4).cluster(articles, embeddings)
    assert sorted(len(cluster) for cluster in clusters) == [1, 2]
    execution = next(cluster for cluster in clusters if len(cluster) == 2)
    assert all("jets" not in article["title"].lower() for article in execution)


def test_clusterer_does_not_group_unrelated_casualties_by_country():
    articles = [
        {"title": "India and Pakistan troops killed in border clash"},
        {"title": "India and Pakistan workers killed in factory fire"},
    ]
    clusters = StoryClusterer(distance_threshold=0.9).cluster(articles, np.ones((2, 8)))
    assert sorted(len(cluster) for cluster in clusters) == [1, 1]


def test_nationality_adjectives_and_executions_are_tagged_correctly():
    title = "Saudi Arabia executes a Bangladeshi couple over an obscene act at Mecca mosque"
    countries = countries_in_text(title)
    assert "Bangladesh" in countries
    assert "Saudi Arabia" in countries

    classification = Classifier().classify(title)
    assert classification["severity"] == "high"
    assert classification["content_warning"]

    soft_language = Classifier().classify("Senate kills the bill after late-night debate")
    assert soft_language["severity"] != "high"
    assert Classifier().classify("Skilled workers rally for wage reform")["severity"] != "high"


def test_classifier_handles_sports_technology_and_other():
    classifier = Classifier()
    assert classifier.classify("ALCS Game 6: Takeaways as Rays advance to World Series")["category"] == "sports"
    assert classifier.classify("Chipmaker unveils new AI semiconductor for data centers")["category"] == "technology"
    assert classifier.classify("Give Me Five: South Africa New Releases")["category"] == "other"


def test_crawler_sitemap_parser_and_url_filtering():
    crawler = NewsCrawler()
    urlset = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/world/story-one</loc><lastmod>2026-10-21T10:00:00Z</lastmod></url>
      <url><loc>https://example.com/tag/politics</loc></url>
      <url><loc>https://example.com/image.jpg</loc></url>
    </urlset>"""
    kind, entries = crawler._xml_entries(urlset)
    assert kind == "urlset"
    assert [entry["loc"] for entry in entries][0].endswith("story-one")
    assert crawler._is_article_url("https://example.com/world/story-one")
    assert not crawler._is_article_url("https://example.com/tag/politics")
    assert not crawler._is_article_url("https://example.com/image.jpg")

    index = b"""<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/news-1.xml</loc></sitemap>
    </sitemapindex>"""
    kind, entries = crawler._xml_entries(index)
    assert kind == "sitemapindex"
    assert entries[0]["loc"].endswith("news-1.xml")


def test_crawler_budget_and_per_outlet_cap(monkeypatch):
    crawler = NewsCrawler()
    monkeypatch.setattr(
        "pipeline.ingestion.news_crawler.settings",
        SimpleNamespace(crawler_per_outlet=2, crawler_max_urls=4),
    )
    outlet_a = {"id": "a", "domain": "a.example"}
    outlet_b = {"id": "b", "domain": "b.example"}
    feed = [
        CrawlCandidate(f"https://a.example/{index}", f"https://a.example/{index}", outlet_a)
        for index in range(5)
    ] + [
        CrawlCandidate(f"https://b.example/{index}", f"https://b.example/{index}", outlet_b)
        for index in range(5)
    ]
    sitemap = [
        CrawlCandidate("https://a.example/sitemap-only", "https://a.example/sitemap-only", outlet_a, from_sitemap=True),
        CrawlCandidate("https://b.example/sitemap-only", "https://b.example/sitemap-only", outlet_b, from_sitemap=True),
    ]
    selected = crawler._select_candidates(feed, sitemap)
    assert len(selected) == 4
    assert selected[0].canonical_url.endswith("sitemap-only")
    assert sum(candidate.outlet["id"] == "a" for candidate in selected) <= 2
    assert sum(candidate.outlet["id"] == "b" for candidate in selected) <= 2


def test_crawler_respects_publisher_indexing_directives():
    assert NewsCrawler._header_disallows_indexing({"X-Robots-Tag": "noarchive"})
    assert NewsCrawler._header_disallows_indexing({"X-Robots-Tag": "noindex, nofollow"})
    assert NewsCrawler._html_disallows_indexing(
        b'<html><head><meta name="robots" content="noindex,nofollow"></head></html>'
    )
    assert NewsCrawler._html_disallows_indexing(
        b'<html><head><meta name="robots" content="nosnippet"></head></html>'
    )
    assert not NewsCrawler._header_disallows_indexing({"X-Robots-Tag": "index, follow"})
    assert not NewsCrawler._html_disallows_indexing(
        b'<html><head><meta name="robots" content="index,follow"></head></html>'
    )


def test_crawler_attaches_text_to_articles():
    crawler = NewsCrawler()
    article = {
        "id": "article-1",
        "url": "https://example.com/world/story",
        "canonical_url": "https://example.com/world/story",
        "snippet": "",
        "outlet": "Example News",
        "domain": "example.com",
    }
    result = CrawlResult(
        content_by_url={
            "https://example.com/world/story": {
                "text": "A detailed report from the scene. " * 20,
                "excerpt": "A detailed report from the scene.",
                "word_count": 120,
                "fetched_at": "2026-10-21T10:00:00+00:00",
                "url": "https://example.com/world/story",
                "outlet": "Example News",
            }
        }
    )
    rows = crawler.attach_content([article], result)
    assert article["content"].startswith("A detailed report")
    assert article["snippet"].startswith("A detailed report")
    assert rows[0]["article_id"] == "article-1"
    assert rows[0]["word_count"] == 120


def test_snapshot_generator_reports_window_total_and_cap(tmp_path):
    from pipeline.modelling.snapshot_generator import SnapshotGenerator

    events = [
        {
            "id": f"evt-{index}",
            "lat": 20.0 + index,
            "lng": 30.0 + index,
            "imp": 0.9 - index * 0.1,
            "at": f"2026-10-21T0{index}:00:00+00:00",
            "cat": "politics",
        }
        for index in range(5)
    ]
    snapshot = SnapshotGenerator(tmp_path).generate(events, [], window_name="7d", total_events=12)
    assert snapshot["n"]["e"] == 5
    assert snapshot["n"]["total"] == 12
    assert snapshot["n"]["capped"] is True


def test_search_index_indexes_crawled_body(tmp_path):
    event_id = "evt-search-test"
    snapshots = {
        "24h": {
            "events": [
                {
                    "id": event_id,
                    "t": "Saudi Arabia Executes Two Bangladeshi Nationals",
                    "sum": "A short event summary.",
                    "loc": "Saudi Arabia",
                    "cat": "other",
                    "at": "2026-10-21T12:00:00+00:00",
                    "imp": 0.6,
                    "lat": 24.7,
                    "lng": 46.7,
                    "st": "developing",
                    "oc": 4,
                    "src": "Example News",
                }
            ]
        }
    }
    contexts = {
        event_id: {
            "cluster": [
                {
                    "id": "article-1",
                    "title": "Saudi Arabia Executes Two Bangladeshi Nationals",
                    "url": "https://example.com/story",
                    "published_at": "2026-10-21T12:00:00+00:00",
                }
            ],
            "primary": {"url": "https://example.com/story"},
            "countries": ["Saudi Arabia", "Bangladesh"],
        }
    }
    content_by_article = {
        "article-1": {
            "text": "Consular officials described the execution and the family's request for answers."
        }
    }
    database = tmp_path / "search_index.sqlite3"
    count = build_search_index(database, snapshots, contexts, content_by_article)
    assert count == 1
    assert database.is_file()
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT event_id, summary FROM events_fts WHERE events_fts MATCH ?",
            ('"consular"',),
        ).fetchall()
    finally:
        connection.close()
    assert rows == [(event_id, "A short event summary.")]


def test_classifier_weights_headline_over_body_noise():
    classifier = Classifier()
    politics = classifier.classify(
        "Lula, Bolsonaro seek to disqualify each other ahead of Brazil runoff",
        "The candidates sparred over technology platforms and social media.",
    )
    assert politics["category"] == "politics"
    conflict = classifier.classify(
        "Zelenskyy says Ukraine ready to freeze conflict along current front line",
        "Diplomacy and elections were also discussed.",
    )
    assert conflict["category"] == "conflict"


def test_multisource_headline_only_summary_adds_details():
    summariser = Summariser()
    summary = summariser._extractive(
        [
            {
                "outlet": "KTLA",
                "title": "Flood watch issued as Pacific storm reaches Southern California",
                "snippet": "",
            },
            {
                "outlet": "KRQE",
                "title": "Flood Watch issued for parts of New Mexico and Colorado",
                "snippet": "",
            },
            {
                "outlet": "FOX 10 Phoenix",
                "title": "Arizona preps for flood watch",
                "snippet": "",
            },
        ],
        title="Flood watch issued as Pacific storm reaches Southern California",
    )
    assert "KTLA reports" in summary
    assert "KRQE adds" in summary
    assert "New Mexico" in summary


def test_new_mexico_is_not_mexico():
    extractor = EntityExtractor()
    geocoder = Geocoder()
    title = "Flood Watch issued for parts of New Mexico and Colorado"
    geo = geocoder.geocode_article(
        {"title": title},
        extractor.extract(title),
        extractor.extract(title),
    )
    assert geo is not None
    assert geo["name"].lower() == "new mexico"
    assert geo["precision"] == "region"
    assert "Mexico" not in countries_in_text(title)


def test_primary_article_location_wins_over_secondary():
    flow = object.__new__(PipelineFlow)
    cluster = [
        {
            "title": "South Africa wine releases",
            "published_at": "2026-10-21T05:00:00+00:00",
            "geo_lat": -25.7479,
            "geo_lng": 28.2293,
            "geo_name": "South Africa",
            "geo_precision": "country",
            "source": "google_news",
        },
        {
            "title": "New York tasting notes",
            "published_at": "2026-10-21T04:00:00+00:00",
            "geo_lat": 40.7128,
            "geo_lng": -74.006,
            "geo_name": "New York",
            "geo_precision": "city",
            "source": "google_news",
        },
    ]
    geo = PipelineFlow._choose_geo(flow, cluster)
    assert geo is not None
    assert geo["name"] == "South Africa"


def test_hf_bucket_backend_selection():
    sync = HuggingFaceSync(token="test-token", repo_id="user/bucket", storage_type="bucket")
    assert sync.enabled
    assert sync.is_bucket
    dataset = HuggingFaceSync(token="test-token", repo_id="user/dataset", storage_type="dataset")
    assert not dataset.is_bucket


def test_llm_usage_budget_persists(tmp_path):
    client = LLMClient()
    client._usage_path = tmp_path / "llm_usage.json"
    provider = {"name": LLMProvider.GROQ, "rpd": 2, "rpm": 2}
    client._record_request(provider)
    assert client._usage_count("groq") == 1
    assert client._usage_path.exists()


def test_window_events_excludes_coded_records():
    flow = object.__new__(PipelineFlow)
    flow.now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    flow.settings = SimpleNamespace(
        max_snapshot_events=400,
        max_snapshot_events_7d=600,
        max_snapshot_events_30d=800,
    )
    recent = (flow.now - timedelta(minutes=10)).isoformat()
    events = [
        {"id": "real", "lat": 1.0, "lng": 2.0, "at": recent, "src": "Reuters", "imp": 0.4},
        {"id": "coded", "lat": 3.0, "lng": 4.0, "at": recent, "src": "GDELT event record", "imp": 0.9},
    ]
    selected, total = PipelineFlow._window_events(flow, events, "24h")
    assert [event["id"] for event in selected] == ["real"]
    assert total == 1


def test_replay_builder_compacts_snapshot_history(tmp_path):
    from datetime import datetime, timezone

    store = LocalParquetStore(tmp_path)
    events = [
        {
            "id": f"evt-{index}",
            "lat": 20.0 + index,
            "lng": 77.0 + index,
            "cat": "conflict",
            "imp": 0.5,
            "t": f"Event {index}",
            "at": "2026-10-23T00:00:00+00:00",
            "oc": index,
            "sp": {"left": 0, "centre": 1, "right": 0, "unrated": 0},
            "st": "breaking",
            "sb": 0.1,
            "ss": True,
            "cg": False,
            "cw": False,
            "loc": "India",
            "src": "Test News",
            "sum": "A summary that is not part of the compact replay frame.",
        }
        for index in range(3)
    ]
    arc = {
        "id": "arc-1",
        "a": "IN",
        "b": "PK",
        "countries": ["India", "Pakistan"],
        "ty": "talks",
        "dir": "bidirectional",
        "stg": "active",
        "imp": 0.8,
        "n": 3,
        "event_ids": [event["id"] for event in events],
        "a_lat": 20.0,
        "a_lng": 77.0,
        "b_lat": 30.0,
        "b_lng": 70.0,
    }
    for index, stamp in enumerate(("2026-10-22T00:00:00+00:00", "2026-10-23T00:00:00+00:00")):
        store.write(
            "gold",
            "snapshots",
            [
                {
                    "window": "24h",
                    "ts": stamp,
                    "n_events": len(events),
                    "n_arcs": 1,
                    "payload": {"ts": stamp, "n": {"e": len(events), "a": 1}, "events": events, "arcs": [arc]},
                }
            ],
            run_id=f"run-{index}",
            partition_date="2026-10-23",
        )

    archive = ReplayBuilder(tmp_path).build(
        datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    )

    assert archive["source_window"] == "24h"
    assert len(archive["frames"]) == 2
    assert archive["frames"][0]["ts"] < archive["frames"][1]["ts"]
    frame = archive["frames"][-1]
    assert len(frame["events"]) == 3
    assert "sum" not in frame["events"][0]
    assert frame["arcs"][0]["event_ids"] == ["evt-0", "evt-1", "evt-2"]
