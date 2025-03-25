import argparse
import copy
from collections import Counter

import iptc
import ipaddress
import random
import string
import time

from iptc import IPTCError
from kubernetes import client, config


POD_CIDR = "10.244.0.0/16"

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


def get_node_pod_subnets():
    # Load kubeconfig from the default location (~/.kube/config)
    config.load_kube_config()  # Load configuration to connect to the cluster

    # Create an instance of the CoreV1Api to interact with the Kubernetes API
    v1 = client.CoreV1Api()

    # List all nodes in the Kubernetes cluster
    nodes = v1.list_node().items

    # Create a dictionary to store node names and their corresponding pod subnets
    node_subnets = {}

    # Iterate through each node to retrieve its pod subnet
    for node in nodes:
        node_name = node.metadata.name

        # Check if the node has multiple pod CIDRs (pod_cidrs) available
        if hasattr(node.spec, 'pod_cidrs') and node.spec.pod_cidrs:
            pod_subnet = node.spec.pod_cidrs[0]  # If multiple, take the first subnet
        else:
            pod_subnet = node.spec.pod_cidr  # Fallback to single pod CIDR field

        # Store the result in the dictionary
        node_subnets[node_name] = pod_subnet

        # Print the node name and its corresponding pod subnet in English
        print(f"Node: {node_name} - Pod Subnet: {pod_subnet}")

    return node_subnets


# 删除所有引用指定链的规则（优化版）
def delete_references_to_chain(table, chain_names):
    # 不单独刷新，批量处理
    for ch in table.chains:
        print(ch.name)
        rules_to_delete = [
            rule for rule in ch.rules
            if rule.target and rule.target.name in chain_names
        ]
        for r in rules_to_delete:
            try:
                ch.delete_rule(r)
            except IPTCError as e:
                print(r)
                print("Error deleting rule:", e)

def delete_all_custom_rules():
    table = iptc.Table(iptc.Table.FILTER)
    table.autocommit = False  # 使用事务批处理
    ingress_chain = iptc.Chain(table, "NETWORK-POLICY/INGRESS")
    ingress_chain.flush()
    egress_chain = iptc.Chain(table, "NETWORK-POLICY/EGRESS")
    egress_chain.flush()
    custom_chains = [
        ch.name for ch in table.chains if ch.name.startswith("podAct_")
    ]
    forward_chain = iptc.Chain(table, "FORWARD")
    for rule in forward_chain.rules:
        # Check if rule has a target and if its name matches target_chain
        if rule.target and rule.target.name == "NETWORK-POLICY":
            forward_chain.delete_rule(rule)

    # 批量删除链
    for chain_name in custom_chains:
        chain_obj = iptc.Chain(table, chain_name)
        chain_obj.flush()
        table.delete_chain(chain_name)

    table.commit()    # 一次性提交所有修改
    table.refresh()   # 统一刷新表状态
    table.autocommit = True
    print("Deleted old rules")


def generate_random_string_16():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))


def create_network_policy_chain():
    table = iptc.Table(iptc.Table.FILTER)
    chains = ["NETWORK-POLICY", "NETWORK-POLICY/INGRESS", "NETWORK-POLICY/EGRESS"]

    table.autocommit = False
    for chain_name in chains:
        if chain_name not in [c.name for c in table.chains]:
            table.create_chain(chain_name)

    table.commit()
    table.refresh()
    table.autocommit = True


def redirect_pod_traffic(pod_cidr):
    table = iptc.Table(iptc.Table.FILTER)
    main_chain = iptc.Chain(table, "NETWORK-POLICY")
    main_chain.flush()


    def add_jump_rule(chain_type, match_field, value):
        rule = iptc.Rule()
        setattr(rule, match_field, value)
        rule.create_match("comment").comment = f"Jump to {chain_type}"
        rule.target = iptc.Target(rule, f"NETWORK-POLICY/{chain_type}")
        main_chain.append_rule(rule)

    add_jump_rule("INGRESS", "dst", pod_cidr)
    add_jump_rule("EGRESS", "src", pod_cidr)

    forward_chain = iptc.Chain(table, "FORWARD")
    forward_rule = iptc.Rule()
    setattr(forward_rule, "src", pod_cidr)
    setattr(forward_rule, "dst", pod_cidr)
    forward_rule.create_match("comment").comment = "redirct pods traffic"
    forward_rule.target = iptc.Target(forward_rule, "NETWORK-POLICY")
    forward_chain.insert_rule(forward_rule, 0)

    table.commit()
    table.refresh()


