#!/bin/bash

# Configuration
REPO_URL="https://github.com/DzwngOo/INF2009_EdgeComputing.git"
BRANCH="LoRa"
TARGET_FOLDER="Station_Pi"  # The folder inside the git repo
DESTINATION_PATH="/home/stationpi/Desktop/Station_Pi"
# Use script location as source of truth for relative paths if needed
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "--- Starting Clean Pull ---"

# 1. Create a temporary directory for the download
TEMP_DIR=$(mktemp -d)
echo "Included temporary workspace: $TEMP_DIR"

# 2. Initialize sparse git repo in temp
cd "$TEMP_DIR"
git init
git remote add origin "$REPO_URL"
git config core.sparseCheckout true

# 3. Define the folder to download
echo "$TARGET_FOLDER/" >> .git/info/sparse-checkout

# 4. Pull the content
echo "Pulling from branch $BRANCH..."
git pull origin "$BRANCH"

# 5. Move files to the final destination
echo "Setting up destination: $DESTINATION_PATH"

# If destination exists, clear it or back it up (here we clear it to be fresh)
if [ -d "$DESTINATION_PATH" ]; then
    echo "Removing existing destination folder to avoid conflicts..."
    rm -rf "$DESTINATION_PATH"
fi

mkdir -p "$DESTINATION_PATH"

# Move the CONTENTS of the downloaded folder to the destination
# This removes the "double layer" (Station_Pi/Station_Pi)
if [ -d "$TEMP_DIR/$TARGET_FOLDER" ]; then
    cp -r "$TEMP_DIR/$TARGET_FOLDER/"* "$DESTINATION_PATH/"
    echo "Files moved successfully."
else
    echo "Error: Could not find folder '$TARGET_FOLDER' in the repository."
    ls -R "$TEMP_DIR"
fi

# 6. Cleanup
rm -rf "$TEMP_DIR"

echo "--- Done! ---"
echo "Your files are now located in: $DESTINATION_PATH"
echo "You can check them with: ls -l $DESTINATION_PATH"
