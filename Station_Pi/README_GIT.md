# Station Pi Setup & Update Instructions

This document explains how to synchronize your local code with the GitHub repository.

## 1. Quick Update (Pull) to Get Latest Code

To update the code to the latest version from GitHub, simply run the setup script again. It is designed to safely pull the latest changes.

Open a terminal and run:
```bash
~/Desktop/git_setup_station_pi.sh
```

## 2. Project Structure

After updating, your project files will be located here:

- **Folder**: `~/Desktop/Station_Pi/`
- **Main App**: `station_lora.py`

To run the application:
```bash
cd ~/Desktop/Station_Pi/
python3 station_lora.py
```

## 3. How to Push Changes (Upload)

If you have made edits to the code and want to save them to GitHub (so others can use them), use the push script.

1.  Run the update script:
    ```bash
    ~/Desktop/git_push_update.sh
    ```

2.  **Authentication**:
    When asked for credentials, enter:
    -   **Username**: Your GitHub username.
    -   **Password**: Your **Personal Access Token** (PAT).
    
    > **Important:** Your normal GitHub password will **not** work. You must use the token starting with `ghp_...`.

### About the Token
-   **Can I reuse it?** Yes! This single token works for **all** your repositories (Station Pi, Cabin Pi, etc.), for both pushing and pulling.
-   **Save it!** You cannot see the token again on GitHub after creating it. Save it in a secure text file or password manager.
