from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = Path(__file__).resolve().parent / "human_annotation_task.csv"


def calculate_human_stats(annotation_csv_path: str | Path | None = None) -> None:
    annotation_csv_path = Path(annotation_csv_path or DEFAULT_CSV)

    if not annotation_csv_path.is_file():
        print(f"Annotation file not found: {annotation_csv_path}")
        print("Run: python human_evaluation/prepare_task.py")
        return

    df = pd.read_csv(annotation_csv_path)
    df = df[df["Score"].notna() & (df["Score"].astype(str).str.strip() != "")]

    if df.empty:
        print("No completed annotations yet.")
        return

    total = len(df)
    counts = df["Human Label"].value_counts()
    pct = (counts / total) * 100

    print("\n--- Human evaluation: label distribution ---")
    for label in counts.index:
        print(f"{label}: {pct[label]:.1f}% ({int(counts[label])} samples)")

    df["Score"] = pd.to_numeric(df["Score"], errors="coerce")
    avg = df["Score"].mean()
    print(f"\nMean score: {avg:.2f} / 4.0")

    if "Error Type" in df.columns:
        print("\n--- Error type (optional column) ---")
        print(df["Error Type"].value_counts())


if __name__ == "__main__":
    calculate_human_stats()
