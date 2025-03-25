#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This script queries a Kubernetes cluster to list:
- Physical addresses of all nodes (using InternalIP as the representative)
- IP addresses of all pods
- For each pod, if there is a corresponding service (based on label selectors), the service's ClusterIP.
"""

from kubernetes import client, config


def pod_matches_selector(pod, selector):
    """
    Check if a pod matches a given selector.
    :param pod: V1Pod object
    :param selector: dict containing label selectors
    :return: Boolean indicating if the pod matches the selector
    """
    pod_labels = pod.metadata.labels or {}
    for key, value in selector.items():
        if pod_labels.get(key) != value:
            return False
    return True


def get_all_pod_ips():
    try:
        config.load_kube_config()  # 加载kubeconfig配置
        v1 = client.CoreV1Api()
        pod_list = v1.list_pod_for_all_namespaces(watch=False)
        return [pod.status.pod_ip for pod in pod_list.items
                if pod.status and pod.status.pod_ip]
    except Exception as e:
        print(f"fail to get pod ips: {str(e)}")
        return []


def get_pod_ips_at(namespace):
    try:
        config.load_kube_config()  # Load kubeconfig configuration
        v1 = client.CoreV1Api()
        # Retrieve pods from the specified namespace
        pod_list = v1.list_namespaced_pod(namespace=namespace, watch=False)
        # Extract and return pod IPs if available
        return [pod.status.pod_ip for pod in pod_list.items if pod.status and pod.status.pod_ip]
    except Exception as e:
        print(f"Failed to get pod IPs: {str(e)}")  # Print error message in English
        return []

def get_main_info():
    # Load Kubernetes configuration from default location (e.g., ~/.kube/config)
    config.load_kube_config()

    v1 = client.CoreV1Api()

    # Query all nodes in the cluster
    nodes = v1.list_node().items
    print("Node Information:")
    for node in nodes:
        node_name = node.metadata.name
        # Retrieve node addresses from status.addresses
        addresses = node.status.addresses
        # For physical address, we assume the InternalIP is used.
        physical_address = None
        for addr in addresses:
            if addr.type == "InternalIP":
                physical_address = addr.address
                break
        print("Node Name: {0}".format(node_name))
        print("Physical Address (InternalIP): {0}".format(physical_address))
        print("Detailed Addresses:")
        for addr in addresses:
            print("  - Type: {0}, Address: {1}".format(addr.type, addr.address))
        print("--------------------------------------------------")

    # Query all services in the cluster
    services = v1.list_service_for_all_namespaces().items
    # Build a list of services with their selectors for easier matching with pods
    service_list = []
    for svc in services:
        # Some services may not have selectors (e.g., ExternalName services)
        if svc.spec.selector:
            service_list.append({
                'name': svc.metadata.name,
                'namespace': svc.metadata.namespace,
                'selector': svc.spec.selector,
                'cluster_ip': svc.spec.cluster_ip
            })

    # Query all pods in the cluster
    pods = v1.list_pod_for_all_namespaces().items
    print("\nPod Information:")
    for pod in pods:
        pod_name = pod.metadata.name
        pod_namespace = pod.metadata.namespace
        pod_ip = pod.status.pod_ip
        print("Pod Name: {0} (Namespace: {1})".format(pod_name, pod_namespace))
        print("Pod IP: {0}".format(pod_ip))
        associated_services = []
        # For each service, check if the pod labels match the service's selector.
        # Note: The pod and service must be in the same namespace.
        for svc in service_list:
            if svc['namespace'] != pod_namespace:
                continue
            if pod_matches_selector(pod, svc['selector']):
                associated_services.append(svc)
        if associated_services:
            print("Associated Service(s):")
            for svc in associated_services:
                print("  - Service Name: {0}, ClusterIP: {1}".format(svc['name'], svc['cluster_ip']))
        else:
            print("No associated service found.")
        print("--------------------------------------------------")

if __name__ == '__main__':
    get_main_info()
