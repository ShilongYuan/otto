# FROM https://github.com/otto-de/recsys-dataset

import json
import random
import argparse
import pandas as pd

from tqdm import tqdm
from typing import List
from pathlib import Path
from copy import deepcopy
from beartype import beartype

from otto_src.labels import ground_truth


class setEncoder(json.JSONEncoder):
    def default(self, obj):
        return list(obj)


@beartype
def split_events(events: List[dict], split_idx=None):
    test_events = ground_truth(deepcopy(events))

    if not split_idx:
        split_idx = random.randint(1, len(test_events))

    test_events = test_events[:split_idx]
    labels = test_events[-1]["labels"]
    for event in test_events:
        del event["labels"]
    return test_events, labels


@beartype
def create_kaggle_testset(
    sessions: pd.DataFrame,
    sessions_output: Path,
    labels_output: Path,
):
    last_labels = []
    splitted_sessions = []

    for _, session in tqdm(
        sessions.iterrows(), desc="Creating trimmed testset", total=len(sessions)
    ):
        session = session.to_dict()
        try:
            splitted_events, labels = split_events(session["events"])
        except ValueError:
            continue
        last_labels.append({"session": session["session"], "labels": labels})
        splitted_sessions.append(
            {"session": session["session"], "events": splitted_events}
        )

    with open(sessions_output, "w") as f:
        for session in splitted_sessions:
            f.write(json.dumps(session) + "\n")

    with open(labels_output, "w") as f:
        for label in last_labels:
            f.write(json.dumps(label, cls=setEncoder) + "\n")


@beartype
def trim_session(session: dict, max_ts: int) -> dict:
    session["events"] = [event for event in session["events"] if event["ts"] < max_ts]
    return session


@beartype
def get_max_ts(sessions_file: Path) -> int:
    max_ts = float("-inf")
    with open(sessions_file) as f:
        for line in tqdm(f, desc="Finding max timestamp"):
            session = json.loads(line)
            max_ts = max(max_ts, session["events"][-1]["ts"])
    return max_ts


def train_test_split(
    session_chunks, train_file, test_file, max_ts, test_days=7, trim=True
):
    assert (test_file is not None) or (train_file is not None), "Saving nothing !"

    split_millis = test_days * 24 * 60 * 60 * 1000
    split_ts = max_ts - split_millis

    if train_file is not None:
        Path(train_file).parent.mkdir(parents=True, exist_ok=True)
        train_file = open(train_file, "w")
        print(f"- Saving train sessions to {train_file}")

    if test_file is not None:
        Path(test_file).parent.mkdir(parents=True, exist_ok=True)
        test_file = open(test_file, "w")
        print(f"- Saving test sessions to {test_file}")

    for chunk in tqdm(session_chunks, desc="Splitting sessions"):
        for _, session in chunk.iterrows():
            session = session.to_dict()
            if session["events"][0]["ts"] > split_ts:  # After split -> test
                if test_file is not None:
                    test_file.write(json.dumps(session, cls=setEncoder) + "\n")
            elif train_file is not None:  # Train
                if trim:
                    session = trim_session(session, split_ts)
                train_file.write(json.dumps(session, cls=setEncoder) + "\n")

    if train_file is not None:
        train_file.close()
    if test_file is not None:
        test_file.close()


@beartype
def main(train_set: Path, output_path: Path, days: int, seed: int):
    random.seed(seed)
    max_ts = get_max_ts(train_set)

    session_chunks = pd.read_json(train_set, lines=True, chunksize=100000)
    train_file = output_path / "train_sessions.jsonl"
    test_file_full = output_path / "test_sessions_full.jsonl"
    train_test_split(session_chunks, train_file, test_file_full, max_ts, days)

    test_sessions = pd.read_json(test_file_full, lines=True)
    test_sessions_file = output_path / "test_sessions.jsonl"
    test_labels_file = output_path / "test_labels.jsonl"
    create_kaggle_testset(test_sessions, test_sessions_file, test_labels_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-set", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.train_set, args.output_path, args.days, args.seed)
