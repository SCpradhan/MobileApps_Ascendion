import io
import os
import json
import zipfile
import re
import shutil
import time
import requests
import urllib3
from typing import Tuple, List, Dict, Any
from datetime import datetime
from collections import defaultdict
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
# from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import InsecureRequestWarning



# Disable SSL warnings for internal network APIs
urllib3.disable_warnings(InsecureRequestWarning)

# ==============================================================================
# USER CONFIGURATION CENTER (FROM INDEXER.PY)
# ==============================================================================
CONFIG = {
    "GITHUB_BASE_URL": "https://github.com",
    "REPO_OWNER": "NavneetBN47",
    "REPO_NAME": "MobileApps",
    "BRANCH_NAME": "feature_sushree",
    
    # Root Target Directory for the organized split index outputs
    # "INDEX_ROOT_DIR": r"C:\New folder\Delivery Infusion\HP\Java\New8Index",
    # "LOG_FILEPATH": r"C:\New folder\Delivery Infusion\HP\Java\New8Index\indexer_run.log",
    "INDEX_ROOT_DIR": "/Users/sushreepradhan/Projects/HP/AAVA/MobileApps/tests/windows/hpx_rebranding/Framework/bell_notifications/index_outputs/generated_index",
    "LOG_FILEPATH": "/Users/sushreepradhan/Projects/HP/AAVA/MobileApps/tests/windows/hpx_rebranding/Framework/bell_notifications/index_outputs/generated_index/indexer_run.log",
    
    "TARGET_EXTENSIONS": [".py", ".json"],
    
    # Platform Authentication (Inherited for KB Creation Process)
    "AAVA_USERNAME": "sushree.pradhan@ascendion.com",
    #"AAVA_API_KEY": os.environ.get("AAVA_API_KEY", ""),
    "AAVA_API_KEY": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJTdXNocmVlIFByYWRoYW4iLCJpYXQiOjE3ODA5ODU5OTAsImV4cCI6MTc4MTA0OTU5OSwiYXBwaWQiOiIyNzFiOTk1NC0wMTE2LTQyNDktOTExOC03MjhmMTViOTRjZjciLCJ1bmlxdWVfbmFtZSI6InN1c2hyZWUucHJhZGhhbkBhc2NlbmRpb24uY29tIiwiZG9tYWluIjoiaW50LWFpLmFhdmEuYWkiLCJ1c2VyRGV0YWlscyI6IlRqaUgxRmJpYUtoOVdjRW5YTmk1Z2YrYm1pK0txbTY1YVIxT0ZXS0ZjcGlDQ2Y4YkJFYTBwUk1hR2RSVGxGVzJDWGZtYlF4QXFPOWFUS0wxR0t3aDN0V1hLdUlTSGdHTzEydFkxbGRaNmROU2ZHaVRtM0w0eTBNVDUrWVZSd3ZMR3JCR3E3WW9penpmajhudkp2amtpclUvZXNtNTFmOHl4Q2ROWVRSMy95QkUyR0tkNUw0eE5JUWNjR040Q2ZlbGVjQ2l1eFVLam1yV09YNWk1dTNwNWVNWnduVUdsZEFXVGlUOWZEc3E4bUdMQTRPUzUrZzJLUGlqOE9WdTFacE1QSCtuNThSQ1RCMFhLc0d1M1hEalBPNVFWSlJ2U3NVWmpwN0VqRTBmMjBNSWpFTXltNUdkVnJXVEhLell5RzdIMUJISGhVVVFIZm4ya2ZFS2srM1NqOGQ1NDdmVUlPQU41OUswVU0ya0pTYz0ifQ.BMLLPeGCNmydtDhnZE_a2NojvMVR3trblujSSks9espkfJGn_hfSAaGZ999J8oL7Vt-w72CLUGFsUdEIDIYIU0RJbcef9a1YvvnRJ5KsPYZf_phV7TDPKFuHObhEg-ApsOsBasmpNjDzCo_KHgNQs4AwrzaqBzDlAlIk4A2q6X-XgQpZZOjQpPnfbTeZZMzd6TYPrnTw7HHXAqomKGaa4fYqpa1VXmbco9gTtdS224aLfun3T3GF7blnp-bbPdotQd6309ICrYRZKVIpLG-ai-i9jsIeswryAGCWvRApWXVaQ1rBxnLgwpXqNCkvUUpdp00t9JMEp_LmS0TEnO-A2A",
    "AAVA_API_BASE": "https://int-ai.aava.ai",
    "BATCH_SIZE": 1
}
# ==============================================================================

