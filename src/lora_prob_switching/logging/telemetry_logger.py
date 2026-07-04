import paho.mqtt.client as mqtt
import json
import csv
import os
import math
from datetime import datetime
from collections import deque

# =========================================================
# MQTT CONFIG
# =========================================================

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"

# =========================================================
# BASE STATION GPS (PPNS)
# =========================================================

BASE_LAT = -7.2754
BASE_LON = 112.7916

# =========================================================
# CSV CONFIG
# =========================================================

CSV_FILENAME = "vms_telemetry_dataset.csv"

CSV_HEADER = [
    "RSSI_dBm",
    "SNR_dB",
    "Latitude",
    "Longitude",
    "Distance_km",
    "Radiation_Wm2",
    "Expected_Packets",
    "Received_Packets",
    "Packet_Loss",
    "PDR_Percent",
    "Timestamp"
]

# =========================================================
# PDR TRACKER
# =========================================================

PDR_WINDOW_SIZE = 10
seq_buffer = deque(maxlen=PDR_WINDOW_SIZE)

# =========================================================
# CSV INIT
# =========================================================

def init_csv():
    file_exists = os.path.isfile(CSV_FILENAME)

    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(CSV_HEADER)
            print(f"[INFO] CSV dibuat: {CSV_FILENAME}")

# =========================================================
# HAVERSINE DISTANCE
# =========================================================

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# =========================================================
# PDR CALCULATION
# =========================================================

def compute_pdr(seq):

    seq_buffer.append(seq)

    if len(seq_buffer) < 2:
        return 1, 1, 0, 100.0

    expected = max(seq_buffer) - min(seq_buffer) + 1
    received = len(seq_buffer)

    loss = max(0, expected - received)

    pdr = (received / expected) * 100 if expected > 0 else 0

    return expected, received, loss, round(pdr, 2)

# =========================================================
# MQTT CALLBACKS
# =========================================================

def on_connect(client, userdata, flags, rc):

    if rc == 0:
        print("[INFO] Connected to HiveMQ")

        client.subscribe(TOPIC_TELEMETRY)

        print(f"[INFO] Subscribe topic: {TOPIC_TELEMETRY}\n")

    else:
        print(f"[ERROR] Connection failed: {rc}")

# =========================================================

def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode("utf-8")

        data = json.loads(payload)

        # =================================================
        # READ TELEMETRY
        # =================================================

        seq = int(data.get("seq", 0))

        rssi = float(data.get("rssi", 0))

        snr = float(data.get("snr", 0))

        lat = float(data.get("lat", 0))

        lon = float(data.get("lon", 0))

        radiation = float(data.get("radiation", 0))

        # =================================================
        # DISTANCE
        # =================================================

        distance = haversine_km(
            lat,
            lon,
            BASE_LAT,
            BASE_LON
        )

        # =================================================
        # PDR
        # =================================================

        expected, received, loss, pdr = compute_pdr(seq)

        # =================================================
        # TIMESTAMP
        # =================================================

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # =================================================
        # TERMINAL LOG
        # =================================================

        print(
            f"[{timestamp}] "
            f"SEQ={seq} "
            f"RSSI={rssi:.1f} "
            f"SNR={snr:.1f} "
            f"LAT={lat:.5f} "
            f"LON={lon:.5f} "
            f"DIST={distance:.2f}km "
            f"RAD={radiation:.1f} "
            f"PDR={pdr:.1f}%"
        )

        # =================================================
        # SAVE CSV
        # =================================================

        with open(CSV_FILENAME, mode='a', newline='') as file:

            writer = csv.writer(file)

            writer.writerow([
                rssi,
                snr,
                lat,
                lon,
                round(distance, 3),
                radiation,
                expected,
                received,
                loss,
                pdr,
                timestamp
            ])

    except json.JSONDecodeError:
        print("[ERROR] Invalid JSON")

    except Exception as e:
        print(f"[ERROR] {e}")

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print(" VMS TELEMETRY LOGGER")
    print("=" * 60)

    init_csv()

    client = mqtt.Client(
        client_id="VMS_Logger_001"
    )

    client.on_connect = on_connect

    client.on_message = on_message

    client.connect(BROKER, PORT, 60)

    try:
        client.loop_forever()

    except KeyboardInterrupt:

        print("\n[INFO] Logger stopped")

        client.disconnect()