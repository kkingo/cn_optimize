#!/usr/bin/env python3
"""
This script creates n Pods and corresponding Services on each Kubernetes node.
The Service's clusterIP starts from a given base IP and increases sequentially.
Pod and Service names as well as labels are generated accordingly.

Usage:
    python create_iperf_resources.py --n 2 --start-ip 10.96.0.100 --namespace default
"""

import argparse
import ipaddress
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

def parse_arguments():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Create multiple iperf pods and services on each Kubernetes node.")
    parser.add_argument('--n', type=int, required=True, help="Number of iperf resources to create per node.")
    parser.add_argument('--start-ip', type=str, default="10.96.0.100", help="Starting clusterIP for Services.")
    parser.add_argument('--namespace', type=str, default="default", help="Target namespace to create the resources.")
    return parser.parse_args()

def creating_test_iperf(n_instances, namespace="default", start_ip="10.96.0.100"):

    # Convert the starting IP to an IPv4Address object
    try:
        current_cluster_ip = ipaddress.IPv4Address(start_ip)
    except Exception as e:
        print("Error: Invalid starting IP address provided. Please check your input.")
        return

    # Load the Kubernetes configuration
    try:
        # Try loading local kubeconfig; if running in cluster, use load_incluster_config()
        config.load_kube_config()
        print("Successfully loaded kubeconfig.")
    except Exception as e:
        try:
            config.load_incluster_config()
            print("Successfully loaded in-cluster configuration.")
        except Exception as e:
            print("Error loading Kubernetes configuration: ", e)
            return

    # Create an instance of the CoreV1Api
    v1 = client.CoreV1Api()

    # List all nodes in the cluster
    try:
        nodes = v1.list_node().items
        if not nodes:
            print("No nodes found in the cluster.")
            return
        print(f"Found {len(nodes)} node(s) in the cluster.")
    except ApiException as e:
        print("Exception when listing nodes: %s\n" % e)
        return

    # Counter for incrementing the clusterIP for each Service across nodes
    ip_counter = 0

    # Iterate over each node and create n resources per node
    for node in nodes:
        node_name = node.metadata.name
        print(f"Processing node: {node_name}")
        for i in range(1, n_instances + 1):
            # Generate resource names and labels
            pod_name = f"iperf-{node_name}-{i}"
            service_name = f"svc-{node_name}-pod{i}"
            instance_label = str(i)
            # Calculate the Service clusterIP for the current resource
            service_cluster_ip = str(current_cluster_ip + ip_counter)
            ip_counter += 1

            # Define the Pod manifest
            pod_manifest = client.V1Pod(
                api_version="v1",
                kind="Pod",
                metadata=client.V1ObjectMeta(
                    name=pod_name,
                    labels={
                        "app": "iperf",
                        "node": node_name,
                        "instance": instance_label
                    }
                ),
                spec=client.V1PodSpec(
                    node_name=node_name,
                    containers=[
                        client.V1Container(
                            name="iperf-server",
                            image="networkstatic/iperf3",
                            command=["/bin/sh", "-c"],
                            args=["iperf3 -s -D && tail -f /dev/null"],
                            ports=[client.V1ContainerPort(container_port=5201)]
                        )
                    ]
                )
            )

            # Define the Service manifest
            service_manifest = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(
                    name=service_name,
                    labels={
                        "app": "iperf",
                        "node": node_name,
                        "instance": instance_label
                    }
                ),
                spec=client.V1ServiceSpec(
                    # Setting the cluster IP explicitly
                    cluster_ip=service_cluster_ip,
                    selector={
                        "app": "iperf",
                        "node": node_name,
                        "instance": instance_label
                    },
                    ports=[client.V1ServicePort(
                        protocol="TCP",
                        port=5201,
                        target_port=5201
                    )]
                )
            )

            # Create the Pod in the specified namespace
            try:
                print(f"Creating Pod '{pod_name}' on node '{node_name}'...")
                v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
                print(f"Pod '{pod_name}' created successfully.")
            except ApiException as e:
                print(f"Error creating Pod '{pod_name}': {e}")

            # Adding a short delay to avoid overwhelming the API server
            time.sleep(0.5)

            # Create the Service in the specified namespace
            try:
                print(f"Creating Service '{service_name}' with clusterIP '{service_cluster_ip}'...")
                v1.create_namespaced_service(namespace=namespace, body=service_manifest)
                print(f"Service '{service_name}' created successfully.")
            except ApiException as e:
                print(f"Error creating Service '{service_name}': {e}")

            # Optional: wait a bit before creating the next resource
            time.sleep(0.5)

if __name__ == "__main__":
    creating_test_iperf(n_instances=1)
