"""
preprocess.py  —  Step 1

Loads creditcard.csv, scales Time and Amount, saves train/test arrays
and the fitted scaler.

Run:  python preprocess.py
"""

import argparse
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [f"V{i}" for i in range(1, 29)] + ["Time", "Amount"]
TARGET_COLUMN   = "Class"

SCRIPT_DIR      = Path(__file__).resolve().parent
PROJECT_ROOT    = SCRIPT_DIR.parent
DEFAULT_INPUT   = PROJECT_ROOT / "data"   / "creditcard.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data"   / "processed"
DEFAULT_SCALER  = PROJECT_ROOT / "models" / "scaler.pkl"


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = set(FEATURE_COLUMNS + [TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")
    return df


def preprocess(df, test_size=0.2, random_state=42):
    df = df.copy()
    scaler = StandardScaler()
    df[["Time", "Amount"]] = scaler.fit_transform(df[["Time", "Amount"]])
    X = df[FEATURE_COLUMNS].values
    y = df[TARGET_COLUMN].values
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )
    return X_train, X_test, y_train, y_test, scaler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",      default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--scaler-out", default=str(DEFAULT_SCALER))
    parser.add_argument("--test-size",  type=float, default=0.2)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(
            f"\nCould not find dataset at: {os.path.abspath(args.input)}\n"
            f"Place creditcard.csv in the data\\ folder and try again."
        )

    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.scaler_out), exist_ok=True)

    print(f"Loading data from {args.input} ...")
    df = load_data(args.input)
    print(f"Loaded {len(df):,} rows  |  Fraud rate: {df[TARGET_COLUMN].mean():.4%}")

    X_train, X_test, y_train, y_test, scaler = preprocess(df, args.test_size)

    np.save(os.path.join(args.output_dir, "X_train.npy"), X_train)
    np.save(os.path.join(args.output_dir, "X_test.npy"),  X_test)
    np.save(os.path.join(args.output_dir, "y_train.npy"), y_train)
    np.save(os.path.join(args.output_dir, "y_test.npy"),  y_test)
    joblib.dump(scaler, args.scaler_out)

    print(f"Train shape : {X_train.shape}")
    print(f"Test shape  : {X_test.shape}")
    print(f"Scaler saved: {args.scaler_out}")
    print("Done.\n")


if __name__ == "__main__":
    main()