def init_ingress_egress_rules(pod_ips):
    table = iptc.Table(iptc.Table.FILTER)
    ports = [8081, 8443, 9999, 12345, 23456, 65530]
    protocols = ["tcp", "udp", 'icmp']

    def create_per_pod_subchain(subchain_name):
        table.autocommit = False
        if subchain_name not in [c.name for c in table.chains]:
            table.create_chain(subchain_name)
        sub_chain_obj = iptc.Chain(table, subchain_name)
        sub_chain_obj.flush()
        table.commit()
        table.refresh()
        table.autocommit = True
        return sub_chain_obj

    def fill_subchain_rules(sub_chain_obj, current_pod_ip, all_pods, is_ingress):

        table.autocommit = False
        for other_ip in all_pods:
            if other_ip == current_pod_ip:
                continue

            r = random.random()
            if 0.1 <= r < 0.2:
                rule_reject = iptc.Rule()
                setattr(rule_reject, 'src' if is_ingress else 'dst', other_ip)
                setattr(rule_reject, 'dst' if is_ingress else 'src', current_pod_ip)

                proto_choice = random.choice(protocols)
                if proto_choice:
                    rule_reject.protocol = proto_choice

                if proto_choice in ["tcp", "udp"]:
                    match = rule_reject.create_match(proto_choice)
                    match.dport = str(random.choice(ports))

                # Set the rule's target to REJECT
                rule_reject.target = iptc.Target(rule_reject, "REJECT")
                # Append the constructed rule to the sub-chain
                sub_chain_obj.append_rule(rule_reject)

            if 0.3 <= r < 0.4:
                rule_drop = iptc.Rule()
                # Set source and destination addresses according to the traffic direction
                setattr(rule_drop, 'src' if is_ingress else 'dst', other_ip)
                setattr(rule_drop, 'dst' if is_ingress else 'src', current_pod_ip)

                # Randomly choose a protocol for this rule
                proto_choice = random.choice(protocols)
                if proto_choice:
                    rule_drop.protocol = proto_choice

                # Set the rule's target to DROP
                rule_drop.target = iptc.Target(rule_drop, "DROP")
                # Append the constructed rule to the sub-chain
                sub_chain_obj.append_rule(rule_drop)

            new_rule = iptc.Rule()
            setattr(new_rule, 'src' if is_ingress else 'dst', other_ip)
            # setattr(new_rule, 'dst' if is_ingress else 'src', current_pod_ip)
            proto_choice = random.choice(protocols)
            if proto_choice:
                new_rule.protocol = proto_choice

            r = random.random()
            target_choice = "ACCEPT" if r < 0.9 else "DROP" if r < 0.95 else "REJECT"

            if proto_choice in ["tcp", "udp"] and target_choice in ["DROP", "REJECT"]:
                match = new_rule.create_match(proto_choice)
                match.dport = str(random.choice(ports))

            new_rule.target = iptc.Target(new_rule, target_choice)
            sub_chain_obj.append_rule(new_rule)

            if r > 0.85:
                rule = iptc.Rule()
                string_match = rule.create_match("string")
                setattr(rule, 'dst' if is_ingress else 'src', current_pod_ip)
                string_match.string = "0x4000"
                string_match.algo = "bm"
                # Set target to RETURN, so that processing continues in the parent chain
                rule.target = iptc.Target(rule, "RETURN")
                sub_chain_obj.append_rule(rule)

        default_rule = iptc.Rule()
        default_rule.target = iptc.Target(default_rule, "ACCEPT")
        sub_chain_obj.append_rule(default_rule)
        table.commit()
        table.refresh()
        table.autocommit = True

    def batch_process_ips(chain, ips, match_field, is_ingress):
        for ip in ips:
            print(f'creating rules for pod with {ip}')
            direction = 'in' if is_ingress else 'out'
            subchain_name = f"podAct_{direction}_{ip.replace('.', '_')}"
            sub_chain_obj = create_per_pod_subchain(subchain_name)
            fill_subchain_rules(sub_chain_obj, ip, ips, is_ingress)

            table.autocommit = False
            rule = iptc.Rule()
            setattr(rule, match_field, ip)
            rule.create_match("comment").comment = f"Pod: {ip}"
            rule.target = iptc.Target(rule, subchain_name)
            chain.append_rule(rule)
            table.commit()
            table.refresh()
            table.autocommit = True
            time.sleep(0.01)  # small delay to avoid kernel resource contention

    def init_chain(chain_name, match_field, is_ingress=False):
        full_name = f"NETWORK-POLICY/{chain_name}"
        chain = iptc.Chain(table, full_name)
        chain.flush()
        table.commit()
        table.refresh()

        batch_process_ips(chain, pod_ips, match_field, is_ingress)

        default_rule = iptc.Rule()
        default_rule.create_match("comment").comment = "Default allow in main subchain"
        default_rule.target = iptc.Target(default_rule, "ACCEPT")
        chain.append_rule(default_rule)
        table.commit()
        table.refresh()

    init_chain("INGRESS", "dst", is_ingress=True)
    init_chain("EGRESS", "src", is_ingress=False)


