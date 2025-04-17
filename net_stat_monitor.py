import json
import requests
import time
from kubernetes import client, config, stream
import numpy as np

# FRONTEND_URL = "http://47.107.243.93:8888/update_data"
FRONTEND_URL = "http://127.0.0.1:8888/update_data"
def send_data(current_data):
    try:
        response = requests.post(FRONTEND_URL, json=current_data)
        if response.status_code == 200:
            pass
        else:
            print(f"Failed to send data. Status code: {response.status_code}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def get_pod_net_stats(api_instance, pod_name, namespace):
    """
    Execute a command in the pod to fetch network statistics for the 'eth0' interface.
    The command reads the /proc/net/dev file and extracts the relevant line for 'eth0'.
    """
    # Command to extract network statistics for eth0
    exec_command = [
        '/bin/sh',
        '-c',
        "cat /proc/net/dev | grep eth0"
    ]
    try:
        # Execute the command in the specified pod
        resp = stream.stream(api_instance.connect_get_namespaced_pod_exec,
                             pod_name,
                             namespace,
                             command=exec_command,
                             stderr=True, stdin=False,
                             stdout=True, tty=False)
        # Expected output format:
        # "  eth0:  1234567 0 0 0 0 0 0 0 7654321 0 0 0 0 0 0 0"
        parts = resp.strip().split()
        # The received bytes are in the second column and transmitted bytes in the tenth column.
        rx_bytes = int(parts[1])
        tx_bytes = int(parts[9])
        return rx_bytes, tx_bytes
    except Exception as e:
        # Print error message in English for debugging purposes
        print("Error retrieving stats for pod {} in namespace {}: {}".format(pod_name, namespace, e))
        return None, None

import base64  # 新增导入
import pickle  # 新增导入

def get_trans_pkl_metrics(api_instance, pod_name, namespace):
    """
    从 Pod 的 /app 目录读取并解析 trans_metrics.pkl 文件
    返回反序列化的 Python 对象
    """
    exec_command = [
        '/bin/sh',
        '-c',
        "if [ -f /app/trans_metrics.pkl ]; then cat /app/trans_metrics.pkl | base64; fi"
    ]
    try:
        resp = stream.stream(
            api_instance.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=exec_command,
            stderr=True, stdin=False,
            stdout=True, tty=False
        )
        resp = resp.strip()
        if not resp:
            return None

        try:
            # Base64 解码二进制数据
            decoded_data = base64.b64decode(resp)
            # 反序列化 pickle 数据
            return pickle.loads(decoded_data)
        except (base64.binascii.Error, pickle.UnpicklingError) as e:
            print(f"Data decoding failed for pod {pod_name}: {str(e)}")
            return None
        except Exception as e:
            print(f"Unexpected parsing error in pod {pod_name}: {str(e)}")
            return None

    except Exception as e:
        print(f"Error retrieving pkl metrics for pod {pod_name}: {str(e)}")
        return None
def get_trans_metrics(api_instance, pod_name, namespace):
    """
    Execute a command in the pod to check if the trans_metrices.json file exists in /app.
    If the file exists, read the content and parse each JSON entry (one per line).

    Returns:
        A list of parsed JSON objects if any are successfully parsed, or None if the file does not exist or is empty.
    """
    # Command to check existence and read the trans_metrices.json file in /app directory
    exec_command = [
        '/bin/sh',
        '-c',
        "if [ -f /app/trans_metrics.json ]; then cat /app/trans_metrics.json; fi"
    ]
    try:
        # Execute the command in the specified pod
        resp = stream.stream(api_instance.connect_get_namespaced_pod_exec,
                             pod_name,
                             namespace,
                             command=exec_command,
                             stderr=True, stdin=False,
                             stdout=True, tty=False)
        resp = resp.lstrip('\ufeff').strip()
        if resp.strip() == "":
            # File does not exist or is empty.
            return None
        # Process the file content line by line
        entries = []
        for line in resp.strip().splitlines():
            line = line.strip()
            line = line.replace("'", '"')
            if line:
                try:
                    # Parse the JSON data from each line
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError as e:
                    # Print error details if the particular line fails to parse
                    print("JSON decode error in line: {}. Error: {}".format(line, e))
        return entries if entries else None
    except Exception as e:
        print("Error retrieving trans_metrices.json for pod {} in namespace {}: {}".format(pod_name, namespace, e))
        return None

def get_sender(pods_tx_history):
    max_mean = -1
    sender = list(pods_tx_history.keys())[-1]
    for pod, rxs in pods_tx_history.items():
        rxs = np.array(rxs)
        c_m = rxs[-1:]
        if c_m > max_mean:
            max_mean = c_m
            sender = pod
    return sender


def get_sender_from_candidates(pods_tx_history, candidates):
    if len(candidates) == 1:
        return candidates[0]
    else:
        for c in candidates:
            if c in pods_tx_history:
                if pods_tx_history[c][-1]!=0:
                    return c
        return candidates[0]


def invert_dict(original_dict):
    """
    For each key in the original dictionary, traverse its value list.
    Use each element from the value list as a new key and append the original key to the new key's value list.

    Args:
        original_dict (dict): Original dictionary where values are lists.

    Returns:
        dict: Inverted dictionary with elements from original values as keys and lists of original keys as values.
    """
    new_dict = {}
    # Iterate over the original dictionary
    for orig_key, value_list in original_dict.items():
        for item in value_list:
            # If the item is not yet a key in the new dictionary, initialize it with an empty list
            if item not in new_dict:
                new_dict[item] = []
            # Append the original key to the list associated with the item
            new_dict[item].append(orig_key)
    return new_dict


def main():
    """
    Main function to monitor the transmission rate of pods in the 'default' namespace every 1 second.
    The transmission rate is displayed in Mbps.
    """
    # Load Kubernetes configuration from default location (e.g., ~/.kube/config)
    config.load_kube_config()
    api_instance = client.CoreV1Api()

    # Retrieve the list of pods in the 'default' namespace
    pods = api_instance.list_namespaced_pod(
        namespace="default",
        label_selector="app=ml-app",
        watch=False
    )

    # Dictionary to store initial network statistics for each pod
    pod_stats = {}
    # Dictionary to store start time for each receiving candidate
    recv_start_times = {}
    pods_interactions = {}
    # Initial collection of network statistics for each pod in the default namespace
    for pod in pods.items:
        namespace = pod.metadata.namespace
        pod_name = pod.metadata.name
        rx, tx = get_pod_net_stats(api_instance, pod_name, namespace)
        trans_info = get_trans_pkl_metrics(api_instance, pod_name, namespace)
        if trans_info is None:
            print("Failed to retrieve trans_metrics for pod {} in namespace {}".format(pod_name, namespace))
        else:
            assert trans_info['sender'] == pod_name
            pods_interactions[pod_name] = trans_info['receiver']

        if rx is not None and tx is not None:
            pod_stats[pod_name] = {'rx': rx, 'tx': tx}

        else:
            print("Failed to retrieve initial stats for pod {} in namespace {}".format(pod_name, namespace))
    rec_send = invert_dict(pods_interactions)
    # Continuous monitoring loop: update every 1 second
    pods_tx_history = {}
    pods_rx_history = {}
    start_time = {}
    historical_sending = []
    optimized = 0
    while True:
        time.sleep(1)
        current_time = time.time()
        # Retrieve the list of pods in the 'default' namespace in case there are changes
        pods = api_instance.list_namespaced_pod(
            namespace="default",
            label_selector="app=ml-app",
            watch=False
        )
        monitoring_data = []
        for pod in pods.items:
            namespace = pod.metadata.namespace
            pod_name = pod.metadata.name
            new_rx, new_tx = get_pod_net_stats(api_instance, pod_name, namespace)
            if new_rx is None or new_tx is None:
                # Skip pod if data retrieval fails
                continue
            key = pod_name
            if key in pod_stats:
                # Calculate the difference in bytes over the 1-second interval
                old_rx = pod_stats[key]['rx']
                old_tx = pod_stats[key]['tx']
                delta_rx = new_rx - old_rx
                delta_tx = new_tx - old_tx
                # Convert bytes per second to Mbps: (B/s * 8) / 1e6
                delta_rx_mbps = (delta_rx * 8) / 1e6
                delta_tx_mbps = (delta_tx * 8) / 1e6
                monitoring_data.append({
                    'namespace': namespace,
                    'pod_name': pod_name,
                    'delta_rx_mbps': delta_rx_mbps,
                    'delta_tx_mbps': delta_tx_mbps
                })
                pods_tx_history.setdefault(pod_name, []).append(delta_tx_mbps)
                pods_rx_history.setdefault(pod_name, []).append(delta_rx_mbps)
                # Update the stored statistics for next interval calculation
                pod_stats[key] = {'rx': new_rx, 'tx': new_tx}
                # Print the transmission rate in Mbps
                print("Pod {} : RX rate: {:.3f} Mbps, TX rate: {:.3f} Mbps".format(pod_name,
                                                                                    delta_rx_mbps,
                                                                                    delta_tx_mbps))
        print('*' * 100)
        for pod, rxs in pods_rx_history.items():
            rxs = np.array(rxs)
            speed = np.mean(rxs[-3:])
            if rxs[-1] > 10 and len(rxs) > 1:
                if pod not in start_time.keys():
                    time_usage = 0
                    start_time[pod] = time.time()
                    historical_sending.append(int(pod.split('-')[-1]))
                else:
                    time_usage = time.time() - start_time[pod]
                sending_pod = get_sender_from_candidates(pods_tx_history, rec_send[pod])
                send_id = int(sending_pod.split('-')[-1]) + 1
                recv_id = int(pod.split('-')[-1]) + 1
                print(f'{sending_pod} -> {pod}')
                p = len(rxs) * 0.2
                p = 1 if p > 1 else p
                if historical_sending.count(1) >= 2:
                    optimized = 1 - optimized
                    historical_sending = [1]
                result = {
                    "from": send_id,
                    "to": recv_id,
                    "bandwidth": round(speed, 3),
                    "latency": -1,
                    "progress": p,
                    "timeusage": round(time_usage, 3),
                    "optimized": optimized
                }
                print(result)
                # Send the result data to the frontend service
                # send_data(result)
            else:
                if pod in start_time.keys():
                    del start_time[pod]





        # # Only consider pods with both tx and rx speeds > 0
        # for data in monitoring_data:
        #     if data['delta_tx_mbps'] > 0 and data['delta_rx_mbps'] > 0:
        #         # If tx rate is more than five times the rx rate, consider it as a sending candidate
        #         if data['delta_tx_mbps'] > 5 * data['delta_rx_mbps']:
        #             sending_candidates.append(data)
        #         else:
        #             receiving_candidates.append(data)
        #
        # # Determine the sending node (only one allowed)
        # sending_node = None
        # if sending_candidates:
        #     sending_node = max(sending_candidates, key=lambda x: x['delta_tx_mbps'] - x['delta_rx_mbps'])
        #
        # # Clean up recv_start_times: remove keys that are not in the current receiving_candidates
        # current_recv_keys = {(item['namespace'], item['pod_name']) for item in receiving_candidates}
        # for key in list(recv_start_times.keys()):
        #     if key not in current_recv_keys:
        #         del recv_start_times[key]
        #
        # # When a sending node and at least one receiving node are available, perform pairing
        # if sending_node and receiving_candidates:
        #     for recv in receiving_candidates:
        #         key = (recv['namespace'], recv['pod_name'])
        #         # If this is the first time we see this receiving candidate, record its start time
        #         if key not in recv_start_times:
        #             recv_start_times[key] = current_time
        #         # Calculate the actual transmission time for the receiving node
        #         timeusage = current_time - recv_start_times[key]
        #         send_id = int(sending_node['pod_name'].split('-')[-1]) + 1
        #         recv_id = int(recv['pod_name'].split('-')[-1]) + 1
        #         result = {
        #             "from": send_id,
        #             "to": recv_id,
        #             "bandwidth": round(recv['delta_rx_mbps'], 3),
        #             "latency": -1,
        #             "progress": -1,
        #             "timeusage": round(timeusage, 3),
        #             "optimized": 0
        #         }
        #         print(result)
        #         # Send the result data to the frontend service
        #         send_data(result)
        # else:
        #     # If no valid pairing detected, clear the receiving candidates' start times
        #     recv_start_times.clear()


if __name__ == "__main__":
    main()
