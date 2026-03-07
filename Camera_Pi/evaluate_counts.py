import argparse
import csv


def load_counts(path: str, count_field: str) -> dict[int, int]:
    output: dict[int, int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            output[int(row["frame_idx"])] = int(row[count_field])
    return output


def main():
    parser = argparse.ArgumentParser(description="Compare predicted person counts to labeled counts.")
    parser.add_argument("--labels", required=True, help="CSV with frame_idx,true_count")
    parser.add_argument("--predictions", required=True, help="CSV from benchmark_models.py")
    args = parser.parse_args()

    labels = load_counts(args.labels, "true_count")
    predictions = load_counts(args.predictions, "person_count")
    common_frames = sorted(set(labels) & set(predictions))

    if not common_frames:
        raise RuntimeError("No overlapping frame_idx values were found between labels and predictions.")

    absolute_errors = []
    exact_matches = 0

    for frame_idx in common_frames:
        error = abs(labels[frame_idx] - predictions[frame_idx])
        absolute_errors.append(error)
        if error == 0:
            exact_matches += 1

    mae = sum(absolute_errors) / len(absolute_errors)
    exact_match_pct = 100.0 * exact_matches / len(absolute_errors)

    print("=== Accuracy Summary ===")
    print(f"Frames compared : {len(absolute_errors)}")
    print(f"MAE             : {mae:.3f}")
    print(f"Exact match %   : {exact_match_pct:.2f}")


if __name__ == "__main__":
    main()