def simulation():
    real_ips = list(set(get_pod_ips_at('default')))

    create_network_policy_chain()
    print("chain created....")
    delete_all_custom_rules()
    redirect_pod_traffic(POD_CIDR)
    print("inserting policy ....")
    init_ingress_egress_rules(real_ips)


def optimization():
    # Get the FILTER table and refresh to obtain current chains
    table = iptc.Table(iptc.Table.FILTER)
    table.refresh()

    networks = list(get_node_pod_subnets().values())

    all_subnets = []

    for net_str in networks:

        net = ipaddress.ip_network(net_str)

        subnets = list(net.subnets(new_prefix=30))

        for s in subnets:
            all_subnets.append(str(s))

    all_subnets.sort()



    custom_chain_names = [ch.name for ch in table.chains if ch.name.startswith("podAct_")]

    chain_rules = {}
    chain_direction = {}
    for chain in table.chains:
        if chain.name in custom_chain_names:
            saved_rules = []
            saved_src = []
            saved_dst = []
            for original_rule in chain.rules:
                new_rule = iptc.Rule()
                new_rule.protocol = original_rule.protocol
                new_rule.src = original_rule.src
                saved_src.append(original_rule.src)
                new_rule.dst = original_rule.dst
                saved_dst.append(original_rule.dst)
                if len(original_rule.matches) > 0 and original_rule.matches[0].name == "string":
                    continue
                for match in original_rule.matches:
                    new_match = new_rule.create_match(match.name)
                    for param, value in match.parameters.items():
                        if param == "dport":
                            new_match.dport = value
                if original_rule.target is not None:
                    new_rule.target = iptc.Target(new_rule, original_rule.target.name)
                saved_rules.append(new_rule)
            chain_rules[chain.name] = saved_rules
            chain_direction[chain.name] = 'dst' if len(set(saved_src)) > len(set(saved_dst)) else 'src'
            chain.flush()
            # Process each saved rule
    table.commit()
    table.refresh()
    table = iptc.Table(iptc.Table.FILTER)
    table.autocommit = False
    table.refresh()
    for chain in table.chains:
        if chain.name in chain_rules:
            print(f'processing {chain.name}')
            reject_drop_rules = []
            accept_rules_grouped = {}
            rules_saved = chain_rules[chain.name]
            direction = chain_direction[chain.name]
            for rule in rules_saved:
                action_lower = rule.target.name.lower()
                if action_lower in ['reject', 'drop']:
                    reject_drop_rules.append(rule)
                elif action_lower == 'accept':
                    try:
                        target_ip = rule.dst if direction == 'src' else rule.src
                        rule_ip = ipaddress.ip_interface(target_ip)
                    except ValueError:
                        continue
                    matched_subnet = None
                    for subnet in all_subnets:
                        network = ipaddress.ip_network(subnet)
                        if rule_ip in network:
                            matched_subnet = subnet
                            break

                    if matched_subnet:
                        if matched_subnet not in accept_rules_grouped:
                            accept_rules_grouped[matched_subnet] = []
                        accept_rules_grouped[matched_subnet].append(rule)

            merged_accept_rules = []
            for subnet, rules in accept_rules_grouped.items():
                merged_rule = rules[0]
                if direction == 'src':
                    merged_rule.dst = subnet
                else:
                    merged_rule.src = subnet
                merged_accept_rules.append(merged_rule)

            for rule in reject_drop_rules:
                chain.append_rule(rule)

            for rule in merged_accept_rules:
                chain.append_rule(rule)
    table.commit()
    table.refresh()


def main():
    parser = argparse.ArgumentParser(description="Execute different functions based on input argument.")
    parser.add_argument("mode", choices=["optimized", "initialized", "clear"],
                        help="Choose between 'optimized' and 'initialized' modes.")

    args = parser.parse_args()

    if args.mode == "optimized":
        optimization()
    elif args.mode == "initialized":
        simulation()
    elif args.mode == "clear":
        delete_all_custom_rules()



if __name__ == "__main__":
    main()
    # delete_all_custom_chains()
    # simulation()
    # optimization()
