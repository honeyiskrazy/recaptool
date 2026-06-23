import os
import json
import logging
from core.project_session import ProjectSession
from core.config_manager import load_config

logger = logging.getLogger(__name__)

# Root directory of the project (where main.py lives)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Exporter:
    def __init__(self, session: ProjectSession):
        self.session = session
        self.project_dir = session.project_dir
        
        self.config = load_config()
        
        self.export_dir = os.path.join(self.project_dir, "export")
        self.raw_images_dir = os.path.join(self.export_dir, self.config.get("raw_images_dir", "01_raw_images"))
        self.cleaned_images_dir = os.path.join(self.export_dir, self.config.get("cleaned_images_dir", "02_cleaned_images"))
        
        self.capcut_package_dir = os.path.join(self.export_dir, self.config.get("capcut_package_dir", "05_capcut_package"))
        self.capcut_assets_dir = os.path.join(self.capcut_package_dir, "assets")
        self.capcut_metadata_dir = os.path.join(self.capcut_package_dir, "metadata")
        
        self.storyboard_path = os.path.join(self.export_dir, "storyboard.json")
        self.ocr_path = os.path.join(self.export_dir, "ocr.json")
        
        self.setup_directories()

    def setup_directories(self):
        dirs = [
            self.raw_images_dir,
            self.cleaned_images_dir,
            self.capcut_package_dir,
            self.capcut_assets_dir,
            self.capcut_metadata_dir
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
            
    def get_raw_image_path(self, index: int) -> str:
        return os.path.join(self.raw_images_dir, f"raw_{index:03d}.jpg")
        
    def get_cleaned_image_path(self, index: int) -> str:
        return os.path.join(self.cleaned_images_dir, f"clean_{index:03d}.jpg")

    def add_scene(self, index, source_url, source_site, ocr_text, crop_dims, apply_motion):
        self.session.add_scene({
            "scene_id": f"scene_{index}",
            "source_url": source_url,
            "source_site": source_site,
            "original_image_path": self.get_raw_image_path(index),
            "cleaned_image_path": self.get_cleaned_image_path(index),
            "ocr_text": [ocr_text] if isinstance(ocr_text, str) else ocr_text,
            "crop_dimensions": crop_dims,
            "motion_preset_applied": apply_motion
        })
        
    def save_metadata(self):
        self.session.save()

    def _create_16x9_frame(self, img_path: str, out_path: str):
        """
        Just copies the image without baking in any background.
        This allows CapCut to natively apply Canvas Blur and Animations 
        to the original image bounds instead of a 16:9 padded frame.
        """
        import shutil
        try:
            shutil.copy2(img_path, out_path)
            return out_path
        except Exception:
            # Fallback
            import cv2
            import numpy as np
            blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
            cv2.imwrite(out_path, blank)
            return out_path
            
    def export_package(self, allowed_animations: list = None, project_name: str = None, 
                       progress_callback=None, custom_draft_dir=None, 
                       combined_audio_path: str = None, audio_timeline: list = None):
        """
        Generates a direct CapCut project using only non-deleted scenes in their current order.
        Images are fitted into 16:9 (1920x1080) frames.
        If combined_audio_path is provided, uses it as a single audio track.
        """
        import shutil
        import uuid
        import time
        
        def generate_id():
            return str(uuid.uuid4()).upper()
            
        active_scenes = self.session.get_active_scenes()
        
        if not custom_draft_dir:
            capcut_draft_dir = os.path.expanduser(r"~\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft")
        else:
            capcut_draft_dir = custom_draft_dir
            
        if not project_name:
            project_name = f"Webtoon_Edit_{int(time.time())}"
            
        output_dir = os.path.join(capcut_draft_dir, project_name)
        
        # Use __file__-relative path instead of os.getcwd()
        template_dir = os.path.join(PROJECT_ROOT, "capcut_template")
        
        # Fix: copytree with dirs_exist_ok to prevent crash on re-export
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)
        shutil.copytree(template_dir, output_dir)
        
        draft_content_path = os.path.join(output_dir, "draft_content.json")
        draft_meta_info_path = os.path.join(output_dir, "draft_meta_info.json")
        
        with open(draft_content_path, 'r', encoding='utf-8') as f:
            draft = json.load(f)
            
        video_track = {"id": generate_id(), "type": "video", "segments": []}
        audio_track = {"id": generate_id(), "type": "audio", "segments": []}
        draft["tracks"] = [video_track, audio_track]
        draft["materials"]["videos"] = []
        if "audios" not in draft["materials"]:
            draft["materials"]["audios"] = []
            
        # Collect default material references from template (e.g. Canvas Blur, Speeds)
        extra_refs = []
        for mat_type, items in draft.get("materials", {}).items():
            if mat_type not in ("videos", "audios", "drafts", "texts", "transitions"):
                if isinstance(items, list):
                    for item in items:
                        if "id" in item:
                            extra_refs.append(item["id"])
        
        current_time_us = 0
        default_duration_us = 3000000  # 3 seconds
        
        script_data = {}
        
        # Create 16:9 frames directory
        frames_dir = os.path.join(self.export_dir, "16x9_frames")
        os.makedirs(frames_dir, exist_ok=True)
        
        # Calculate per-scene duration from audio timeline if available
        scene_durations = {}
        if audio_timeline and combined_audio_path:
            # Distribute audio timeline paragraphs across scenes
            # Simple approach: divide total audio evenly across scenes
            total_audio_ms = sum(entry.get("duration_ms", 3000) for entry in audio_timeline)
            total_scenes = len(active_scenes)
            if total_scenes > 0:
                per_scene_ms = total_audio_ms / total_scenes
                for i in range(total_scenes):
                    scene_durations[i] = int(per_scene_ms * 1000)  # to microseconds
        
        last_anim = None
        
        for new_idx, scene in enumerate(active_scenes):
            img_path = scene.get("cleaned_image_path")
            if not img_path or not os.path.exists(img_path):
                img_path = scene.get("original_image_path")
                
            if img_path and os.path.exists(img_path):
                if progress_callback:
                    progress_callback(new_idx + 1, len(active_scenes), 
                                     f"Preparing Scene {new_idx + 1}/{len(active_scenes)}...")
                
                # Create 16:9 frame for YouTube
                frame_path = os.path.join(frames_dir, f"frame_{new_idx:04d}.jpg")
                self._create_16x9_frame(img_path, frame_path)
                
                # Determine duration
                capcut_duration = scene_durations.get(new_idx, default_duration_us)
                
                mat_id = generate_id()
                capcut_start = current_time_us
                
                # --- Video Material ---
                draft["materials"]["videos"].append({
                    "id": mat_id,
                    "type": "photo",
                    "path": os.path.abspath(frame_path).replace('\\', '/'),
                    "duration": capcut_duration,
                    "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
                    "extra_type_option": 0,
                    "local_id": "",
                    "material_name": os.path.basename(frame_path)
                })
                
                # 9:16 frames are already 1080x1920, no scaling needed
                scale_val = 1.0
                
                seg_id = generate_id()
                seg_data = {
                    "id": seg_id,
                    "material_id": mat_id,
                    "source_timerange": {"start": 0, "duration": capcut_duration},
                    "target_timerange": {"start": capcut_start, "duration": capcut_duration},
                    "clip": {
                        "scale": {"x": 1.0, "y": 1.0},
                        "rotation": 0.0,
                        "transform": {"x": 0.0, "y": 0.0},
                        "flip": {"vertical": False, "horizontal": False},
                        "alpha": 1.0
                    },
                    "extra_material_refs": extra_refs.copy(),
                    "common_keyframes": []
                }
                
                # --- Apply Animation ---
                if allowed_animations:
                    import random
                    
                    # Prevent back-to-back same animations (if multiple options available)
                    available = allowed_animations.copy()
                    if last_anim in available and len(available) > 1:
                        available.remove(last_anim)
                        
                    anim = random.choice(available)
                    last_anim = anim
                    
                    duration_us = int(capcut_duration)
                    if anim == "Zoom In":
                        props = [("KFTypeScaleX", scale_val, scale_val * 1.20), ("KFTypeScaleY", scale_val, scale_val * 1.20)]
                    elif anim == "Zoom Out":
                        props = [("KFTypeScaleX", scale_val * 1.20, scale_val), ("KFTypeScaleY", scale_val * 1.20, scale_val)]
                    elif anim == "Pan Left":
                        props = [("KFTypePositionX", 0.20, -0.20)]
                    elif anim == "Pan Right":
                        props = [("KFTypePositionX", -0.20, 0.20)]
                    elif anim == "Pan Up":
                        props = [("KFTypePositionY", -0.20, 0.20)]
                    elif anim == "Pan Down":
                        props = [("KFTypePositionY", 0.20, -0.20)]
                    else:
                        props = []
                        
                    for prop_name, start_val, end_val in props:
                        kf_list = [
                            {
                                "id": generate_id(), 
                                "time_offset": 0, 
                                "values": [start_val], 
                                "curveType": "Line",
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "string_value": "",
                                "graphID": ""
                            },
                            {
                                "id": generate_id(), 
                                "time_offset": duration_us, 
                                "values": [end_val], 
                                "curveType": "Line",
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "string_value": "",
                                "graphID": ""
                            }
                        ]
                        seg_data["common_keyframes"].append({
                            "id": generate_id(),
                            "material_id": "",
                            "keyframe_list": kf_list,
                            "property_type": prop_name
                        })
                        
                video_track["segments"].append(seg_data)
                current_time_us += capcut_duration
                
            # Build script hierarchy
            scene_id = scene.get("scene_id")
            parent_id = scene.get("parent_id")
            ocr_text = " ".join(scene.get("ocr_text", []))
            
            if scene.get("is_sub_panel") and parent_id:
                if parent_id not in script_data:
                    script_data[parent_id] = {"sub_panels": {}, "script_txt": ""}
                script_data[parent_id]["sub_panels"][scene_id] = ocr_text
            else:
                if scene_id not in script_data:
                    script_data[scene_id] = {"sub_panels": {}, "script_txt": ocr_text}
                else:
                    script_data[scene_id]["script_txt"] = ocr_text
        
        # --- Combined Audio Track ---
        if combined_audio_path and os.path.exists(combined_audio_path):
            audio_mat_id = generate_id()
            
            # Get actual audio duration
            try:
                from mutagen.mp3 import MP3
                audio_info = MP3(combined_audio_path)
                audio_duration_us = int(audio_info.info.length * 1000000)
            except Exception:
                audio_duration_us = current_time_us  # Fallback to video duration
            
            draft["materials"]["audios"].append({
                "id": audio_mat_id,
                "type": "extract_audio",
                "path": os.path.abspath(combined_audio_path).replace('\\', '/'),
                "duration": audio_duration_us,
                "local_id": "",
                "name": os.path.basename(combined_audio_path)
            })
            
            audio_track["segments"].append({
                "id": generate_id(),
                "material_id": audio_mat_id,
                "source_timerange": {"start": 0, "duration": audio_duration_us},
                "target_timerange": {"start": 0, "duration": audio_duration_us},
                "clip": {
                    "scale": {"x": 1.0, "y": 1.0},
                    "transform": {"x": 0.0, "y": 0.0},
                    "alpha": 1.0
                },
                "volume": 1.0,
                "speed": 1.0,
                "extra_material_refs": []
            })
                
        draft["duration"] = current_time_us
        
        # Save hierarchical script
        script_path = os.path.join(self.export_dir, "episode_script.json")
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump({"episode_script": script_data}, f, indent=4, ensure_ascii=False)
        
        with open(draft_content_path, 'w', encoding='utf-8') as f:
            json.dump(draft, f, indent=4)
            
        if os.path.exists(draft_meta_info_path):
            with open(draft_meta_info_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            meta["draft_name"] = project_name
            with open(draft_meta_info_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=4)
                
        logger.info(f"Generated CapCut project at {output_dir}")
        return output_dir

    # ------------------------------------------------------------------
    # Incremental Mega Draft helpers (new nested-folder pipeline)
    # ------------------------------------------------------------------
    _mega_draft_lock = __import__('threading').Lock()

    @staticmethod
    def append_to_capcut_draft(series_dir: str, episode_name: str,
                              active_scenes: list, allowed_animations: list = None):
        """
        Appends one episode's panels to an accumulating mega draft.
        - Generates 9:16 frames and saves them to series_dir/_capcut_draft/assets/
        - Appends video+segment JSON entries to series_dir/_capcut_draft/draft_data.json
        - Returns number of panels appended.

        series_dir  : absolute path to the series folder, e.g. …/projects/oka
        episode_name: e.g. 'ep_001'
        active_scenes: list of scene dicts (already filtered, deleted==False)
        allowed_animations: list of animation names, or None/[] for no animations
        """
        import uuid
        import random
        import shutil

        def _gen_id():
            return str(uuid.uuid4()).upper()

        mega_dir = os.path.join(series_dir, "_capcut_draft")
        assets_dir = os.path.join(mega_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        data_path = os.path.join(mega_dir, "draft_data.json")

        anim_map = {
            "Zoom In":   [("KFTypeScaleX", 1.0, 1.20),  ("KFTypeScaleY", 1.0, 1.20)],
            "Zoom Out":  [("KFTypeScaleX", 1.20, 1.0),  ("KFTypeScaleY", 1.20, 1.0)],
            "Pan Left":  [("KFTypePositionX", 0.20, -0.20)],
            "Pan Right": [("KFTypePositionX", -0.20, 0.20)],
            "Pan Up":    [("KFTypePositionY", -0.20, 0.20)],
            "Pan Down":  [("KFTypePositionY", 0.20, -0.20)],
        }

        def _make_kf(prop, sv, ev, dur):
            def _kf(offset, val):
                return {"id": _gen_id(), "time_offset": offset, "values": [val],
                        "curveType": "Line",
                        "left_control": {"x": 0.0, "y": 0.0},
                        "right_control": {"x": 0.0, "y": 0.0},
                        "string_value": "", "graphID": ""}
            return {"id": _gen_id(), "material_id": "", "property_type": prop,
                    "keyframe_list": [_kf(0, sv), _kf(dur, ev)]}

        with Exporter._mega_draft_lock:
            if os.path.exists(data_path):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {"videos": [], "segments": [], "total_duration": 0}
            else:
                data = {"videos": [], "segments": [], "total_duration": 0}

            extra_refs = []
            template_content = os.path.join(PROJECT_ROOT, "capcut_template", "draft_content.json")
            if os.path.exists(template_content):
                try:
                    with open(template_content, "r", encoding="utf-8") as f:
                        t_draft = json.load(f)
                    for mat_type, items in t_draft.get("materials", {}).items():
                        if mat_type not in ("videos", "audios", "drafts", "texts", "transitions"):
                            if isinstance(items, list):
                                extra_refs.extend(item["id"] for item in items if "id" in item)
                except Exception:
                    pass

            prefix = f"{episode_name}_frame_"
            mats_to_remove = {v["id"] for v in data.get("videos", [])
                              if v.get("material_name", "").startswith(prefix)}

            if mats_to_remove:
                data["videos"] = [v for v in data["videos"] if v["id"] not in mats_to_remove]
                data["segments"] = [s for s in data["segments"] if s["material_id"] not in mats_to_remove]
                current_us = 0
                for s in data["segments"]:
                    dur = s["target_timerange"]["duration"]
                    s["target_timerange"]["start"] = current_us
                    current_us += dur
                data["total_duration"] = current_us

            current_us = data["total_duration"]
            default_dur = 3_000_000

            sync_path = os.path.join(series_dir, episode_name, "export", "script_sync.json")
            scene_durations = {}
            if os.path.exists(sync_path):
                try:
                    with open(sync_path, "r", encoding="utf-8") as f:
                        sync_data = json.load(f)
                    total_ep_dur = len(active_scenes) * default_dur
                    for block in sync_data:
                        b_dur = int(total_ep_dur * block.get("proportion", 0))
                        s_count = block.get("scene_count", 1)
                        if s_count > 0:
                            s_dur = b_dur // s_count
                            for sid in block.get("scene_ids", []):
                                scene_durations[sid] = s_dur
                except Exception as e:
                    logger.warning(f"Failed to load sync map: {e}")

            last_anim = None
            appended = 0

            for idx, scene in enumerate(active_scenes):
                img_path = scene.get("cleaned_image_path", "")
                if not img_path or not os.path.exists(img_path):
                    img_path = scene.get("original_image_path", "")
                if not img_path or not os.path.exists(img_path):
                    continue

                frame_name = f"{episode_name}_frame_{idx:04d}.jpg"
                frame_path = os.path.join(assets_dir, frame_name)

                try:
                    shutil.copy2(img_path, frame_path)
                except Exception:
                    try:
                        import cv2
                        import numpy as np
                        cv2.imwrite(frame_path, np.zeros((1080, 1920, 3), dtype=np.uint8))
                    except Exception as e:
                        logger.warning(f"Could not create frame {frame_name}: {e}")
                        continue

                mat_id = _gen_id()
                abs_frame = os.path.abspath(frame_path).replace("\\", "/")

                panel_dur = scene_durations.get(scene.get("scene_id"), default_dur)
                if panel_dur < 1_000_000:
                    panel_dur = 1_000_000

                data["videos"].append({
                    "id": mat_id, "type": "photo", "path": abs_frame,
                    "duration": panel_dur,
                    "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0,
                             "upper_right_x": 1.0, "upper_right_y": 0.0,
                             "lower_left_x": 0.0, "lower_left_y": 1.0,
                             "lower_right_x": 1.0, "lower_right_y": 1.0},
                    "extra_type_option": 0, "local_id": "", "material_name": frame_name
                })

                seg = {
                    "id": _gen_id(), "material_id": mat_id,
                    "source_timerange": {"start": 0, "duration": panel_dur},
                    "target_timerange": {"start": current_us, "duration": panel_dur},
                    "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0,
                             "transform": {"x": 0.0, "y": 0.0},
                             "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
                    "extra_material_refs": extra_refs.copy(),
                    "common_keyframes": []
                }

                if allowed_animations:
                    available = list(allowed_animations)
                    if last_anim in available and len(available) > 1:
                        available.remove(last_anim)
                    anim = random.choice(available)
                    last_anim = anim
                    for prop, sv, ev in anim_map.get(anim, []):
                        seg["common_keyframes"].append(_make_kf(prop, sv, ev, panel_dur))

                data["segments"].append(seg)
                current_us += panel_dur
                appended += 1

            data["total_duration"] = current_us

            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"append_to_capcut_draft: {appended} panels from {episode_name}")
        return appended

    @staticmethod
    def finalize_capcut_draft(series_dir: str, project_name: str,
                             capcut_output_dir: str = None) -> str:
        """
        Reads the accumulated draft_data.json from series_dir/_capcut_draft/
        and writes a complete CapCut draft project.

        capcut_output_dir: if None, defaults to CapCut's standard drafts folder.
        Returns the path to the created CapCut project folder.
        """
        import shutil
        import uuid

        def _gen_id():
            return str(uuid.uuid4()).upper()

        mega_dir = os.path.join(series_dir, "_capcut_draft")
        data_path = os.path.join(mega_dir, "draft_data.json")

        if not os.path.exists(data_path):
            raise FileNotFoundError(
                f"No mega draft data found at {data_path}. "
                "Review at least one episode with 'Save & Next' first."
            )

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data.get("segments"):
            raise ValueError("draft_data.json has no segments. Nothing to export.")

        if not capcut_output_dir:
            capcut_output_dir = os.path.expanduser(
                r"~\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"
            )

        output_dir = os.path.join(capcut_output_dir, project_name)
        template_dir = os.path.join(PROJECT_ROOT, "capcut_template")

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)
        shutil.copytree(template_dir, output_dir)

        draft_content_path = os.path.join(output_dir, "draft_content.json")
        with open(draft_content_path, "r", encoding="utf-8") as f:
            draft = json.load(f)

        video_track = {"id": _gen_id(), "type": "video", "segments": data["segments"]}
        audio_track = {"id": _gen_id(), "type": "audio", "segments": []}

        draft["tracks"] = [video_track, audio_track]
        draft["materials"]["videos"] = data["videos"]
        if "audios" not in draft["materials"]:
            draft["materials"]["audios"] = []
            
        # --- Auto-Inject Combined Voiceover if it exists ---
        voiceover_path = os.path.join(series_dir, "voiceover", "combined_voiceover.mp3")
        if os.path.exists(voiceover_path):
            audio_mat_id = _gen_id()
            try:
                from mutagen.mp3 import MP3
                audio_info = MP3(voiceover_path)
                audio_duration_us = int(audio_info.info.length * 1000000)
            except Exception:
                audio_duration_us = data["total_duration"]
                
            draft["materials"]["audios"].append({
                "id": audio_mat_id,
                "type": "extract_audio",
                "path": os.path.abspath(voiceover_path).replace('\\', '/'),
                "duration": audio_duration_us,
                "local_id": "",
                "name": "combined_voiceover.mp3"
            })
            
            audio_track["segments"].append({
                "id": _gen_id(),
                "material_id": audio_mat_id,
                "source_timerange": {"start": 0, "duration": audio_duration_us},
                "target_timerange": {"start": 0, "duration": audio_duration_us},
                "clip": {
                    "scale": {"x": 1.0, "y": 1.0},
                    "transform": {"x": 0.0, "y": 0.0},
                    "alpha": 1.0
                },
                "volume": 1.0,
                "speed": 1.0,
                "extra_material_refs": []
            })
            # Ensure the draft duration covers the audio if it's longer
            draft["duration"] = max(data["total_duration"], audio_duration_us)
        else:
            draft["duration"] = data["total_duration"]

        with open(draft_content_path, "w", encoding="utf-8") as f:
            json.dump(draft, f, indent=2)

        meta_path = os.path.join(output_dir, "draft_meta_info.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["draft_name"] = project_name
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        logger.info(f"finalize_capcut_draft: project â†’ {output_dir}")
        return output_dir


