import os
import glob
import time

def find_files():
    workspace = r"c:\Users\Ayush Khandwe\Desktop\New folder"
    print("Listing files sorted by modification time:")
    all_files = []
    for root, dirs, files in os.walk(workspace):
        if "node_modules" in root or ".next" in root or ".git" in root or "__pycache__" in root or ".pytest_cache" in root:
            continue
        for file in files:
            path = os.path.join(root, file)
            mtime = os.path.getmtime(path)
            all_files.append((mtime, path))
    
    all_files.sort(reverse=True)
    for mtime, path in all_files[:25]:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))} - {path}")

if __name__ == "__main__":
    find_files()
