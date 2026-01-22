import os
import shutil

# Set your source (root) directory and target directory here
SOURCE_DIR = r"C:\Users\kvcn639\OneDrive - AZCollaboration\Desktop\structure"
TARGET_DIR = r"C:\Users\kvcn639\OneDrive - AZCollaboration\Desktop\all_files_flat"

os.makedirs(TARGET_DIR, exist_ok=True)

for root, dirs, files in os.walk(SOURCE_DIR):
    for file in files:
        src_path = os.path.join(root, file)
        dst_path = os.path.join(TARGET_DIR, file)
        # If file with same name exists, add a suffix to avoid overwrite
        if os.path.exists(dst_path):
            base, ext = os.path.splitext(file)
            i = 1
            while True:
                new_name = f"{base}_{i}{ext}"
                new_dst_path = os.path.join(TARGET_DIR, new_name)
                if not os.path.exists(new_dst_path):
                    dst_path = new_dst_path
                    break
                i += 1
        shutil.move(src_path, dst_path)

print(f"All files moved to {TARGET_DIR}")