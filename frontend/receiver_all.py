#!/usr/bin/env python3
# receiver.py - 根据您的要求修改的接收端脚本。

import socket
import sys
import time
import os
import struct
import argparse

def receive_file(host='39.107.79.185', port=12345):
    # 要请求的算法列表
    algo_list = ['cubic', 'fastbts']
    # 显示名称映射
    algo_display_names = {'cubic': 'Regular', 'fastbts': 'Burst'}

    # 用于存储接收速率的数据结构
    receive_rates = {'Regular': [], 'Burst': []}
    time_points = {'Regular': [], 'Burst': []}

    for algo in algo_list:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((host, port))

        # 获取算法的显示名称
        display_name = algo_display_names.get(algo, algo)

        print("[+] Connected to server {}:{}".format(host, port))

        # 发送请求的算法到服务器
        client_socket.sendall(algo.encode())

        # 接收头部信息
        header_size = struct.calcsize('!Q16s')
        header_data = b''
        while len(header_data) < header_size:
            chunk = client_socket.recv(header_size - len(header_data))
            if not chunk:
                print("[-] Connection closed unexpectedly while receiving header.")
                client_socket.close()
                return
            header_data += chunk

        file_size, algo_used_bytes = struct.unpack('!Q16s', header_data)
        algo_used = algo_used_bytes.decode().strip('\x00')

        # 在输出中使用显示名称
        print("[*] File size: {} bytes".format(file_size))
        print("[*] Receiving file using congestion control algorithm: {}".format(display_name))

        received_size = 0
        # 用于存储时间戳和累计接收数据的列表
        timestamps = []
        data_received = []

        start_time = time.time()

        with open('received_file_{}.txt'.format(display_name), 'wb') as f:
            while received_size < file_size:
                data = client_socket.recv(4096)
                if not data:
                    break
                f.write(data)
                received_size += len(data)

                # 记录时间戳和接收的数据
                current_time = time.time()
                timestamps.append(current_time - start_time)
                data_received.append(received_size)

                # 更新进度
                progress = (received_size / file_size) * 100
                sys.stdout.write("\rReceiving with {}: {:.2f}%".format(display_name, progress))
                sys.stdout.flush()

        end_time = time.time()
        elapsed_time = end_time - start_time
        avg_speed = (file_size * 8 / elapsed_time) / (1024 * 1024)  # Mbps
        print("\n[+] File received using {}.".format(display_name))
        print("[*] Time taken: {:.2f} seconds".format(elapsed_time))
        print("[*] Average speed: {:.2f} Mbps".format(avg_speed))

        client_socket.close()
        print("[*] Connection closed.")

        # 处理收集的数据，每50ms计算一次接收速率
        interval = 0.05  # 50ms
        max_time = timestamps[-1]
        intervals = [i * interval for i in range(int(max_time / interval) + 1)]
        rates = []
        prev_data = 0
        prev_time = 0.0
        idx = 0

        for t in intervals:
            # 找到时间t之前接收到的数据
            while idx < len(timestamps) and timestamps[idx] <= t:
                idx += 1
            data = data_received[idx - 1] if idx > 0 else 0
            data_interval = data - prev_data
            time_interval = t - prev_time
            rate = (data_interval * 8) / (time_interval * 1024 * 1024) if time_interval > 0 else 0
            rates.append(rate)
            prev_data = data
            prev_time = t

        # 存储用于绘图的速率和时间间隔
        receive_rates[display_name] = rates
        time_points[display_name] = intervals

    # 绘制接收速率的折线图
    # plt.figure(figsize=(10, 6))
    # for algo_name in ['Regular', 'Burst']:
    #     plt.plot(time_points[algo_name][:len(receive_rates[algo_name])], receive_rates[algo_name], label=algo_name)
    # plt.xlabel('Time (s)')
    # plt.ylabel('Data transmission speed (Mbps)')
    # plt.legend()
    # plt.grid(True)
    # plt.tight_layout()
    # # 保存图表为文件
    # plt.savefig('receive_rate_plot.png')
    # print("[*] Receive rate plot saved as 'receive_rate_plot.png'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Receiver script')
    parser.add_argument('--host', type=str, default='39.107.79.185', help='Sender host IP')
    parser.add_argument('--port', type=int, default=12345, help='Sender port')
    args = parser.parse_args()

    receive_file(host=args.host, port=args.port)


