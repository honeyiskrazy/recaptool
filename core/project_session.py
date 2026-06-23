import os
import json
import logging
import shutil

logger = logging.getLogger(__name__)

class ProjectSession:
    def __init__(self, base_dir: str, project_name: str):
        self.base_dir = base_dir
        self.project_name = project_name
        self.project_dir = os.path.join(base_dir, project_name)
        self.session_file = os.path.join(self.project_dir, "session.json")
        self.backup_file = os.path.join(self.project_dir, "session.json.bak")
        
        self.scenes = []
        
        os.makedirs(self.project_dir, exist_ok=True)
        self.load()

    def load(self):
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    self.scenes = json.load(f)
                logger.info(f"Loaded existing session with {len(self.scenes)} scenes.")
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Session file corrupted: {e}. Trying backup...")
                # Try loading from backup
                if os.path.exists(self.backup_file):
                    try:
                        with open(self.backup_file, 'r', encoding='utf-8') as f:
                            self.scenes = json.load(f)
                        logger.info(f"Recovered {len(self.scenes)} scenes from backup.")
                        # Restore the main file from backup
                        self.save()
                    except Exception as e2:
                        logger.error(f"Backup also corrupted: {e2}. Starting fresh.")
                        self.scenes = []
                else:
                    logger.error(f"No backup available. Starting fresh.")
                    self.scenes = []
        return self.scenes
                
    def save(self):
        """Atomic save: write to .tmp, then rename to avoid corruption on crash."""
        os.makedirs(self.project_dir, exist_ok=True)

        tmp_file = self.session_file + ".tmp"
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.scenes, f, indent=2, ensure_ascii=False)

            if os.path.exists(self.session_file):
                valid_backup = False
                try:
                    with open(self.session_file, 'r', encoding='utf-8') as f:
                        json.load(f)
                    valid_backup = True
                except Exception:
                    pass
                if valid_backup:
                    shutil.copy2(self.session_file, self.backup_file)

            if os.path.exists(self.session_file):
                os.replace(tmp_file, self.session_file)
            else:
                os.rename(tmp_file, self.session_file)
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    def add_scene(self, scene_data: dict):
        """
        Add a single scene and save immediately.
        Use add_scenes_batch() during processing for better performance.
        """
        self.scenes.append(scene_data)
        self.save()
    
    def add_scenes_batch(self, scene_data_list: list):
        """
        Add multiple scenes at once with a single disk write.
        Use this during processing to avoid O(N) writes.
        """
        self.scenes.extend(scene_data_list)
        self.save()
        
    def get_active_scenes(self):
        return [s for s in self.scenes if not s.get("deleted", False)]
        
    def get_all_scenes(self):
        return self.scenes
        
    def update_scene(self, index: int, updates: dict):
        if 0 <= index < len(self.scenes):
            self.scenes[index].update(updates)
            self.save()

    def insert_scene_after(self, index: int, new_scene_data: dict):
        if 0 <= index < len(self.scenes):
            self.scenes.insert(index + 1, new_scene_data)
        else:
            self.scenes.append(new_scene_data)
        self.save()

    def swap_scenes(self, idx1: int, idx2: int):
        if 0 <= idx1 < len(self.scenes) and 0 <= idx2 < len(self.scenes):
            self.scenes[idx1], self.scenes[idx2] = self.scenes[idx2], self.scenes[idx1]
            self.save()
