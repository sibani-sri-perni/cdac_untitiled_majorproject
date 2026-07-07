import glob
import pandas as pd

# Finds every bhw_structured_<pid>.csv file the workers wrote and
# combines them into one clean final file.

worker_files = glob.glob("data/bhw_structured_*.csv")

if not worker_files:
    print("No worker output files found. Did the workers run yet?")
else:
    print(f"Found {len(worker_files)} worker file(s): {worker_files}")

    frames = [pd.read_csv(f) for f in worker_files]
    combined = pd.concat(frames, ignore_index=True)

    before = len(combined)
    combined.drop_duplicates(subset="url", inplace=True)
    after = len(combined)

    combined.to_csv("data/bhw_structured_merged.csv", index=False)

    print(f"Combined rows : {before}")
    print(f"After dedup   : {after}")
    print("Saved -> data/bhw_structured_merged.csv")
