from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import config

TOP_N = 12


def load_latest() -> pd.DataFrame:
    files = sorted(Path(config.RAW_DIR).glob("vacancies_*.jsonl"))
    if not files:
        raise SystemExit("Немає даних. Спочатку: python -m scraper.scrape")
    df = pd.read_json(files[-1], lines=True)
    df["snapshot"] = files[-1].stem.replace("vacancies_", "")
    return df.explode("experience").reset_index(drop=True)


def tech_flags(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        name: df["description"].str.contains(pattern, case=False, regex=True)
        for name, pattern in config.TECHNOLOGIES.items()
    })


def count_technologies(df: pd.DataFrame) -> pd.Series:
    uniq = df.drop_duplicates("url")
    return tech_flags(uniq).sum().sort_values(ascending=False)


def plot_overall(df, date_str):
    counts = count_technologies(df).head(TOP_N)
    total = df["url"].nunique()
    ax = (counts / total * 100).sort_values().plot.barh(figsize=(9, 6))
    ax.set_xlabel("% вакансій")
    ax.set_title(f"Python-технології на DOU ({total} вакансій, {date_str})")
    plt.tight_layout()
    plt.savefig(Path(config.CHARTS_DIR) / f"overall_{date_str}.png", dpi=150)
    plt.close()


def plot_by_experience(df, date_str):
    flags = tech_flags(df)
    flags["experience"] = df["experience"]
    share = flags.groupby("experience").mean() * 100
    order = [k for k in config.EXPERIENCE_LEVELS if k in share.index]
    share = share.loc[order]
    top = count_technologies(df).head(TOP_N).index
    ax = share[top].T.plot.bar(figsize=(12, 6))
    ax.set_ylabel("% вакансій у рівні")
    ax.set_title(f"Технології за рівнем досвіду ({date_str})")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(Path(config.CHARTS_DIR) / f"by_experience_{date_str}.png", dpi=150)
    plt.close()


def update_history(df, date_str) -> pd.DataFrame:
    counts = count_technologies(df)
    new = pd.DataFrame({
        "date": date_str,
        "technology": counts.index,
        "count": counts.values,
        "total": df["url"].nunique(),
    })
    path = Path(config.HISTORY_FILE)
    if path.exists():
        old = pd.read_csv(path)
        old = old[old["date"] != date_str]
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(path, index=False)
    return new


def plot_trends(history: pd.DataFrame):
    if history["date"].nunique() < 2:
        print("Для трендів потрібно щонайменше 2 дати, пропускаю")
        return
    history = history.assign(pct=history["count"] / history["total"] * 100)
    pivot = history.pivot(index="date", columns="technology", values="pct")
    top = pivot.iloc[-1].sort_values(ascending=False).head(8).index
    ax = pivot[top].plot(marker="o", figsize=(10, 6))
    ax.set_ylabel("% вакансій")
    ax.set_title("Тренди технологій")
    plt.tight_layout()
    plt.savefig(Path(config.CHARTS_DIR) / "trends.png", dpi=150)
    plt.close()


def main():
    Path(config.CHARTS_DIR).mkdir(exist_ok=True)
    Path(config.HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    df = load_latest()
    date_str = df["snapshot"].iloc[0]
    plot_overall(df, date_str)
    plot_by_experience(df, date_str)
    plot_trends(update_history(df, date_str))
    print(count_technologies(df).head(TOP_N))


if __name__ == "__main__":
    main()
