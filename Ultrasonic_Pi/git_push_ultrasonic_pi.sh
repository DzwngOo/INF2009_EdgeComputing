#!/bin/bash

# Configuration
REPO_URL="https://github.com/DzwngOo/INF2009_EdgeComputing.git"
BRANCH="LoRa"
REPO_SUBFOLDER="Ultrasonic_Pi"
# Use the directory where the script is located as the source folder (which is now Ultrasonic_Pi)
LOCAL_SOURCE_FOLDER="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# We need a temp directory OUTSIDE the current folder to avoid recursion when copying
TEMP_REPO_DIR="/home/ultrasonicpi/Desktop/Git_Update_Stage_Ultrasonic"

echo "--- Starting Full Ultrasonic_Pi Push Process ---"

# 1. Setup Staging Area (Clone the repo)
if [ -d "$TEMP_REPO_DIR" ]; then
    echo "Cleaning up old staging area..."
    rm -rf "$TEMP_REPO_DIR"
fi

echo "Cloning repository branch $BRANCH..."
# Clone into the temp directory
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TEMP_REPO_DIR"

if [ ! -d "$TEMP_REPO_DIR" ]; then
    echo "ERROR: Clone failed. Please check your internet connection or credentials."
    exit 1
fi

DESTINATION="$TEMP_REPO_DIR/$REPO_SUBFOLDER"

# 2. Sync Files
# Ensure destination folder exists in the repo
mkdir -p "$DESTINATION"

echo "Syncing all files from $LOCAL_SOURCE_FOLDER to $DESTINATION..."

# Copy contents of local folder (Ultrasonic_Pi) to the repo's subfolder
# We exclude the .git folder if it exists locally to avoid nested repo issues
rsync -av --progress --exclude='.git' --exclude='__pycache__' --exclude='.pio' --exclude='.vscode' "$LOCAL_SOURCE_FOLDER/" "$DESTINATION/"

# 3. Commit and Push
cd "$TEMP_REPO_DIR"

# Configure Git Identity for this transaction
git config user.email "ultrasonicpi-update@local"
git config user.name "Ultrasonic Pi User"

# Fix for VS Code Terminal Auth Issue
unset GIT_ASKPASS
unset SSH_ASKPASS

echo "Checking for changes..."
git add .
status=$(git status --porcelain)

if [ -z "$status" ]; then
    echo "No changes detected to push."
else
    echo "Changes detected:"
    echo "$status"
    
    echo "Committing..."
    git commit -m "Update Ultrasonic_Pi folder with latest local code"
    
    echo "--------------------------------------------------------"
    echo "ATTENTION: You are about to push to GitHub."
    echo "IMPORTANT: When asked for 'Password', use a PERSONAL ACCESS TOKEN (starts with ghp_...)."
    echo "Do NOT use your GitHub login password."
    echo "--------------------------------------------------------"
    
    if git push origin "$BRANCH"; then
        echo "Push successful!"
    else
        echo "Push failed. Check your password/token."
    fi
fi

# 4. Cleanup
cd ..
rm -rf "$TEMP_REPO_DIR"
echo "--- Cleanup Done! ---"
