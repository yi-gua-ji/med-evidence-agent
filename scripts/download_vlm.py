import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", r"D:\hf-cache")
from huggingface_hub import snapshot_download
path = snapshot_download("Qwen/Qwen2-VL-2B-Instruct", local_dir=r"D:\hf-cache\qwen2-vl-2b")
print("downloaded:", path)