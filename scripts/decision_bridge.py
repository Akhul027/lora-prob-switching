import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = "broker.emqx.io"
MQTT_PORT = 1883

TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"
TOPIC_DECISION = "vms_hybrid_2026/switching_decision"

P_LOW = 0.30
P_HIGH = 0.70

current_mode = "LORA"


def make_client(client_id):
    try:
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    except AttributeError:
        return mqtt.Client(client_id=client_id)


def decide(payload):
    global current_mode

    p_lora = float(payload.get("p_lora", 0.0))

    # Hysteresis supaya tidak ping-pong
    if current_mode == "LORA" and p_lora < P_LOW:
        current_mode = "STARLINK"
    elif current_mode == "STARLINK" and p_lora > P_HIGH:
        current_mode = "LORA"

    return current_mode


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[MQTT] Connected: {reason_code}")
    client.subscribe(TOPIC_TELEMETRY)
    print(f"[MQTT] Subscribe telemetry: {TOPIC_TELEMETRY}")
    print(f"[MQTT] Publish decision : {TOPIC_DECISION}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        decision = decide(payload)

        decision_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_id": payload.get("device_id", "UNKNOWN"),
            "packet_id": payload.get("packet_id"),
            "decision": decision,
            "target": decision,
            "p_lora": payload.get("p_lora"),
            "rssi": payload.get("rssi"),
            "snr": payload.get("snr"),
            "distance_m": payload.get("distance_m"),
            "relay_status": "ON" if decision == "STARLINK" else "OFF",
        }

        # Publish JSON decision
        client.publish(TOPIC_DECISION, json.dumps(decision_payload), qos=0)

        # Publish plain decision juga, kalau firmware lama hanya expect string
        client.publish(TOPIC_DECISION + "/plain", decision, qos=0)

        print(
            f"[RX] packet={payload.get('packet_id')} "
            f"p_lora={payload.get('p_lora')} "
            f"rssi={payload.get('rssi')} "
            f"distance={payload.get('distance_m')}m "
            f"=> decision={decision}"
        )

    except Exception as e:
        print(f"[ERROR] gagal proses payload: {e}")
        print(msg.payload.decode(errors="replace"))


def main():
    client = make_client("vms-decision-bridge")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
