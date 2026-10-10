from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402

TOP_N = 12


def load_latest() -> pd.DataFrame:
    """Load the latest snapshot and expand experience levels."""
    files = sorted(Path(config.RAW_DIR).glob("vacancies_*.jsonl"))

    if not files:
        raise SystemExit("No data found. Run first: python -m scraper.scrape")

    latest_file = files[-1]

    try:
        df = pd.read_json(latest_file, lines=True)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Failed to read {latest_file}: {exc}") from exc

    if df.empty:
        raise SystemExit(f"File {latest_file} contains no vacancies.")

    missing = {"url", "description", "experience"} - set(df.columns)

    if missing:
        raise SystemExit(
            f"Missing columns in {latest_file}: {', '.join(sorted(missing))}"
        )

    df["url"] = df["url"].fillna("").astype(str)
    df["description"] = df["description"].fillna("").astype(str)
    df = df[df["url"].str.strip() != ""].copy()

    if df.empty:
        raise SystemExit("No vacancies with valid URLs found.")

    df["snapshot"] = latest_file.stem.replace("vacancies_", "")

    df = df.explode("experience").reset_index(drop=True)
    df = df.dropna(subset=["experience"])
    df["experience"] = df["experience"].astype(str)

    return df


def tech_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean flags: does each description mention each technology."""
    return pd.DataFrame(
        {
            name: df["description"].str.contains(
                pattern, case=False, regex=True, na=False
            )
            for name, pattern in config.TECHNOLOGIES.items()
        },
        index=df.index,
    )


def count_technologies(flags: pd.DataFrame) -> pd.Series:
    """Number of vacancies mentioning each technology, most common first.

    `flags` must contain one row per unique vacancy.
    """
    return flags.sum().sort_values(ascending=False).astype(int)


def experience_share(df: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """% of vacancies mentioning each technology within each experience level.

    `df` has one row per (vacancy, level); `flags` is indexed by vacancy URL.
    """
    row_flags = flags.loc[df["url"].to_numpy()]
    return row_flags.groupby(df["experience"].to_numpy()).mean() * 100


def save_chart(filename: str) -> None:
    path = Path(config.CHARTS_DIR) / filename
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_overall(counts: pd.Series, total: int, date_str: str) -> None:
    percentages = (counts.head(TOP_N) / total * 100).sort_values()

    ax = percentages.plot.barh(figsize=(9, 6))
    ax.set_xlabel("% of vacancies")
    ax.set_title(f"Python Technologies on DOU ({total} vacancies, {date_str})")

    save_chart(f"overall_{date_str}.png")


def plot_by_experience(
    df: pd.DataFrame,
    flags: pd.DataFrame,
    counts: pd.Series,
    date_str: str,
) -> None:
    share = experience_share(df, flags)
    levels = [lvl for lvl in config.EXPERIENCE_LEVELS if lvl in share.index]

    if not levels:
        print("[WARN] No recognized experience levels found.")
        return

    top = list(counts.head(TOP_N).index)

    ax = share.loc[levels, top].T.plot.bar(figsize=(12, 6))
    ax.set_ylabel("% of vacancies within each experience level")
    ax.set_title(f"Technologies by Experience Level ({date_str})")

    plt.xticks(rotation=45, ha="right")
    save_chart(f"by_experience_{date_str}.png")


def update_history(
    counts: pd.Series,
    total: int,
    date_str: str,
) -> pd.DataFrame:
    """Store technology counts for a snapshot date (replaces the same date)."""
    new = pd.DataFrame(
        {
            "date": date_str,
            "technology": counts.index,
            "count": counts.values,
            "total": total,
        }
    )

    path = Path(config.HISTORY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.stat().st_size > 0:
        old = pd.read_csv(path)

        if {"date", "technology", "count", "total"}.issubset(old.columns):
            old = old[old["date"].astype(str) != date_str]
            new = pd.concat([old, new], ignore_index=True)
        else:
            print(
                "[WARN] The history file has an invalid structure."
                " Recreating it."
            )

    new = new.sort_values(["date", "technology"]).reset_index(drop=True)
    new.to_csv(path, index=False)

    return new


def plot_trends(history: pd.DataFrame) -> None:
    history = history.copy()
    history["date"] = history["date"].astype(str)

    for column in ("count", "total"):
        history[column] = pd.to_numeric(history[column], errors="coerce")

    history = history.dropna(subset=["count", "total"])
    history = history[history["total"] > 0]

    if history["date"].nunique() < 2:
        print("At least two dates are required to plot trends. Skipping.")
        return

    history["pct"] = history["count"] / history["total"] * 100

    pivot = history.pivot_table(
        index="date",
        columns="technology",
        values="pct",
        aggfunc="last",
    ).sort_index()

    top = pivot.iloc[-1].dropna().sort_values(ascending=False).head(8).index

    ax = pivot[list(top)].plot(marker="o", figsize=(10, 6))
    ax.set_ylabel("% of vacancies")
    ax.set_title("Technology Trends")

    plt.xticks(rotation=45, ha="right")
    save_chart("trends.png")


def main() -> None:
    Path(config.CHARTS_DIR).mkdir(parents=True, exist_ok=True)

    df = load_latest()
    date_str = str(df["snapshot"].iloc[0])

    # Регулярні вирази виконуються один раз на унікальну вакансію.
    unique = df.drop_duplicates(subset="url").set_index("url")
    flags = tech_flags(unique)
    counts = count_technologies(flags)
    total = len(unique)

    plot_overall(counts, total, date_str)
    plot_by_experience(df, flags, counts, date_str)
    plot_trends(update_history(counts, total, date_str))

    print("\nTop Technologies:")
    print(counts.head(TOP_N))


if __name__ == "__main__":
    main()
