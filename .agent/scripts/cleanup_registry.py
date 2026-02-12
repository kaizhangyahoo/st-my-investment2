import subprocess
import json
import sys

REPO = "us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app"
KEEP_COUNT = 2

def list_images():
    """List images in the repository sorted by update time (descending)."""
    cmd = [
        "gcloud", "artifacts", "docker", "images", "list",
        REPO, "--format=json", "--sort-by=~UPDATE_TIME"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error listing images: {result.stderr}")
        sys.exit(1)
    return json.loads(result.stdout)

def delete_image(digest):
    """Delete a specific image digest."""
    full_image_path = f"{REPO}@{digest}"
    print(f"Deleting {full_image_path}...")
    cmd = [
        "gcloud", "artifacts", "docker", "images", "delete",
        full_image_path, "--quiet", "--delete-tags"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error deleting image: {result.stderr}")

def main():
    print("Fetching images...")
    images = list_images()
    
    if len(images) <= KEEP_COUNT:
        print(f"Only {len(images)} images found. Keeping all (Policy: Keep last {KEEP_COUNT}).")
        return

    # Images are already sorted by UPDATE_TIME descending (newest first)
    images_to_delete = images[KEEP_COUNT:]
    print(f"Found {len(images)} images. Deleting {len(images_to_delete)} old images...")

    for img in images_to_delete:
         # Getting the digest is more reliable than tags for deletion
        digest = img.get('version', '')
        if digest:
            delete_image(digest)

if __name__ == "__main__":
    main()
