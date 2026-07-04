import re
import csv

INPUT_FILE = "Pasted text.txt"
OUTPUT_CSV = "mqtt_history.csv"

pattern = re.compile(
    r"\[#(\d+)\]\s+"
    r"RSSI=\s*(-?\d+\.\d+)\s+"
    r"SNR=\s*(-?\d+\.\d+)\s+"
    r"D=\s*(\d+\.\d+)km\s+"
    r"PDR=\s*(\d+\.\d+)%\s+"
    r"P=(\d+\.\d+)\s+"
    r"STATE=(\w+)"
)

rows = []

with open(INPUT_FILE, "r") as f:

    for line in f:

        match = pattern.search(line)

        if match:

            rows.append([

                int(match.group(1)),

                float(match.group(2)),

                float(match.group(3)),

                float(match.group(4)),

                float(match.group(5)),

                float(match.group(6)),

                match.group(7)
            ])

# ============================================================
# SAVE CSV
# ============================================================

with open(OUTPUT_CSV, "w", newline="") as csvfile:

    writer = csv.writer(csvfile)

    writer.writerow([

        "Packet_ID",
        "RSSI_dBm",
        "SNR_dB",
        "Distance_km",
        "PDR_Percent",
        "P_LoRa",
        "State"

    ])

    writer.writerows(rows)

print(f"[INFO] CSV saved: {OUTPUT_CSV}")

print(f"[INFO] Total rows: {len(rows)}")