# Initialize Tree-sitter Parser natively
PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)


def log_and_print(message, log_file=None):
    """Prints to console and synchronously writes to the configured log file."""
    print(message)
    if log_file:
        try:
            log_file.write(message + "\n")
            log_file.flush()
        except Exception:
            pass


def get_file_extension(filename):
    """Safely extracts file extensions or returns a fallback grouping name."""
    basename = os.path.basename(filename)
    if basename.startswith(".") and bytes(basename, "utf-8").count(b".") == 1:
        return "Hidden System Config (e.g., .gitignore)"
    ext = os.path.splitext(filename)[1].lower()
    return ext if ext else "No Extension"


def download_github_repo(base_url, owner, repo, branch, log_file, skipped_tracker, target_extensions):
    """Downloads the repository as a zip archive from GitHub and streams file content matching configured extensions."""
    clean_base = base_url.rstrip("/")
    download_url = f"{clean_base}/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    
    log_and_print(f"Fetching repository archive from: {download_url}...", log_file)
    response = requests.get(download_url)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch repository. Status code: {response.status_code}.")
        
    extensions_set = {ext.strip().lower() for ext in target_extensions}
        
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        file_list = archive.infolist()
        log_and_print(f"Archive opened successfully. Found {len(file_list)} total structural entries inside zip.", log_file)
        
        for file_info in file_list:
            path_parts = file_info.filename.split("/", 1)
            relative_path = path_parts[1] if len(path_parts) > 1 else file_info.filename
            
            if file_info.is_dir():
                skipped_tracker.append({
                    "path": relative_path,
                    "extension": "Directory / Folder"
                })
                continue
                
            file_ext = get_file_extension(relative_path)
            if file_ext not in extensions_set:
                skipped_tracker.append({
                    "path": relative_path,
                    "extension": file_ext
                })
                continue
            
            with archive.open(file_info) as file:
                try:
                    content = file.read()
                    yield relative_path, content
                except Exception as e:
                    log_and_print(f"Skipping {relative_path} due to error.", log_file)
                    skipped_tracker.append({
                        "path": relative_path,
                        "extension": file_ext
                    })


def resolve_import_to_path(module_name, all_paths):
    """Translates dot-notated Python import strings into real matched relative paths."""
    if not module_name:
        return None
        
    module_name = module_name.strip()
    parts = module_name.split(".")
    
    while len(parts) > 0:
        potential_base = "/".join(parts)
        variations = [f"{potential_base}.py", f"{potential_base}/__init__.py"]
        
        for var in variations:
            if var in all_paths:
                return var
                
        for path in all_paths:
            if path.startswith(potential_base + "/"):
                return path
                
        parts.pop(0)
            
    return None


