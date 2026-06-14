import os

def search():
    workspace = r"c:\Users\Ayush Khandwe\Desktop\New folder"
    terms = ["tumkur", "mundra"]
    found = False
    for root, dirs, files in os.walk(workspace):
        if "node_modules" in root or ".next" in root or ".git" in root or "__pycache__" in root or ".pytest_cache" in root:
            continue
        for file in files:
            if file.endswith(('.py', '.ts', '.tsx', '.json', '.js', '.mjs')):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            for term in terms:
                                if term in line.lower() and "search_dynamic_dbs.py" not in path:
                                    print(f"Found '{term}' in {path}:{line_num} -> {line.strip()}")
                                    found = True
                except Exception as e:
                    pass
    if not found:
        print("No hardcoded references to 'tumkur' or 'mundra' found.")

if __name__ == "__main__":
    search()
