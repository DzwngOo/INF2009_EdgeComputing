#!/bin/bash
# 1. Initialize Git Repo in the main folder ONE level above where you want the files to appear
# In this case: The Desktop itself will be the git root
cd ~/Desktop

if [ ! -d ".git" ]; then
    git init
    # Configure safety to not track other desktop items
    echo "*" > .gitignore
    echo "!Ultrasonic_Pi/" >> .gitignore
    
    git remote add origin https://github.com/DzwngOo/INF2009_EdgeComputing.git
fi

# 2. Configure Sparse Checkout (Only get the Ultrasonic_Pi folder)
git config core.sparseCheckout true
echo "Ultrasonic_Pi/" > .git/info/sparse-checkout

# 3. Pull from LoRa 
echo "Pulling updates..."
git pull origin LoRa

echo "--------------------------------------------------------"
echo "Success! Your files are now at: ~/Desktop/Ultrasonic_Pi/"
echo "No double folder layer."
echo "--------------------------------------------------------"
