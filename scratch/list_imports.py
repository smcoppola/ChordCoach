import os
import re
import ast

def get_imports(directory):
    imports = set()
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    try:
                        tree = ast.parse(f.read())
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for n in node.names:
                                    imports.add(n.name.split('.')[0])
                            elif isinstance(node, ast.ImportFrom):
                                if node.module:
                                    imports.add(node.module.split('.')[0])
                    except Exception as e:
                        print(f"Error parsing {path}: {e}")
    return imports

src_dir = r'c:\Users\scopp\OneDrive\Documents\repos\ChordCoach-Companion\src'
all_imports = get_imports(src_dir)

# Exclude internal modules (logic, core, hardware, etc.)
internal = {'logic', 'core', 'hardware', 'ui'}
external_imports = all_imports - internal

print("Detected external imports:")
for imp in sorted(external_imports):
    print(f"- {imp}")