def extract_parameters_and_returns(node, source_bytes):
    """Extracts input arguments and maps out potential return values/expressions from a function definition."""
    input_params = []
    output_returns = []
    
    parameters_node = None
    for child in node.children:
        if child.type == "parameters":
            parameters_node = child
            break
            
    if parameters_node:
        for param in parameters_node.children:
            if param.type in ["identifier", "dictionary_splat_pattern", "list_splat_pattern", "typed_parameter", "default_parameter"]:
                param_text = source_bytes[param.start_byte:param.end_byte].decode("utf-8", errors="ignore").strip()
                if param_text and param_text not in ["(", ")", ","]:
                    input_params.append(param_text)

    sub_stack = [node]
    while sub_stack:
        curr = sub_stack.pop()
        if curr.type == "return_statement":
            if len(curr.children) > 1:
                ret_val = source_bytes[curr.children[1].start_byte:curr.children[1].end_byte].decode("utf-8", errors="ignore").strip()
                if ret_val:
                    output_returns.append(ret_val)
            else:
                output_returns.append("None")
        else:
            for child in reversed(curr.children):
                sub_stack.append(child)
                
    return input_params, sorted(list(set(output_returns)))


def extract_semantic_and_relations(source_bytes, all_paths):
    """Parses file bytes to retrieve structural symbols, imports, and interface parameters."""
    tree = parser.parse(source_bytes)
    
    extracted_features = []
    dependencies = set()
    processed_node_ids = set()
    
    class_name_regex = re.compile(r"class\s+([a-zA-Z0-9_]+)")
    func_name_regex = re.compile(r"def\s+([a-zA-Z0-9_]+)")
    
    source_lines = source_bytes.decode("utf-8", errors="ignore").splitlines()
    
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        
        for child in reversed(node.children):
            stack.append(child)
            
        node_type = str(node.type)
        current_decorators = []
        target_node = None
        
        if node_type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    dec_text = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
                    if dec_text:
                        current_decorators.append(dec_text)
                elif child.type in ["class_definition", "function_definition"]:
                    target_node = child
                    processed_node_ids.add(id(child))
                    break
            
            if target_node:
                node_type = str(target_node.type)
        
        elif node_type in ["class_definition", "function_definition"]:
            if id(node) in processed_node_ids:
                continue
            target_node = node

        if node_type == "class_definition" and target_node:
            node_text = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8", errors="ignore").strip()
            match = class_name_regex.search(node_text)
            name = match.group(1) if match else "anonymous_class"
            
            start_idx = target_node.start_point[0]
            end_idx = target_node.end_point[0] + 1
            body_content = "\n".join(source_lines[start_idx:end_idx])
            
            extracted_features.append({
                "type": "class",
                "name": name,
                "start_line": start_idx + 1,
                "end_line": end_idx,
                "annotations": current_decorators,
                "content": body_content
            })
            
        elif node_type == "function_definition" and target_node:
            node_text = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8", errors="ignore").strip()
            match = func_name_regex.search(node_text)
            name = match.group(1) if match else "anonymous_function"
            
            start_idx = target_node.start_point[0]
            end_idx = target_node.end_point[0] + 1
            body_content = "\n".join(source_lines[start_idx:end_idx])
            
            input_params, output_returns = extract_parameters_and_returns(target_node, source_bytes)
            
            extracted_features.append({
                "type": "function",
                "name": name,
                "start_line": start_idx + 1,
                "end_line": end_idx,
                "input_parameters": input_params,
                "output_parameters": output_returns,
                "annotations": current_decorators,
                "content": body_content
            })
            
        elif node_type in ["import_statement", "import_from_statement"]:
            # Robust extraction matching cross-version tree-sitter setups
            node_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            if node_type == "import_statement":
                clean_line = node_text.replace("import ", "", 1)
                sub_imports = [imp.split(" as ")[0].strip() for imp in clean_line.split(",")]
                for imp in sub_imports:
                    resolved = resolve_import_to_path(imp, all_paths)
                    if resolved:
                        dependencies.add(resolved)
            elif node_type == "import_from_statement":
                if node_text.startswith("from "):
                    parts = node_text[5:].split(" import ")
                    if len(parts) > 0:
                        base_module = parts[0].strip()
                        resolved = resolve_import_to_path(base_module, all_paths)
                        if resolved:
                            dependencies.add(resolved)
                        
    return extracted_features, sorted(list(dependencies))


