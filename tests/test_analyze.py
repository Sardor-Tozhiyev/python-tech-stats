import json

import pandas as pd
import pytest

import config
from analysis import analyze

TECH = {
    "Django": r"\bdjango\b",
    "Docker": r"\bdocker\b",
    "REST": r"\brest\s+apis?\b",
}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir()
    (tmp_path / "charts").mkdir()
    monkeypatch.setattr(config, "RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(config, "CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setattr(config, "HISTORY_FILE", str(tmp_path / "history.csv"))
    monkeypatch.setattr(config, "TECHNOLOGIES", TECH)
    monkeypatch.setattr(
        config, "EXPERIENCE_LEVELS", {"1_3y": "1-3", "3_5y": "3-5"}
    )


def vacancy(
    url, description, experience, scraped_at="2026-10-10T12:00:00+00:00"
):
    return {
        "url": url,
        "title": "Python Developer",
        "published": "10 жовтня 2026",
        "place": "Київ",
        "experience": experience,
        "description": description,
        "scraped_at": scraped_at,
    }


def write_snapshot(tmp_path, date, records):
    path = tmp_path / "raw" / f"vacancies_{date}.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    return path


# ---------- tech_flags ----------


def test_tech_flags_is_case_insensitive():
    df = pd.DataFrame(
        {
            "description": [
                "We use DJANGO and docker",
                "REST APIs only",
                "nothing",
            ]
        }
    )

    flags = analyze.tech_flags(df)

    assert list(flags.columns) == ["Django", "Docker", "REST"]
    assert flags["Django"].tolist() == [True, False, False]
    assert flags["Docker"].tolist() == [True, False, False]
    assert flags["REST"].tolist() == [False, True, False]


# ---------- count_technologies ----------


def test_count_technologies_counts_vacancies_and_sorts_descending():
    df = pd.DataFrame({"description": ["Django Docker", "Django", "nothing"]})

    counts = analyze.count_technologies(analyze.tech_flags(df))

    assert counts["Django"] == 2
    assert counts["Docker"] == 1
    assert counts["REST"] == 0
    assert counts.index[0] == "Django"  # відсортовано за спаданням


# ---------- experience_share ----------


def test_experience_share_counts_vacancy_in_every_matching_level():
    df = pd.DataFrame(
        {
            "url": ["a", "a", "b"],
            "experience": ["1_3y", "3_5y", "1_3y"],
        }
    )
    unique = pd.DataFrame(
        {"description": ["Django Docker", "Django"]},
        index=pd.Index(["a", "b"], name="url"),
    )

    share = analyze.experience_share(df, analyze.tech_flags(unique))

    assert share.loc["1_3y", "Django"] == 100.0  # a і b
    assert share.loc["1_3y", "Docker"] == 50.0  # лише a з двох
    assert share.loc["3_5y", "Docker"] == 100.0  # лише a
    assert share.loc["3_5y", "REST"] == 0.0


# ---------- load_latest ----------


def test_load_latest_uses_newest_file_and_expands_experience(tmp_path):
    write_snapshot(
        tmp_path, "2026-10-09", [vacancy("https://x/old/", "Old", ["1_3y"])]
    )
    write_snapshot(
        tmp_path,
        "2026-10-10",
        [
            vacancy("https://x/1/", "Django", ["1_3y", "3_5y"]),
            vacancy("", "no url, must be dropped", ["1_3y"]),
        ],
    )

    df = analyze.load_latest()

    assert set(df["snapshot"]) == {"2026-10-10"}
    assert len(df) == 2  # одна вакансія x два рівні досвіду
    assert df["url"].nunique() == 1
    assert set(df["experience"]) == {"1_3y", "3_5y"}


@pytest.mark.parametrize(
    "scraped_at", ["2026-10-10", "2026-10-10T12:00:00+00:00"]
)
def test_load_latest_accepts_old_and_new_scraped_at_format(
    tmp_path, scraped_at
):
    write_snapshot(
        tmp_path,
        "2026-10-10",
        [vacancy("https://x/1/", "Django", ["1_3y"], scraped_at=scraped_at)],
    )

    df = analyze.load_latest()

    assert len(df) == 1
    assert df["snapshot"].iloc[0] == "2026-10-10"


def test_load_latest_without_files_exits():
    with pytest.raises(SystemExit, match="No data found"):
        analyze.load_latest()


def test_load_latest_invalid_jsonl_exits(tmp_path):
    (tmp_path / "raw" / "vacancies_2026-10-10.jsonl").write_text(
        "this is not json\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        analyze.load_latest()


def test_load_latest_empty_file_exits(tmp_path):
    (tmp_path / "raw" / "vacancies_2026-10-10.jsonl").write_text(
        "", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        analyze.load_latest()


def test_load_latest_missing_columns_exits(tmp_path):
    record = vacancy("https://x/1/", "Django", ["1_3y"])
    del record["experience"]
    write_snapshot(tmp_path, "2026-10-10", [record])

    with pytest.raises(SystemExit, match="Missing columns"):
        analyze.load_latest()


# ---------- update_history ----------


def update_history_sample(date_str):
    df = pd.DataFrame({"description": ["Django Docker", "Django"]})
    counts = analyze.count_technologies(analyze.tech_flags(df))
    return analyze.update_history(counts, len(df), date_str)


def test_update_history_appends_new_dates_and_replaces_same_date(tmp_path):
    update_history_sample("2026-10-09")
    update_history_sample("2026-10-10")
    update_history_sample("2026-10-10")  # повторний запуск за ту саму дату

    history = pd.read_csv(config.HISTORY_FILE)

    assert sorted(history["date"].unique()) == ["2026-10-09", "2026-10-10"]
    assert len(history) == 2 * len(TECH)  # без дублікатів
    row = history[
        (history["date"] == "2026-10-10") & (history["technology"] == "Django")
    ]
    assert row["count"].iloc[0] == 2
    assert row["total"].iloc[0] == 2


def test_update_history_recreates_file_with_invalid_structure(tmp_path):
    (tmp_path / "history.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    history = update_history_sample("2026-10-10")

    assert {"date", "technology", "count", "total"} <= set(history.columns)
    assert len(history) == len(TECH)


# ---------- plot_trends ----------


def test_plot_trends_skips_with_single_date(tmp_path, capsys):
    history = update_history_sample("2026-10-10")

    analyze.plot_trends(history)

    assert "At least two dates" in capsys.readouterr().out
    assert not (tmp_path / "charts" / "trends.png").exists()


def test_plot_trends_creates_chart_with_two_dates(tmp_path):
    update_history_sample("2026-10-09")
    history = update_history_sample("2026-10-10")

    analyze.plot_trends(history)

    assert (tmp_path / "charts" / "trends.png").exists()


# ---------- main (наскрізний тест) ----------


def test_main_creates_charts_and_history(tmp_path):
    write_snapshot(
        tmp_path,
        "2026-10-10",
        [
            vacancy(
                "https://x/1/", "Django, Docker, REST APIs", ["1_3y", "3_5y"]
            ),
            vacancy("https://x/2/", "Django", ["3_5y"]),
        ],
    )

    analyze.main()

    assert (tmp_path / "charts" / "overall_2026-10-10.png").exists()
    assert (tmp_path / "charts" / "by_experience_2026-10-10.png").exists()
    assert (tmp_path / "history.csv").exists()

    history = pd.read_csv(tmp_path / "history.csv")
    django = history[history["technology"] == "Django"].iloc[0]

    assert django["count"] == 2 and django["total"] == 2
