#!/bin/bash
# List of target Linux hosts in the LAN
HOSTS=("node1" "node2" "node3")

# Check if at least one argument is provided (script path)
if [ -z "$1" ]; then
    echo "Usage: $0 <script_path> [arguments...]"
    exit 1
fi

# Local path to the Python script provided as parameter
SCRIPT_PATH="$1"
shift  # Remove the first argument so that $@ now contains parameters for the Python script

# Extract the filename from the provided script path
SCRIPT_FILENAME=$(basename "$SCRIPT_PATH")


USERNAME="root"

# Loop through each host, copy the script file, and execute it remotely with parameters
for host in "${HOSTS[@]}"; do
    echo "Copying script to host: $host"  # Print execution information in English
    scp "$SCRIPT_PATH" ${USERNAME}@${host}:/root/

    # Prepare remote command with parameters (properly quoted)
    PARAMS=$(printf " %q" "$@")

    echo "Executing script on host: $host with parameters:${PARAMS}"  # Print execution information in English
    ssh ${USERNAME}@${host} "python3 /root/${SCRIPT_FILENAME}${PARAMS}" &
done

# Wait for all background SSH processes to complete
wait
echo "Script execution completed on all hosts."  # Inform completion in English