def attach_to_tree(tree_root, path_parts, files_list, local_index_rel_path):
    """Helper method to recursively build a nested dictionary tree of paths."""
    current = tree_root
    for part in path_parts:
        if not part:
            continue
        if part not in current:
            current[part] = {}
        current = current[part]
    
    current["_files"] = sorted([os.path.basename(f) for f in files_list])
    current["_sub_index"] = local_index_rel_path.replace("\\", "/")


def build_repo_index():
    """Orchestrates indexing pipeline operations and structural tree split exports."""
    index_root = CONFIG["INDEX_ROOT_DIR"]
    log_path = CONFIG["LOG_FILEPATH"]
    
    if os.path.exists(index_root):
        print(f"Target index folder detected at: {index_root}. Cleaning stale directory contents...")
        try:
            shutil.rmtree(index_root)
            print("Cleanup successful. Starting fresh pipeline tracking.")
        except Exception as cleanup_error:
            print(f"Warning: Failed to completely clean index target directory: {cleanup_error}")
            
    os.makedirs(index_root, exist_ok=True)
    
    dirname = os.path.dirname(log_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    skipped_files = []
    processed_stats = defaultdict(int)
    
    folder_buckets = defaultdict(dict)
    master_index = {}
    collective_index = {}
    directory_tree_root = {}
    
    forward_deps_map = {}
    reverse_deps_map = defaultdict(list)
            
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_and_print("Starting Segmented AST Folder-Level Index Pipeline...", log_file)
        
        raw_repo_data = {}
        for file_path, content_bytes in download_github_repo(
            CONFIG["GITHUB_BASE_URL"], CONFIG["REPO_OWNER"], CONFIG["REPO_NAME"], 
            CONFIG["BRANCH_NAME"], log_file, skipped_files, CONFIG["TARGET_EXTENSIONS"]
        ):
            raw_repo_data[file_path] = content_bytes
                
        all_tracked_paths = set(raw_repo_data.keys())
        log_and_print(f"\nTotal repository file entries matched for processing: {len(all_tracked_paths)}", log_file)
        
        for file_path, content_bytes in raw_repo_data.items():
            file_ext = get_file_extension(file_path)
            processed_stats[file_ext] += 1
            
            total_lines = len(content_bytes.split(b'\n'))
            full_file_content = content_bytes.decode("utf-8", errors="ignore")
            
            if file_path.endswith(".py"):
                definitions, depends_on = extract_semantic_and_relations(content_bytes, all_tracked_paths)
                cleaned_dependencies = [dep for dep in depends_on if dep != file_path]
            else:
                definitions = []
                cleaned_dependencies = []
            
            forward_deps_map[file_path] = cleaned_dependencies
            for dependency in cleaned_dependencies:
                reverse_deps_map[dependency].append(file_path)
            
            file_record = {
                "type": "file_node",
                "name": os.path.basename(file_path),
                "filepath": file_path,
                "start_line": 1,
                "end_line": total_lines,
                "depends_on": cleaned_dependencies,
                "definitions": definitions,
                "content": full_file_content
            }
            
            collective_index[file_path] = [file_record]
            
            sub_folder_context = os.path.dirname(file_path)
            folder_buckets[sub_folder_context][file_path] = [file_record]

        log_and_print("\nWriting segmented folder-level sub-index structures...", log_file)
        for folder_rel_path, files_dict in folder_buckets.items():
            
            target_sub_dir_name = folder_rel_path if folder_rel_path else "root"
            folder_name = os.path.basename(folder_rel_path) if folder_rel_path else "root"
            sub_index_filename = f"{folder_name}_index.json"
            
            physical_output_dir = os.path.join(index_root, target_sub_dir_name)
            os.makedirs(physical_output_dir, exist_ok=True)
                
            physical_sub_index_path = os.path.join(physical_output_dir, sub_index_filename)
            
            with open(physical_sub_index_path, "w", encoding="utf-8") as sub_file:
                json.dump(files_dict, sub_file, indent=4, ensure_ascii=False)
            
            local_index_rel = os.path.join(target_sub_dir_name, sub_index_filename)
            
            master_index[target_sub_dir_name] = {
                "local_sub_index_filepath": local_index_rel,
                "tracked_files_count": len(files_dict),
                "files_list": sorted(list(files_dict.keys()))
            }
            
            if folder_rel_path:
                split_parts = folder_rel_path.replace("\\", "/").split("/")
                attach_to_tree(directory_tree_root, split_parts, files_dict.keys(), local_index_rel)
            else:
                attach_to_tree(directory_tree_root, ["root"], files_dict.keys(), local_index_rel)
            
        master_index_path = os.path.join(index_root, "master_index.json")
        log_and_print(f"Writing master entry catalog manifest to: {master_index_path}", log_file)
        with open(master_index_path, "w", encoding="utf-8") as master_file:
            json.dump(master_index, master_file, indent=4, ensure_ascii=False)
            
        collective_index_path = os.path.join(index_root, "complete_codebase_index.json")
        log_and_print(f"Writing collective monolithic index file to: {collective_index_path}", log_file)
        with open(collective_index_path, "w", encoding="utf-8") as collective_file:
            json.dump(collective_index, collective_file, indent=4, ensure_ascii=False)
            
        tree_output_path = os.path.join(index_root, "directory_tree.json")
        log_and_print(f"Writing complete relational directory tree file to: {tree_output_path}", log_file)
        with open(tree_output_path, "w", encoding="utf-8") as tree_file:
            json.dump(directory_tree_root, tree_file, indent=4, ensure_ascii=False)
            
        dependency_tree_output = {
            "forward_dependencies": forward_deps_map,
            "reverse_dependencies": {k: sorted(v) for k, v in reverse_deps_map.items()}
        }
        dependency_tree_path = os.path.join(index_root, "dependency_tree.json")
        log_and_print(f"Writing complete directional dependency tree manifest to: {dependency_tree_path}", log_file)
        with open(dependency_tree_path, "w", encoding="utf-8") as dep_file:
            json.dump(dependency_tree_output, dep_file, indent=4, ensure_ascii=False)
            
        log_and_print("\nMulti-tier segmented directory and tree analysis completed successfully!", log_file)


# ==============================================================================
# PHASE 2 APPENDED LOGIC: KB CREATION INFRASTRUCTURE (FROM KB_CREATION.PY)
# ==============================================================================
GLOBAL_CONTEXT_TRACKER = {}

class PipelineLogger:
    """Handles writing standalone logs cleanly to console and the shared configuration log session file."""
    @staticmethod
    def write(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}"
        print(formatted_msg)
        try:
            with open(CONFIG["LOG_FILEPATH"], "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
        except Exception as e:
            print(f"[{timestamp}] Warning: Failed writing to log file: {e}")


class AavaKBPlatformClient:
    """Platform client dealing exclusively with metadata ingestion and KB approvals."""
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    HTTP_TIMEOUT = 60

    def __init__(self):
        self.username = CONFIG["AAVA_USERNAME"]
        self.api_key = CONFIG["AAVA_API_KEY"]
        self.base_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json, text/plain, */*",
            "X-Realm-Id": "118"
        }

    def _make_request(self, method: str, url: str, headers: dict = None, json_data: dict = None, files: list = None, data: dict = None):
        final_headers = self.base_headers.copy()
        if headers:
            final_headers.update(headers)
            
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.request(
                    method, url, headers=final_headers, json=json_data, files=files, data=data, 
                    verify=False, timeout=self.HTTP_TIMEOUT
                )
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1: time.sleep(self.RETRY_DELAY)
                else: raise

    def fetch_tenant_details(self) -> Tuple[str, str]:
        """Finds the Tenant Realm ID and Team ID automatically."""
        details_data = self._make_request('get', f"{CONFIG['AAVA_API_BASE']}/api/auth/user/details/v2", headers=self.base_headers).json() or {}
        realm_id = str((details_data.get("data") or {}).get("lastRealmId") or details_data.get("lastRealmId"))
        
        realms_data = self._make_request('get', f"{CONFIG['AAVA_API_BASE']}/api/auth/realms?limit=12", headers=self.base_headers).json() or {}
        realm_list = (realms_data.get("data") or {}).get("realmList") or []
        team_id = next((str(r.get("teamId")) for r in realm_list if isinstance(r, dict) and str(r.get("realmId")) == realm_id), None)
        return realm_id, team_id

    def upload_and_approve_kb(self, kb_name: str, batch_items: list, realm_id: str, team_id: str) -> str:
        """Uploads source code files into a unified Knowledge Base mapping collection."""
        active_headers = self.base_headers.copy()
        if realm_id: active_headers["X-Realm-Id"] = realm_id

        form_data = {
            "knowledgeBase": kb_name,
            "description": "Standalone Extraction Code Base Ingestion",
            "model-ref": "4",      
            "type": "normal",
            "splitSize": "2000",
            "practiceArea": "4",
            "teamId": team_id or "",
            "status": "CREATED",
            "goodAt": "2",
            "functionType": "Flat Files",
            "methodology": "Quick Search"
        }

        multipart_files = []
        for item in batch_items:
            mime_wrapper = "json" if item["source_path"].lower().endswith(".json") else "python"
            formatted_payload = f"```{mime_wrapper}\n{item['content']}\n```".encode("utf-8")
            multipart_files.append(("files", (f"{item['name']}.md", formatted_payload, "text/markdown")))

        kb_url = f"{CONFIG['AAVA_API_BASE']}/embedding/knowledge/v2"
        
        post_response = self._make_request('post', kb_url, headers=active_headers, files=multipart_files, data=form_data).json() or {}
        data_block = post_response.get("data") or {}
        kb_id = str(data_block.get("id") or data_block.get("kbDetail", {}).get("id"))

        self._make_request('put', f"{kb_url}/IN_REVIEW?collection_id={kb_id}", headers=active_headers, json_data={})
        self._make_request('put', f"{kb_url}/approval", headers=active_headers, json_data={
            "masterId": int(kb_id), "status": "APPROVED", "comment": "Auto-approved asset"
        })
        
        PipelineLogger.write(f" -> KB [{kb_name}] (ID: {kb_id}) approved. Waiting 10 seconds for chunking process...")
        time.sleep(10)
        
        return kb_id


def generate_batch_kb_name(folder_name: str, batch_index: int) -> str:
    """Format string structure securely complying with Aava storage schemas."""
    safe_folder = folder_name.lower()
    safe_folder = re.sub(r'[^a-z0-9_.-]', '_', safe_folder)
    
    if not safe_folder or not safe_folder[0].islower():
        safe_folder = "mod_" + safe_folder
        
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    kb_name = f"{safe_folder}_batch{batch_index}_rc_{timestamp}kb"
    return re.sub(r'_+', '_', kb_name)


def extract_sub_indexes(node: dict, gathered_sub_indexes: list):
    """Recursively parses the directory tree object topology to harvest all valid sub-indices."""
    if isinstance(node, dict):
        if "_sub_index" in node:
            gathered_sub_indexes.append(node["_sub_index"])
        for key, val in node.items():
            if key not in ["_files", "_sub_index"]:
                extract_sub_indexes(val, gathered_sub_indexes)


def attach_to_context_tree(context_root: dict, path_parts: list[str], raw_code_items: list):
    """Maps items into structured tree node locations specifically updating raw_code blocks."""
    current = context_root
    for part in path_parts:
        if not part: continue
        if part not in current: 
            current[part] = {}
        current = current[part]
        
    if "associated_context" not in current:
        current["associated_context"] = {"raw_code": [], "code_doc": []}
    if "file_purposes" not in current:
        current["file_purposes"] = {}
    if "generated_doc_filepath" not in current:
        current["generated_doc_filepath"] = None

    current["associated_context"]["raw_code"].extend(raw_code_items)


def save_incremental_context_tree(folder_rel_path: str, raw_code_items: list):
    """Updates context tree model and writes changes straight to the root folder of index root."""
    split_parts = folder_rel_path.replace("\\", "/").split("/") if folder_rel_path else ["root"]
    attach_to_context_tree(GLOBAL_CONTEXT_TRACKER, split_parts, raw_code_items)
    
    context_tree_output_path = os.path.join(CONFIG["INDEX_ROOT_DIR"], "context_tree.json")
    try:
        with open(context_tree_output_path, "w", encoding="utf-8") as context_file:
            json.dump(GLOBAL_CONTEXT_TRACKER, context_file, indent=4, ensure_ascii=False)
        PipelineLogger.write(f"   [Context Sync] Incremental context tree committed to disk: {context_tree_output_path}")
    except Exception as e:
        PipelineLogger.write(f"   [Context Sync Warning] Failed saving context manifest to disk: {e}")


def run_standalone_kb_ingestion():
    """Reads directory tree config paths, pushes KB uploads with explicit error handling, and maps context trees."""
    start_time = datetime.now()
    index_root = os.path.normpath(CONFIG["INDEX_ROOT_DIR"])
    PipelineLogger.write(f"\nLaunching Appended KB Creation Process Context. Ingesting from: {index_root}")
    
    tree_manifest_path = os.path.join(index_root, "directory_tree.json")
    if not os.path.exists(tree_manifest_path):
        PipelineLogger.write(f"Critical Ingestion Error: Missing master directory_tree.json inside path: {index_root}")
        return

    with open(tree_manifest_path, "r", encoding="utf-8") as f:
        directory_tree_root = json.load(f)

    sub_index_paths = []
    extract_sub_indexes(directory_tree_root, sub_index_paths)
    PipelineLogger.write(f"Resolved {len(sub_index_paths)} module folder scopes from directory tree mapping metadata.")

    # Initialize Platform Client Connections
    kb_client = AavaKBPlatformClient()
    realm_id, team_id = kb_client.fetch_tenant_details()
    PipelineLogger.write(f"Connection Verified: Realm ID [{realm_id}], Team ID [{team_id}]")

    GLOBAL_CONTEXT_TRACKER.clear()
    allowed_extensions = [ext.lower() for ext in CONFIG["TARGET_EXTENSIONS"]]
    total_kbs_uploaded = 0

    for sub_index_rel in sub_index_paths:
        absolute_sub_index_path = os.path.join(index_root, sub_index_rel)
        if not os.path.exists(absolute_sub_index_path):
            continue

        folder_rel_dir = os.path.dirname(sub_index_rel)
        folder_base_name = os.path.basename(folder_rel_dir) or "root"
        PipelineLogger.write(f"\nProcessing directory partition: {folder_rel_dir or 'root'}")

        with open(absolute_sub_index_path, "r", encoding="utf-8") as f:
            local_index_content = json.load(f) or {}

        extracted_items = []
        seen_files = set()

        for repo_file_path, records_list in local_index_content.items():
            normalized_path = os.path.normpath(repo_file_path)
            for record in (records_list or []):
                if record.get("type") == "file_node" and normalized_path not in seen_files:
                    _, file_extension = os.path.splitext(normalized_path.lower())
                    if file_extension in allowed_extensions:
                        full_content = record.get("content", "")
                        if full_content:
                            seen_files.add(normalized_path)
                            extracted_items.append({
                                "source_path": normalized_path,
                                "name": record["name"],
                                "content": full_content
                            })

        if not extracted_items:
            PipelineLogger.write(f" -> No matching {allowed_extensions} files found. Skipping folder node.")
            continue

        PipelineLogger.write(f" -> Discovered {len(extracted_items)} files. Preparing cluster upload & context tracking maps...")

        batch_size = CONFIG["BATCH_SIZE"]
        for batch_num, i in enumerate(range(0, len(extracted_items), batch_size), start=1):
            batch_slice = extracted_items[i:i + batch_size]
            cluster_kb_name = generate_batch_kb_name(folder_base_name, batch_num)
            
            PipelineLogger.write(f"   >> Processing Ingestion Batch #{batch_num} containing: {[item['name'] for item in batch_slice]}")
            batch_raw_code_metadata = []
            
            try:
                try:
                    # 1st attempt to create KB
                    kb_id = kb_client.upload_and_approve_kb(cluster_kb_name, batch_slice, realm_id, team_id)
                    total_kbs_uploaded += 1
                    PipelineLogger.write(f"   >> Ingestion complete for KB ID: {kb_id}")
                except Exception as first_attempt_err:
                    PipelineLogger.write(f"   >> [WARNING] 1st time KB API fail: {first_attempt_err}")
                    PipelineLogger.write("   >> Waiting for 1 minute before retrying...")
                    time.sleep(60)
                    
                    PipelineLogger.write("   >> Triggering the KB API 2nd time...")
                    # 2nd attempt to create KB
                    kb_id = kb_client.upload_and_approve_kb(cluster_kb_name, batch_slice, realm_id, team_id)
                    total_kbs_uploaded += 1
                    PipelineLogger.write(f"   >> Ingestion complete on 2nd attempt for KB ID: {kb_id}")

                for item in batch_slice:
                    batch_raw_code_metadata.append({
                        "file_identity": item["name"],
                        "source_system_path": item["source_path"].replace("\\", "/"),
                        "kb_id": kb_id,
                        "kb_name": cluster_kb_name
                    })
                    
            except Exception as second_attempt_err:
                PipelineLogger.write(f"   >> [ERROR] 2nd time KB API fail: {second_attempt_err}")
                PipelineLogger.write("   >> Fallback triggered: Updating context tree with null properties.")
                
                fallback_kb_id = None
                fallback_kb_name = "KB Creation Process Failed"
                
                for item in batch_slice:
                    batch_raw_code_metadata.append({
                        "file_identity": item["name"],
                        "source_system_path": item["source_path"].replace("\\", "/"),
                        "kb_id": fallback_kb_id,
                        "kb_name": fallback_kb_name
                    })

            save_incremental_context_tree(folder_rel_dir, batch_raw_code_metadata)

    duration = datetime.now() - start_time
    PipelineLogger.write("\n==================================================================")
    PipelineLogger.write(f"KB INGESTION & CONTEXT TREE SYNCHRONIZATION RUN COMPLETE!")
    PipelineLogger.write(f"-> Total Knowledge Base Blocks Successfully Created: {total_kbs_uploaded}")
    PipelineLogger.write(f"-> Master Context Tree Saved to: {os.path.join(index_root, 'context_tree.json')}")
    PipelineLogger.write(f"TOTAL EXECUTION TIME SPENT: {str(duration)}")
    PipelineLogger.write("==================================================================")


# ==============================================================================
# UNIFIED SEQUENTIAL RUN PIPELINE ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    # 1. Execute indexing process from indexer.py natively
    try:
        build_repo_index()
    except Exception as error:
        print(f"Critical error compiling codebase index: {error}")
        
    # 2. Append and run the KB Creation ingestion loop sequentially directly from directory tree outputs
    try:
        run_standalone_kb_ingestion()
    except Exception as pipeline_fault:
        print(f"Fatal context run execution halted: {pipeline_fault}")
