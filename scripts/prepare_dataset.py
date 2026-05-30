#!/usr/bin/env python3
import json
import sys
from pathlib import Path

# Ensure imports resolve
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from bizpulse.storage.postgres import PostgresStore


def main():
    store = PostgresStore()
    pool = store._pool

    print("Retrieving completed runs from database...")
    query = """
        SELECT runs.id, businesses.url, businesses.industry, runs.output
        FROM runs
        JOIN businesses ON runs.business_id = businesses.id
        WHERE runs.status = 'complete' AND runs.output IS NOT NULL
    """

    dataset = []
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    print(f"Found {len(rows)} completed runs with non-null output.")

    for _, url, industry, output in rows:
        run_type = output.get("run_type", "marketing_strategy")
        if run_type == "daily_research":
            instruction = f"Generate a daily research report for the business at URL: {url} in the {industry} industry."
        else:
            instruction = f"Generate a marketing strategy report for the business at URL: {url} in the {industry} industry."

        # Serialize response as JSON string
        response = json.dumps(output)

        dataset.append({"instruction": instruction, "response": response})

    # Write to train.json
    output_path = ROOT / "data" / "train.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)

    print(f"Dataset successfully written to {output_path} with {len(dataset)} examples!")


if __name__ == "__main__":
    main()
