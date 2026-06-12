import requests
import time
import sys
import os
import subprocess
import glob
import json
import re

# ==============================================================================
# PIPELINE CONFIGURATION CENTER
# ==============================================================================
CONFIG = {
    # Executable Path Components
    "JAR_PATH": r"/Users/sushreepradhan/Projects/HP/AAVA/code-indexer/code-indexer-1.0.0.jar",
    
    
    # Network Service API Routing
    "INDEXER_BASE_URL": "http://localhost:8080",
    "BASE_URL": "http://localhost:8080",
    "ENDPOINT": "/api/index/progress?executionId=",
    "REQUEST_TIMEOUT": 30,
    "AAVA_API_KEY": "",
    "HEADERS": {
        "Content-Type": "application/json"
    },
    
    # Repository Meta Targeting Coordinates
    "REPO_OWNER": "NavneetBN47",
    "REPO_NAME": "MobileApps",
    "REPO_BRANCH": "feature_sushree",
    
    # Execution Parameter Context Blocks
    "USER_PRINCIPAL": "anushree.s",
    "INDEX_SOURCE_STRATEGY": "local",
    "INDEX_DESTINATION_STRATEGY": "local",
    "TARGET_REPO_LOCAL_PATH": r"/Users/sushreepradhan/Projects/HP/AAVA/MobileApps-feature_sushree",
    
    
    # Behavioral Engine Evaluation Flags
    "USE_CLONE_STRATEGY": False,
    "REQUIRE_PURPOSE_EXTRACTION": True,
    "REQUIRE_CHUNK_SUMMARIES": True
}
# ==============================================================================


def start_indexer_jar(jar_path: str):
    print(f"Starting Java Indexer Application: {jar_path}")
    if not os.path.exists(jar_path):
        print(f"❌ Error: JAR file not found at {jar_path}")
        sys.exit(1)
        
    log_file = open("indexer_execution.log", "w")
    command = ["java", "-jar", jar_path]
    process = subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    
    # Wait for the server to be ready
    print("Waiting for Indexer API to become available on port 8080... (Check indexer_execution.log for startup logs)")
    check_url = f"{CONFIG['INDEXER_BASE_URL']}/api/index/progress?owner={CONFIG['REPO_OWNER']}&repo={CONFIG['REPO_NAME']}&branch={CONFIG['REPO_BRANCH']}"
    for _ in range(60): # wait up to 120 seconds
        try:
            # We just need any response to know the server is up
            requests.get(check_url, timeout=2)
            print("✅ Indexer API is ready!")
            return process, log_file
        except requests.exceptions.ConnectionError:
            if process.poll() is not None:
                print("❌ Java process died unexpectedly during startup. Check indexer_execution.log.")
                sys.exit(1)
            time.sleep(2)
            
    print("❌ Timeout waiting for Indexer API to start.")
    process.terminate()
    log_file.close()
    sys.exit(1)

def trigger_indexer():
    url = f"{CONFIG['INDEXER_BASE_URL']}/api/index"
    
    payload = {
        "owner": CONFIG["REPO_OWNER"],
        "repo": CONFIG["REPO_NAME"],
        "branch": CONFIG["REPO_BRANCH"],
        "userPrincipal": CONFIG["USER_PRINCIPAL"],
        "source": CONFIG["INDEX_SOURCE_STRATEGY"],
        "destination": CONFIG["INDEX_DESTINATION_STRATEGY"],
        "repoPath": CONFIG["TARGET_REPO_LOCAL_PATH"],
        "useClone": CONFIG["USE_CLONE_STRATEGY"],
        "isPurposeRequired": CONFIG["REQUIRE_PURPOSE_EXTRACTION"],
        "isChunkSummaryRequired": CONFIG["REQUIRE_CHUNK_SUMMARIES"]
    }
    
    print(f"\nTriggering Indexer via POST request to {url}...")
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("✅ Indexer successfully triggered.")
    except Exception as e:
        print(f"❌ Failed to trigger indexer: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Response: {response.text}")
        sys.exit(1)

