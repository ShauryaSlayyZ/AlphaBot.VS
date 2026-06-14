import os

def search():
    workspace = r"c:\Users\Ayush Khandwe\Desktop\New folder"
    for root, dirs, files in os.walk(workspace):
        if "node_modules" in root or ".next" in root or ".git" in root or "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(('.py', '.ts', '.tsx', '.json', '.js', '.mjs')):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "metricName" in content:
                            print(f"Found in {path}")
                except Exception as e:
                    pass

if __name__ == "__main__":
    search()
