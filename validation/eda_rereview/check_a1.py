"""Check the historical grepafloxacin exposure-ratio comparison in a local absorption.json."""
import argparse
import json
from pathlib import Path


def check(document, checks):
    boards = {b["board_id"]: b for b in document["status_boards"]}
    for c in checks:
        board = boards[c["board_id"]]
        question, = [q for q in board["questions"] if q["q"] == c["q"]]
        if c["op"] == "contains":
            if c["value"] not in question[c["field"]]:
                raise ValueError(f'{c["board_id"]}: expected published F in the conclusion')
        else:
            ev, iv = c["route_pair"]
            if ev not in board["datasets"]:
                raise ValueError(f"{ev} is outside the study board")
            pair, = [p for p in document["ev_iv"] if (p["ev"], p["iv"]) == (ev, iv)]
            value = pair
            for name in c["field"].split("."):
                value = value[name]
            lo, hi = c["value"]["range"]
            if not lo <= value <= hi:
                raise ValueError(f"{ev} / {iv}: historical ratio {value} outside [{lo}, {hi}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("absorption_json", type=Path)
    args = parser.parse_args()
    spec = json.loads(Path(__file__).with_name("a1.json").read_bytes())
    check(json.loads(args.absorption_json.read_bytes()), spec["checks"])
    print(f'A1 passed ({len(spec["checks"])} checks)')
