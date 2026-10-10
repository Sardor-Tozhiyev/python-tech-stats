
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

import config


TOP_N = 12


def load_latest() -> pd.DataFrame:
    """Load the latest snapshot and expand experience levels."""
    files = sorted(Path(config.RAW_DIR).glob("vacancies_*.jsonl"))

    if not files:
        raise SystemExit(
            "No data found. Run first: python -m scraper.scrape"
        )

    latest_file = files[-1]

    try:
        df = pd.read_json(latest_file, lines=True)
    except (ValueError, OSError) as exc:
        raise SystemExit(
            f"Failed to read {latest_file}: {exc}"
        ) from exc

    if df.empty:
        raise SystemExit(f"File {latest_file} contains no vacancies.")

    required_columns = {"url", "description", "experience"}
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise SystemExit(
            f"Missing columns in {latest_file}: "
            f"{', '.join(sorted(missing_columns))}"
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
    """Return boolean flags indicating technology mentions."""
    return pd.DataFrame(
        {
            name: df["description"].str.contains(
                pattern,
                case=False,
                regex=True,
                na=False,
            )
            for name, pattern in config.TECHNOLOGIES.items()
        },
        index=df.index,
    )


def count_technologies(df: pd.DataFrame) -> pd.Series:
    """Count unique vacancies mentioning each technology."""
    unique_vacancies = df.drop_duplicates(subset="url")

    if unique_vacancies.empty:
        return pd.Series(dtype="int64")

    return (
        tech_flags(unique_vacancies)
        .sum()
        .sort_values(ascending=False)
        .astype(int)
    )


def plot_overall(df: pd.DataFrame, date_str: str) -> None:
    counts = count_technologies(df).head(TOP_N)
    total = df["url"].nunique()

    if total == 0 or counts.empty:
        print("[WARN] No data available for the overall chart.")
        return

    percentages = (counts / total * 100).sort_values()

    ax = percentages.plot.barh(figsize=(9, 6))
    ax.set_xlabel("% of vacancies")
    ax.set_title(
        f"Python Technologies on DOU "
        f"({total} vacancies, {date_str})"
    )

    plt.tight_layout()
    output_path = Path(config.CHARTS_DIR) / f"overall_{date_str}.png"
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"Saved: {output_path}")


def plot_by_experience(df: pd.DataFrame, date_str: str) -> None:
    if df.empty:
        print("[WARN] No data available for the experience chart.")
        return

    flags = tech_flags(df)
    flags["experience"] = df["experience"].to_numpy()

    share = flags.groupby("experience").mean() * 100

    order = [
        level
        for level in config.EXPERIENCE_LEVELS
        if level in share.index
    ]

    if not order:
        print("[WARN] No recognized experience levels found.")
        return

    share = share.loc[order]
    top = count_technologies(df).head(TOP_N).index
    available_technologies = [
        technology for technology in top if technology in share.columns
    ]

    if not available_technologies:
        print("[WARN] No technologies available for the experience chart.")
        return

    ax = share[available_technologies].T.plot.bar(figsize=(12, 6))
    ax.set_ylabel("% of vacancies within each experience level")
    ax.set_title(f"Technologies by Experience Level ({date_str})")

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    output_path = (
        Path(config.CHARTS_DIR) / f"by_experience_{date_str}.png"
    )
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"Saved: {output_path}")


def update_history(
    df: pd.DataFrame,
    date_str: str,
) -> pd.DataFrame:
    """Update historical technology counts for a snapshot date."""
    counts = count_technologies(df)
    total = df["url"].nunique()

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

        expected_columns = {"date", "technology", "count", "total"}

        if expected_columns.issubset(old.columns):
            old = old[old["date"].astype(str) != date_str]
            new = pd.concat([old, new], ignore_index=True)
        else:
            print(
                "[WARN] The history file has an invalid structure. "
                "Recreating it."
            )

    new = new.sort_values(
        ["date", "technology"]
    ).reset_index(drop=True)

    new.to_csv(path, index=False)

    return new


def plot_trends(history: pd.DataFrame) -> None:
    if history.empty or history["date"].nunique() < 2:
        print("At least two dates are required to plot trends. Skipping.")
        return

    history = history.copy()
    history["date"] = history["date"].astype(str)
    history["count"] = pd.to_numeric(
        history["count"], errors="coerce"
    )
    history["total"] = pd.to_numeric(
        history["total"], errors="coerce"
    )

    history = history.dropna(subset=["count", "total"])
    history = history[history["total"] > 0]

    if history["date"].nunique() < 2:
        print("[WARN] Not enough valid data points to plot trends.")
        return

    history["pct"] = history["count"] / history["total"] * 100

    pivot = history.pivot_table(
        index="date",
        columns="technology",
        values="pct",
        aggfunc="last",
    ).sort_index()

    if pivot.empty:
        print("[WARN] No data available for the trends chart.")
        return

    top = (
        pivot.iloc[-1]
        .dropna()
        .sort_values(ascending=False)
        .head(8)
        .index
    )

    if len(top) == 0:
        print("[WARN] No technologies available for the trends chart.")
        return

    ax = pivot[list(top)].plot(marker="o", figsize=(10, 6))
    ax.set_ylabel("% of vacancies")
    ax.set_title("Technology Trends")

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    output_path = Path(config.CHARTS_DIR) / "trends.png"
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"Saved: {output_path}")


def main() -> None:
    Path(config.CHARTS_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.HISTORY_FILE).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df = load_latest()
    date_str = str(df["snapshot"].iloc[0])

    plot_overall(df, date_str)
    plot_by_experience(df, date_str)

    history = update_history(df, date_str)
    plot_trends(history)

    print("\nTop Technologies:")
    print(count_technologies(df).head(TOP_N))


if __name__ == "__main__":
    main()
