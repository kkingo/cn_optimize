import json
import requests
import time


def send_grouped_data(file_path, server_url):
    """
    Read data from a JSON file, group data with `from=2` and adjacent `to=3` and `to=4`,
    and send them simultaneously to the server at intervals of 1 second.

    Args:
        file_path (str): Path to the JSON file containing data to be sent.
        server_url (str): URL of the server to which the data will be sent.
    """
    try:
        # Load data from JSON file
        with open(file_path, 'r', encoding='utf-8') as file:
            data_list = json.load(file)

        print(f"Loaded {len(data_list)} data entries from {file_path}.")

        i = 0
        while i < len(data_list):
            current_data = data_list[i]
            if (
                    current_data['from'] == 2 and current_data['to'] == 3 and
                    i + 1 < len(data_list) and data_list[i + 1]['from'] == 2 and data_list[i + 1]['to'] == 4
            ):
                # Simultaneously send two JSON data
                data1 = current_data
                data2 = data_list[i + 1]
                try:
                    response1 = requests.post(server_url, json=data1)
                    response2 = requests.post(server_url, json=data2)

                    if response1.status_code == 200 and response2.status_code == 200:
                        print(f"[{i + 1}/{len(data_list)}] Sent data1 and data2 successfully.")
                    else:
                        print(f"[{i + 1}/{len(data_list)}] Failed to send both data. "
                              f"Status codes: {response1.status_code}, {response2.status_code}")
                except Exception as e:
                    print(f"[{i + 1}/{len(data_list)}] Exception occurred while sending grouped data: {e}")

                i += 2  # Skip both entries
            else:
                # Send a single JSON data
                try:
                    response = requests.post(server_url, json=current_data)
                    if response.status_code == 200:
                        print(f"[{i + 1}/{len(data_list)}] Sent single data successfully.")
                    else:
                        print(f"[{i + 1}/{len(data_list)}] Failed to send data. Status code: {response.status_code}")
                except Exception as e:
                    print(f"[{i + 1}/{len(data_list)}] Exception occurred while sending data: {e}")

                i += 1

            time.sleep(1)  # Wait for 1 second before the next send
    except FileNotFoundError:
        print(f"Error: File {file_path} not found.")
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the file.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")



if __name__ == '__main__':
    # Path to the JSON file
    file_path = 'data.json'
    # server_url = "http://192.168.0.1:8888/update_data"
    server_url = "http://39.108.80.76:8888/update_data"
    send_grouped_data(file_path, server_url)