def poll_indexer():
    url = f"{CONFIG['INDEXER_BASE_URL']}/api/index/progress?owner={CONFIG['REPO_OWNER']}&repo={CONFIG['REPO_NAME']}&branch={CONFIG['REPO_BRANCH']}"
    
    print(f"\nPolling indexer progress at {url}...")
    while True:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            state = data.get("state")
            current_step = data.get("currentStep")
            total_steps = data.get("totalSteps")
            step_name = data.get("currentStepName")
            percent = data.get("percentComplete")
            
            print(f"Status: {state} | Step: {current_step}/{total_steps} ({step_name}) | Progress: {percent}%")
            
            if state == "COMPLETED":
                print("\n✅ SUCCESS: Indexer is done!")
                break
            elif state in ["FAILED", "ERROR", "ABORTED"]:
                print(f"\n❌ ERROR: Indexer stopped with state {state}! Message: {data.get('errorMessage')}")
                break
                
        except Exception as e:
            print(f"⚠️ Error polling indexer: {e}")
            
        time.sleep(5)

def process_and_build_trees():
    # Path to where the indexer creates shards
    base_dir = os.path.dirname(os.path.abspath(__file__))
    shards_dir = os.path.join(base_dir, ".code_index", "shards")
    print(f"\nProcessing shards from: {shards_dir}")
    shard_files = glob.glob(os.path.join(shards_dir, "*.json"))
    print(f"Found {len(shard_files)} shard files.")
    
    cleaned_grouped_by_file = {}
    uncleaned_grouped_by_folder = {}
    
    # 1. Parse shards
    for shard_file in shard_files:
        try:
            with open(shard_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for chunk in data:
                file_path = chunk.get("filePath", "")
                if not file_path:
                    continue
                    
                file_path = file_path.replace("\\", "/")
                parent_folder = os.path.dirname(file_path)
                
                # Uncleaned
                uncleaned_chunk = chunk.copy()
                if parent_folder not in uncleaned_grouped_by_folder:
                    uncleaned_grouped_by_folder[parent_folder] = {}
                if file_path not in uncleaned_grouped_by_folder[parent_folder]:
                    uncleaned_grouped_by_folder[parent_folder][file_path] = []
                uncleaned_grouped_by_folder[parent_folder][file_path].append(uncleaned_chunk)
                
                # Cleaned (Remove calledBy and importedBy)
                cleaned_chunk = chunk.copy()
                
                def _clean_dict(d):
                    if isinstance(d, dict):
                        d.pop('calledBy', None)
                        d.pop('importedBy', None)
                        d.pop('calledby', None)
                        d.pop('importedby', None)
                        for k, v in list(d.items()):
                            if isinstance(v, (dict, list)):
                                _clean_dict(v)
                    elif isinstance(d, list):
                        for item in d:
                            if isinstance(item, (dict, list)):
                                _clean_dict(item)
                
                _clean_dict(cleaned_chunk)
                
                if file_path not in cleaned_grouped_by_file:
                    cleaned_grouped_by_file[file_path] = []
                cleaned_grouped_by_file[file_path].append(cleaned_chunk)
                
        except Exception as e:
            print(f"Error processing {shard_file}: {e}")
            
    # Save cleaned/uncleaned JSONs
    with open("cleaned_shards_grouped_by_file.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_grouped_by_file, f, indent=4)
    with open("uncleaned_shards_grouped_by_folder.json", "w", encoding="utf-8") as f:
        json.dump(uncleaned_grouped_by_folder, f, indent=4)
        
    print("Saved cleaned_shards_grouped_by_file.json and uncleaned_shards_grouped_by_folder.json")
    
    # 2. Build Directory Tree
    directory_tree = {}
    for folder, files in uncleaned_grouped_by_folder.items():
        for file_path in files.keys():
            parts = file_path.split("/")
            current_level = directory_tree
            for i, part in enumerate(parts):
                if not part: continue
                if i == len(parts) - 1:
                    current_level[part] = "file"
                else:
                    if part not in current_level or current_level[part] == "file":
                        current_level[part] = {}
                    current_level = current_level[part]
                    
    # 3. Build Dependency Graph
    all_known_paths = set()
    for folder, files in uncleaned_grouped_by_folder.items():
        all_known_paths.update(files.keys())
        
    def resolve_import_path(imp_str):
        # We need to find if this module string matches any of our known file paths.
        # e.g., 'MobileApps.libs.flows.windows.hpx_rebranding.flow_container'
        # will become 'MobileApps/libs/flows/windows/hpx_rebranding/flow_container'
        imp_path = imp_str.replace(".", "/")
        
        parts = imp_path.split("/")
        if len(parts) > 1 and parts[0] == CONFIG["REPO_NAME"]:
            match_path = "/".join(parts[1:])
        else:
            match_path = imp_path
             
        for kp in all_known_paths:
            if kp.endswith("/" + match_path + ".py") or kp.endswith("/" + match_path) or kp == match_path + ".py":
                return kp
        return None

    dependency_graph = {
        "forward_dependencies": {},
        "reverse_dependencies": {}
    }
    
    for p in all_known_paths:
        dependency_graph["forward_dependencies"][p] = []
        dependency_graph["reverse_dependencies"][p] = []
        
    for folder, files in uncleaned_grouped_by_folder.items():
        for file_path, chunks in files.items():
            forward_deps = set()
            for chunk in chunks:
                deps = chunk.get("dependencies", {})
                imports = deps.get("imports", []) + chunk.get("imports", [])
                
                for imp_block in imports:
                    if not isinstance(imp_block, str): continue
                    # imp_block might be a multiline string with 'import X' or 'from Y import Z'
                    for line in imp_block.split("\n"):
                        line = line.strip()
                        module_name = None
                        if line.startswith("import "):
                            parts = line.split(" ")
                            if len(parts) > 1:
                                module_name = parts[1].split(",")[0].strip() # Handle 'import a, b' loosely by just taking a
                        elif line.startswith("from "):
                            parts = line.split(" ")
                            if len(parts) > 1:
                                module_name = parts[1].strip()
                                
                        if module_name:
                            resolved = resolve_import_path(module_name)
                            if resolved and resolved != file_path:
                                forward_deps.add(resolved)
                        
            dependency_graph["forward_dependencies"][file_path] = sorted(list(forward_deps))
            
            for dep in forward_deps:
                if dep in dependency_graph["reverse_dependencies"]:
                    dependency_graph["reverse_dependencies"][dep].append(file_path)
                    
    for p in dependency_graph["reverse_dependencies"]:
        dependency_graph["reverse_dependencies"][p] = sorted(list(set(dependency_graph["reverse_dependencies"][p])))
        
    docs_dir = os.path.join(os.getcwd(), "Docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    with open(os.path.join(docs_dir, "directory_tree.json"), "w", encoding="utf-8") as f:
        json.dump(directory_tree, f, indent=4)
    with open(os.path.join(docs_dir, "dependency_graph.json"), "w", encoding="utf-8") as f:
        json.dump(dependency_graph, f, indent=4)
        
    print("SUCCESS: Built and saved directory_tree.json and dependency_graph.json in Docs/")


if __name__ == "__main__":
    print("-" * 40)
    print("Starting Indexing Automation")
    print("-" * 40)
    
    process, log_file = start_indexer_jar(CONFIG["JAR_PATH"])
    
    try:
        trigger_indexer()
        poll_indexer()
        print("\nStarting post-processing (Shards parsing & Tree building)...")
        process_and_build_trees()
    finally:
        print("\nCleaning up Java process...")
        process.terminate()
        log_file.close()
        print("-" * 40)
