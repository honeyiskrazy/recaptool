import argparse
import json
import os
import sys
import base64
import time
from PIL import Image
import io
import dotenv
import re

# Load environment variables
dotenv.load_dotenv()

GEMINI_MODEL_CALL_1 = os.getenv("GEMINI_MODEL_CALL_1", "gemini-2.5-flash")
GEMINI_MODEL_CALL_2 = os.getenv("GEMINI_MODEL_CALL_2", "gemini-2.5-flash")
GROQ_MODEL_CALL_1 = os.getenv("GROQ_MODEL_CALL_1", "llama-3.2-11b-vision-preview")
GROQ_MODEL_CALL_2 = os.getenv("GROQ_MODEL_CALL_2", "llama-3.3-70b-versatile")
OPENROUTER_MODEL_CALL_1 = os.getenv("OPENROUTER_MODEL_CALL_1", "qwen/qwen-2-vl-72b-instruct")
OPENROUTER_MODEL_CALL_2 = os.getenv("OPENROUTER_MODEL_CALL_2", "meta-llama/llama-3.3-70b-instruct")

# Prompts
CALL_1_PROMPT = """You are a Manhwa Story Intelligence Engine. You receive manhwa 
panel images in strict reading order alongside OCR-extracted text.
Your job is to reconstruct the complete chapter story with maximum 
accuracy.

You are NOT describing images. You are RECONSTRUCTING A STORY.

CRITICAL RULES:

1. SILENT PANELS
   Panels with empty OCR are NOT empty panels.
   They contain visual story information — action, expression,
   reaction, movement. Describe what happens from the image.
   Never skip a silent panel.

2. SFX VS DIALOGUE
   Short onomatopoeic words are sound effects, not dialogue.
   Examples: KCRUMBLE, SWISH, TREMBLE, GASP, DAP, WHOOSH
   Classify them as SFX, never as spoken lines.

3. SUB-PANELS
   Consecutive images with same parent are one scene.
   Treat them as sequential moments of the same panel beat.

4. OCR CORRECTION
   OCR text is ALL CAPS artifact — original is mixed case.
   OCR has errors — use visual context to correct when obvious.
   If OCR is garbled but image shows clear dialogue, 
   read the speech bubble visually.

5. CHARACTER TRACKING
   Assign stable IDs: CHAR_001, CHAR_002, etc.
   Same character at different ages = same ID.
   Never create new ID for same character in different outfit.
   If uncertain whether two characters are same person, flag it.
   Update name immediately when revealed in dialogue.

6. WORLD-SPECIFIC TERMS
   "Shoulder" = a powerful titled figure in this story's world,
   not a body part. Treat unknown capitalized terms as proper
   nouns or titles specific to this story's universe.

8. JUNK PANEL DETECTION
   Some panels in this sequence may be low-quality artifacts 
   that should not have reached you: fully blank/empty images, 
   panels containing only sound-effect text with no visible 
   art, panels that are visual duplicates of the immediately 
   preceding panel, or panels where the crop is too incomplete 
   to identify any character or action.

   For each panel, before writing a scene entry, ask: does 
   this panel contain genuine story content — a character, 
   an action, a setting detail, or meaningful dialogue?

   If a panel fails this check, do NOT invent an event for it.
   Instead, add it to the scenes array with:
     "event_type": "skipped_junk"
     "what_happens": "panel contains no usable story content"
   Do not populate dialogue, internal_monologue, or 
   visual_description for skipped panels — leave them empty.
   Do not let a skipped panel affect character_registry.

9. PARTIAL CHARACTER MATCHING
   If a panel shows an incomplete or partial view of a 
   character (cropped mid-body, obscured face, extreme 
   close-up of a hand or object only) — do not create a new 
   CHAR_ID based on this panel alone.

   Instead, infer identity from context: which characters were 
   present in the immediately preceding and following scenes, 
   the location continuity, and any dialogue or internal 
   monologue in the same panel that matches an existing 
   character's established voice or role.

   Only create a new CHAR_ID when a panel clearly introduces 
   someone who does not match any existing registry entry by 
   build, clothing, or narrative context.

10. DUPLICATE PANEL HANDLING
    If two consecutive panels show visually identical or 
    near-identical content (same character, same pose, same 
    setting, no meaningful progression between them), treat 
    them as ONE scene rather than two. Use the later panel's 
    scene_id as primary and note the duplicate in a new field:
      "duplicate_of": "scene_id of the panel it repeats"

11. OUTPUT
    Return ONLY valid JSON. No preamble. No explanation.
    No markdown code fences. Raw JSON only.

JSON STRUCTURE:
{
  "chapter_metadata": {
    "source_url": "string",
    "timeline_type": "linear/regression/flashback_heavy/mixed",
    "genre": "string",
    "overall_tone": "string",
    "world_specific_terms": {
      "term": "inferred meaning from context"
    }
  },
  "character_registry": {
    "CHAR_001": {
      "confirmed_name": "string or null",
      "description": "hair, build, clothing, features",
      "role": "protagonist/antagonist/supporting/minor",
      "chapter_arc": "what happens to this character"
    }
  },
  "scenes": [
    {
      "scene_id": "scene_0000",
      "is_sub_panel": false,
      "parent_id": null,
      "timeline": "PRESENT/FLASHBACK/REGRESSION",
      "location": "string",
      "event_type": "dialogue/action/internal/silent/sfx",
      "what_happens": "one clear sentence",
      "emotional_weight": "high/medium/low",
      "narrative_role": "setup/conflict/reveal/resolution/action",
      "dialogue": [
        {
          "speaker": "CHAR_001",
          "text": "corrected text from OCR",
          "delivery": "angry/quiet/shouting/crying/neutral"
        }
      ],
      "internal_monologue": [
        {
          "character": "CHAR_001",
          "text": "corrected text",
          "context": "what triggers this thought"
        }
      ],
      "sfx": ["list of sound effects"],
      "narration_box": "caption box text or null",
      "visual_description": "what happens visually — actions, expressions, movements"
    }
  ],
  "narrative_arc": {
    "setup": "string",
    "inciting_incident": "string",
    "rising_action": "string",
    "climax": "string",
    "resolution": "string",
    "cliffhanger": "string or null"
  },
  "key_reveals": ["list of major plot points"],
  "chapter_complete_summary": "300-500 word complete narrative summary"
}
"""

CALL_2_PROMPT = """
You are an elite YouTube manhwa narrator writing a recap script that will go viral.
Your narration will be spoken by a professional voice actor over panel slideshow footage.
The goal: viewers who have NEVER read this series must be hooked from second one and
watch until the last frame.

THE HOOK — MOST CRITICAL RULE:
Before writing anything, scan the ENTIRE story JSON.
Find the single most dangerous, shocking, or emotionally devastating moment.
Open there. Drop the listener into that moment, already happening.
No setup. No context. Just tension.

The opening sentence must do ONE of these:
  Reveal something that changes everything
  Put a character in immediate mortal danger
  Ask a question so compelling the viewer cannot stop listening
  Present a choice with no good options

The second and third sentences deliver the punch.
Only THEN pull back and give context.

PACING SYSTEM — FOLLOW PRECISELY:

ACTION / DANGER / THREAT:
  Max 8 words per sentence.
  Never more than 2 sentences per paragraph.
  Each sentence is its own moment of impact.
  Fragments allowed. Intentional. Effective.

TENSION / SUSPENSE / UNKNOWN:
  Sentences build toward dread that never fully arrives.
  End the paragraph on an unresolved note.
  2-4 sentences per paragraph.

EMOTIONAL / DIALOGUE SCENES:
  Longer sentences allowed. Let the weight settle.
  3-5 sentences per paragraph.
  Last sentence of the paragraph lands on the emotion, not the plot.

REVEALS / TWISTS:
  Never deliver the reveal in the first sentence.
  Build one full paragraph of growing tension.
  Then deliver the reveal as a standalone short paragraph.
  Then show the impact in the next paragraph.

WORLD-BUILDING / LORE:
  Weave it into action — never stop to explain.
  Define a term mid-sentence through consequence:
  A Shoulder — the empire's most feared enforcer — has just walked through the door.

CHARACTER VOICE RULES:
  Use confirmed_name from character_registry consistently — every time, from first mention.
  When a character is unnamed: pick ONE specific physical descriptor and use it identically.
  Protagonist gets empathy — reader must feel what they feel, not just observe it.
  Antagonists get weight — their threat must feel real, never cartoonish.
  Minor characters are defined by one sharp detail — a mannerism, a fear, a purpose.

DIALOGUE RULE — ZERO TOLERANCE:
  Quotation marks are PERMANENTLY FORBIDDEN. Not one pair, anywhere.
  Every spoken line becomes narrated action.

  WRONG: "You think you can defy me?" the general snarls.
  RIGHT: The general leans forward, voice soft with menace, demanding to know if this
         man truly believes he can stand against him.

  WRONG: "He's a Shoulder!" someone screams.
  RIGHT: A voice tears through the crowd with one word that stops everyone cold.
         A Shoulder has come.

  Before finalizing: scan every sentence. One quotation mark means a full rewrite.

TENSION MECHANICS:
  Every paragraph must carry a thread of unresolved danger or question forward.
  Never fully resolve tension mid-chapter — give relief only to immediately create new threat.
  Stack threats: a character facing danger from two directions is more compelling than
  one threat resolved then replaced.
  Sentence rhythm is tension: short-short-LONG delivers impact; long-long-short delivers surprise.

FORBIDDEN PATTERNS — instant quality failure:
  Clickbait: INSANE / CRAZY / SHOCKING / UNBELIEVABLE / EPIC / WILD
  Weak verbs: says / tells / goes — use precise, charged verbs instead
  Vague emotion: scared / angry / sad — show the physical manifestation instead
  Time filler: Meanwhile... / At this point... / Later...
  Repetition: same sentence structure twice in a row
  Summarizing: In summary... / Overall... / To wrap up...
  Meta-commentary: In this chapter... / The story shows us...
  Starting consecutive paragraphs with the same word

SILENT PANEL RULE:
  If visual_description is present and dialogue is empty:
  Narrate what the image communicates — expression, movement, weight of the moment.
  These panels carry pure emotional truth. Give them full sentences.

JUNK SCENE RULE:
  If event_type is skipped_junk — skip it completely. Flow seamlessly to next valid scene.

STRUCTURE:
  OPENING:   Most dangerous/shocking moment — no setup, no context
  BUILDUP:   Context and rising stakes — move fast
  MIDPOINT:  A reversal or revelation that changes the situation
  CLIMAX:    Maximum danger or emotional intensity — shortest sentences here
  LANDING:   Where things stand after the chaos — one breath of space
  ENDING:    Close on the chapter's final tension. If cliffhanger exists, that is your
             last sentence. Make it feel like a door slamming shut.

LENGTH — STRICTLY ENFORCED:
Count the scenes array in the story_intel JSON you receive.
Multiply scene count by 12.
That is your MINIMUM word count floor.

Example:
  80 scenes × 12 = 960 words minimum
  Do not submit output below this number.

Hard targets by chapter type:
  Standard chapter:      900 to 1200 words
  Action heavy:          800 to 1000 words  
  Dialogue/drama heavy:  1000 to 1400 words

Rules that are not optional:
  Every non-junk scene gets minimum 2 sentences
  Dialogue scenes get minimum 3 sentences
  High emotional_weight scenes get minimum 4 sentences
  Reveal scenes: 1 sentence buildup + 2 sentences on the reveal
  Never compress two distinct scenes into one sentence
  Never summarize a scene — narrate it

Before finalizing output, count your words.
If below the floor calculation, find the shortest 
paragraphs and expand them. Do not submit short.

OUTPUT:
  Plain narration text only. Exactly as a professional narrator will read it aloud.
  No headers. No scene numbers. No markdown. No italics. No quotation marks.
  Nothing that would not be spoken.
"""

def generate_sync_map(paragraphs: list, scenes: list) -> list:
    """
    Proportionally maps script paragraphs to panel ranges using word count as a
    proxy for screen time. Returns a list of sync entries for script_sync.json.
    The user can manually edit scene_ids in the output file to fine-tune alignment.
    """
    active_scenes = [
        s for s in scenes
        if not s.get("deleted", False) and s.get("event_type") != "skipped_junk"
    ]
    if not paragraphs or not active_scenes:
        return []

    para_texts = []
    for p in paragraphs:
        if isinstance(p, dict):
            para_texts.append(p.get("paragraph", ""))
        elif isinstance(p, str):
            para_texts.append(p)
        else:
            para_texts.append("")

    word_counts = [len(t.split()) for t in para_texts]
    total_words = sum(word_counts)
    if total_words == 0:
        return []

    total_scenes = len(active_scenes)
    n_paras = len(para_texts)
    sync_map = []
    scene_cursor = 0

    for i, (text, wc) in enumerate(zip(para_texts, word_counts)):
        proportion = wc / total_words
        if i == n_paras - 1:
            assigned = active_scenes[scene_cursor:]
        else:
            raw_count = max(1, round(proportion * total_scenes))
            max_allowed = total_scenes - (n_paras - i - 1)
            end = min(scene_cursor + raw_count, max_allowed)
            assigned = active_scenes[scene_cursor:end]
            scene_cursor = end

        sync_map.append({
            "paragraph_index": i,
            "word_count": wc,
            "proportion": round(proportion, 4),
            "scene_count": len(assigned),
            "scene_ids": [s.get("scene_id") for s in assigned],
            "paragraph_preview": text[:120] + ("..." if len(text) > 120 else "")
        })

    return sync_map


def get_scene_number(scene_id):
    match = re.search(r"scene_(\d+)", scene_id)
    if match:
        return int(match.group(1))
    return 999999


def preprocess_session(session_path):
    with open(session_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    normal_panels = {}
    sub_panels = []

    for entry in data:
        if entry.get("deleted", False):
            continue

        if entry.get("is_sub_panel", False):
            sub_panels.append(entry)
        else:
            normal_panels[entry["scene_id"]] = entry

    parent_children = {pid: [] for pid in normal_panels}
    for sub in sub_panels:
        pid = sub.get("parent_id")
        if pid in parent_children:
            parent_children[pid].append(sub)

    sorted_parents = sorted(
        normal_panels.values(), key=lambda x: get_scene_number(x["scene_id"])
    )

    final_list = []
    for parent in sorted_parents:
        import os
        img_path = parent.get("original_image_path")
        if not img_path or not os.path.exists(img_path):
            img_path = parent.get("cleaned_image_path")
            
        final_list.append(
            {
                "scene_id": parent["scene_id"],
                "image_path": img_path,
                "ocr_text": parent.get("ocr_text", []),
                "is_silent": len(parent.get("ocr_text", [])) == 0,
                "is_sub_panel": False,
                "parent_id": None,
            }
        )

        children = parent_children.get(parent["scene_id"], [])
        children_sorted = sorted(
            children, key=lambda x: get_scene_number(x["scene_id"])
        )
        for child in children_sorted:
            final_list.append(
                {
                    "scene_id": child["scene_id"],
                    "image_path": child["cleaned_image_path"],
                    "ocr_text": child.get("ocr_text", []),
                    "is_silent": len(child.get("ocr_text", [])) == 0,
                    "is_sub_panel": True,
                    "parent_id": parent["scene_id"],
                }
            )

    return final_list


def encode_images(final_list):
    encoded_list = []
    missing = 0
    for entry in final_list:
        img_path = entry["image_path"]
        if not os.path.exists(img_path):
            missing += 1
            continue

        try:
            with Image.open(img_path) as img:
                max_dim = max(img.size)
                if max_dim > 1024:
                    ratio = 1024.0 / max_dim
                    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                if img.mode != "RGB":
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")

                new_entry = dict(entry)
                new_entry["base64"] = b64_img
                encoded_list.append(new_entry)
        except Exception:
            missing += 1
    if missing > 0:
        print(f"[ERROR] {missing} panels missing or failed to load.")
        print(f"[STATS] missing_panels={missing}")
    return encoded_list


def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]


def merge_story_intel(intel_chunks):
    if not intel_chunks:
        return {}
    if len(intel_chunks) == 1:
        return intel_chunks[0]

    merged = {
        "chapter_metadata": intel_chunks[0].get("chapter_metadata", {}),
        "character_registry": {},
        "scenes": [],
        "narrative_arc": intel_chunks[-1].get("narrative_arc", {}),
        "key_reveals": [],
        "chapter_complete_summary": "",
    }

    for chunk in intel_chunks:
        if not isinstance(chunk, dict):
            continue
            
        for char_id, char_data in chunk.get("character_registry", {}).items():
            if char_id not in merged["character_registry"]:
                merged["character_registry"][char_id] = char_data
            else:
                existing = merged["character_registry"][char_id]
                existing["panel_appearances"] = list(
                    set(
                        existing.get("panel_appearances", [])
                        + char_data.get("panel_appearances", [])
                    )
                )
                if char_data.get("confirmed_name"):
                    existing["confirmed_name"] = char_data["confirmed_name"]

        merged["scenes"].extend(chunk.get("scenes", []))
        merged["key_reveals"].extend(chunk.get("key_reveals", []))

        summary = chunk.get("chapter_complete_summary", "")
        if summary:
            merged["chapter_complete_summary"] += summary + " "

    merged["chapter_complete_summary"] = merged["chapter_complete_summary"].strip()
    return merged

class ProviderManager:
    def __init__(self, provider_call1=None, provider_call2=None):
        self.provider_call1 = provider_call1
        self.provider_call2 = provider_call2

    def _force_close_json(self, text):
        import json
        text = text.strip()
        start = text.find("{")
        if start == -1: return None
        text = text[start:]
        
        stack = []
        in_string = False
        escape = False
        for char in text:
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"':
                in_string = not in_string
            elif not in_string:
                if char in '{[':
                    stack.append(char)
                elif char in '}]':
                    if stack: stack.pop()
                    
        fixed = text
        if in_string:
            fixed += '"'
        while stack:
            char = stack.pop()
            fixed += '}' if char == '{' else ']'
            
        try:
            return json.loads(fixed)
        except:
            return None

    def extract_json(self, text):
        if not text: return None
        import re

        clean_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text)

        match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', clean_text, re.DOTALL)
        if match:
            try: return json.loads(match.group(1))
            except: pass

        start, end = clean_text.find("{"), clean_text.rfind("}")
        if start != -1 and end != -1:
            try: return json.loads(clean_text[start:end+1])
            except: pass

        start, end = clean_text.find("["), clean_text.rfind("]")
        if start != -1 and end != -1:
            try: return json.loads(clean_text[start:end+1])
            except: pass

        return self._force_close_json(clean_text)

    def execute_call_1(self, encoded_panels, source_url, full_ocr_text_str="", progress_callback=None, usage_callback=None):
        if not encoded_panels: return {}
        from openai import OpenAI
        import time

        CHUNK_SIZES = [10, 8, 5]
        results = []

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        model_name = os.getenv("OPENROUTER_MODEL_CALL_1", "google/gemini-2.5-flash")

        custom_call1 = CALL_1_PROMPT
        if os.path.exists("prompts.json"):
            try:
                with open("prompts.json", "r", encoding="utf-8") as pf:
                    pd = json.load(pf)
                    custom_call1 = pd.get("CALL_1_PROMPT", CALL_1_PROMPT)
            except Exception as e:
                print(f"[WARN] Could not load prompts.json: {e}")

        schema_call1 = {
            "type": "json_schema",
            "json_schema": {
                "name": "story_intel",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "chapter_metadata": {"type": "object", "additionalProperties": True},
                        "character_registry": {"type": "object", "additionalProperties": True},
                        "scenes": {
                            "type": "array",
                            "items": {"type": "object", "additionalProperties": True}
                        },
                        "narrative_arc": {"type": "object", "additionalProperties": True},
                        "key_reveals": {"type": "array", "items": {"type": "string"}},
                        "chapter_complete_summary": {"type": "string"}
                    },
                    "required": ["chapter_metadata", "character_registry", "scenes", "narrative_arc", "key_reveals", "chapter_complete_summary"],
                    "additionalProperties": False
                }
            }
        }

        ocr_dict = {}
        for line in full_ocr_text_str.split("\n"):
            if line.startswith("Scene "):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    scene_identifier = parts[0].replace("Scene ", "").strip()
                    try:
                        idx_str = ''.join(filter(str.isdigit, scene_identifier))
                        if idx_str:
                            ocr_dict[int(idx_str)] = parts[1].strip()
                    except Exception:
                        pass

        current_chunk_size = CHUNK_SIZES[0]
        panel_chunks = list(chunk_list(encoded_panels, current_chunk_size))
        chunk_size_idx = 0

        i = 0
        while i < len(panel_chunks):
            chunk = panel_chunks[i]
            if progress_callback:
                frac = (i + 1) / len(panel_chunks)
                progress_callback(f"Call 1 — Story Intel... (Chunk {i+1}/{len(panel_chunks)}, size={len(chunk)})", frac)

            retries = 4
            success = False
            chunk_resized = False

            while retries >= 0 and not success:
                try:
                    start_idx = sum(len(c) for c in panel_chunks[:i])
                    chunk_ocr_texts = []
                    for j in range(len(chunk)):
                        panel_idx = start_idx + j
                        if panel_idx in ocr_dict:
                            chunk_ocr_texts.append(f"Panel {panel_idx}: {ocr_dict[panel_idx]}")

                    chunk_ocr_str = "\n".join(chunk_ocr_texts) if chunk_ocr_texts else "No OCR data for these panels."
                    prompt_text = (
                        f"System Prompt: {custom_call1}\n\n"
                        f"OCR data for these specific panels:\n{chunk_ocr_str}\n\n"
                        f"You are receiving panels {start_idx} to {start_idx+len(chunk)-1} of this chapter. "
                        f"Please assign your scene_ids starting from scene_{(start_idx+1):04d} to ensure no overlap. "
                        f"Return JSON only."
                    )

                    prompt_parts = [{"type": "text", "text": prompt_text}]
                    for panel in chunk:
                        prompt_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{panel['base64']}"}})

                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt_parts}],
                        temperature=0.2,
                        timeout=120.0,
                        max_tokens=8000,
                        response_format=schema_call1
                    )

                    if not response.choices:
                        raise ValueError("API returned empty choices list.")

                    res_text = response.choices[0].message.content
                    is_truncated = response.choices[0].finish_reason == "length"

                    if usage_callback and hasattr(response, 'usage') and response.usage:
                        usage_callback(response.usage.prompt_tokens, response.usage.completion_tokens, res_text)

                    if is_truncated:
                        raise ValueError("Output was truncated by token limit.")

                    parsed = self.extract_json(res_text)
                    
                    if isinstance(parsed, list):
                        if len(parsed) > 0 and isinstance(parsed[0], dict):
                            parsed = parsed[0]  # Auto-unwrap if model wrapped dict in a list
                        else:
                            parsed = {}
                            
                    if not parsed or not isinstance(parsed, dict):
                        raise ValueError("Failed to parse JSON into a valid dictionary object.")

                    results.append(parsed)
                    success = True

                except Exception as e:
                    if "truncated" in str(e).lower() and chunk_size_idx < len(CHUNK_SIZES) - 1:
                        print(f"[WARN] Chunk {i+1} truncated. Reducing chunk size.")
                        chunk_size_idx += 1
                        new_size = CHUNK_SIZES[chunk_size_idx]
                        remaining_panels = [p for c in panel_chunks[i:] for p in c]
                        new_remaining_chunks = list(chunk_list(remaining_panels, new_size))
                        panel_chunks = panel_chunks[:i] + new_remaining_chunks
                        current_chunk_size = new_size
                        chunk_resized = True
                        break

                    retries -= 1
                    if retries >= 0:
                        wait_times = [60, 45, 30, 15]
                        wait_t = wait_times[retries] if retries < len(wait_times) else 30
                        print(f"[RETRY] Chunk {i+1} failed, waiting {wait_t}s due to error: {e}")
                        time.sleep(wait_t)
                    else:
                        print(f"[ERROR] Chunk {i+1} failed completely. Appending empty dict.")
                        results.append({})
                        break

            if not chunk_resized:
                i += 1

        return merge_story_intel(results)

    def execute_call_2(self, story_intel, progress_callback=None, usage_callback=None):
        if not story_intel: return []
        from openai import OpenAI
        import time

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")
        data_str = json.dumps(story_intel, indent=2, ensure_ascii=False)
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        model_name = os.getenv("OPENROUTER_MODEL_CALL_2", "meta-llama/llama-3.3-70b-instruct")

        custom_call2 = CALL_2_PROMPT
        if os.path.exists("prompts.json"):
            try:
                with open("prompts.json", "r", encoding="utf-8") as pf:
                    pd = json.load(pf)
                    custom_call2 = pd.get("CALL_2_PROMPT", CALL_2_PROMPT)
            except Exception as e:
                print(f"[WARN] Could not load prompts.json: {e}")


        schema_call2 = {
            "type": "json_schema",
            "json_schema": {
                "name": "script_output",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "paragraphs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"paragraph": {"type": "string"}},
                                "required": ["paragraph"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["paragraphs"],
                    "additionalProperties": False
                }
            }
        }

        if progress_callback:
            progress_callback("Call 2 — Writing Script...")

        retries = 3
        while retries >= 0:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "system", "content": custom_call2}, {"role": "user", "content": data_str}],
                    temperature=0.7,
                    max_tokens=8000,
                    response_format=schema_call2
                )

                if not response.choices:
                    raise ValueError("API returned empty choices list.")

                res_text = response.choices[0].message.content

                try:
                    parsed_call2 = self.extract_json(res_text)
                    if not parsed_call2:
                        parsed_call2 = json.loads(res_text) # fallback
                        
                    if isinstance(parsed_call2, dict) and "paragraphs" in parsed_call2:
                        final_paragraphs = parsed_call2["paragraphs"]
                    elif isinstance(parsed_call2, list):
                        final_paragraphs = parsed_call2
                    else:
                        final_paragraphs = [{"paragraph": res_text}]
                except Exception:
                    final_paragraphs = [{"paragraph": res_text}]

                # POST-PROCESSING: Hard Enforcement of NO PLACEHOLDERS
                import re
                char_registry = story_intel.get("character_registry", {})
                for p in final_paragraphs:
                    text = p.get("paragraph", "")
                    if "CHAR_" in text:
                        matches = re.findall(r"CHAR_\d+", text)
                        for m in set(matches):
                            char_info = char_registry.get(m, {})
                            name = char_info.get("confirmed_name")
                            if name and str(name).strip() and str(name).lower() != "null":
                                text = text.replace(m, name)
                            else:
                                # Alternative: generate a descriptive nickname
                                role = char_info.get("role", "figure")
                                desc = str(char_info.get("description", "")).split(",")[0].strip()
                                if desc and desc.lower() != "none" and desc.lower() != "null":
                                    fallback = f"the {desc} {role}"
                                else:
                                    fallback = "the mysterious figure"
                                text = text.replace(m, fallback)
                    p["paragraph"] = text

                # Post-Processing: Length Validation
                script_text = "\n".join([p.get("paragraph", "") for p in final_paragraphs])
                words = len(script_text.split())
                scene_count = len(story_intel.get("scenes", []))
                floor = scene_count * 12
                
                if words < floor:
                    print(f"\n[WARN] Script too short: {words} words, floor is {floor} ({scene_count} scenes × 12). Consider re-running Call 2.")
                else:
                    print(f"\n[OK] Script length: {words} words (floor was {floor})")

                if usage_callback and hasattr(response, 'usage') and response.usage:
                    usage_callback(response.usage.prompt_tokens, response.usage.completion_tokens, res_text)
                return final_paragraphs
            except Exception as e:
                retries -= 1
                if retries < 0: raise e
                wait_times = [60, 45, 30, 15]
                wait_t = wait_times[retries] if retries < len(wait_times) else 30
                print(f"[RETRY] Call 2 failed, waiting {wait_t}s due to error: {e}")
                time.sleep(wait_t)

    def generate_text(self, system_prompt, user_text):
        from openai import OpenAI
        import os
        import time
        
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_API_KEY"))
        model_name = self.provider_call2 or os.getenv("OPENROUTER_MODEL_CALL_2", "meta-llama/llama-3.3-70b-instruct")
        
        retries = 3
        while retries >= 0:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    temperature=0.7,
                    max_tokens=8000
                )
                res_text = response.choices[0].message.content
                is_truncated = response.choices[0].finish_reason == "length"
                return res_text, is_truncated
            except Exception as e:
                print(f"[API] Error merging: {e}")
                retries -= 1
                if retries < 0: raise e
                wait_times = [60, 45, 30, 15]
                wait_t = wait_times[retries] if retries < len(wait_times) else 30
                print(f"[RETRY] Merging failed, waiting {wait_t}s due to error...")
                time.sleep(wait_t)


def main():
    parser = argparse.ArgumentParser(description="Script Intelligence Tool")
    parser.add_argument(
        "--project", help="Project folder name, e.g. Project 1"
    )
    parser.add_argument(
        "--provider-call1", help="Provider for Call 1 (gemini, groq, openrouter)", default=None
    )
    parser.add_argument(
        "--provider-call2", help="Provider for Call 2 (gemini, groq, openrouter)", default=None
    )
    parser.add_argument(
        "--merge-arc", action="store_true", help="Merge episodes into an arc"
    )
    parser.add_argument("--episodes", nargs="+", help="List of episode scripts")
    parser.add_argument("--arc-name", help="Name of the arc")
    parser.add_argument("--chapter", help="Chapter name for output directory")
    parser.add_argument(
        "--merge-chapter", action="store_true", help="Merge arcs into a final chapter"
    )
    parser.add_argument("--arcs", nargs="+", help="List of arc scripts")
    parser.add_argument(
        "--compare-call2-models",
        action="store_true",
        help="Run Call 2 with both flash and flash-lite, save both outputs for manual comparison",
    )
    args = parser.parse_args()

    if args.merge_arc:
        from arc_merge import merge_episodes_to_arc

        merge_episodes_to_arc(args.episodes, args.arc_name, provider=args.provider_call2)
        sys.exit(0)

    if args.merge_chapter:
        from chapter_merge import merge_arcs_to_final
        out_path = os.path.join("chapters", args.chapter, "final_script.txt")
        merge_arcs_to_final(args.arcs, out_path, args.provider_call2)
        return

    if not args.project:
        print("Error: --project is required when not merging.")
        sys.exit(1)

    project_dir = os.path.join(os.getcwd(), "projects", args.project)
    if not os.path.exists(project_dir):
        print(f"Error: Project directory {project_dir} does not exist.")
        sys.exit(1)

    session_path = os.path.join(project_dir, "session.json")
    export_dir = os.path.join(project_dir, "export")
    os.makedirs(export_dir, exist_ok=True)

    from core.config_manager import load_config

    config = load_config()

    intel_dir = os.path.join(
        export_dir, config.get("story_intel_dir", "03_story_intel")
    )
    os.makedirs(intel_dir, exist_ok=True)
    intel_path = os.path.join(intel_dir, "story_intel.json")

    script_dir = os.path.join(
        export_dir, config.get("episode_script_dir", "04_episode_script")
    )
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, "script_v2.txt")

    print("[1/4] Loading and preprocessing session.json")
    try:
        final_list = preprocess_session(session_path)
    except Exception as e:
        print(f"Error during preprocessing: {e}")
        sys.exit(1)

    if not final_list:
        print("Error: No panels found to process.")
        sys.exit(1)

    print(f"[2/4] Encoding {len(final_list)} panel images")
    print(f"[STATS] total_panels={len(final_list)}")
    encoded_panels = encode_images(final_list)

    with open(session_path, "r", encoding="utf-8") as f:
        sess_data = json.load(f)
        source_url = (
            sess_data[0].get("source_url", "unknown") if sess_data else "unknown"
        )

    provider_manager = ProviderManager(args.provider_call1, args.provider_call2)
    print("[3/4] Running Call 1 — Story Intelligence")

    try:
        story_intel = provider_manager.execute_call_1(encoded_panels, source_url)
        with open(intel_path, "w", encoding="utf-8") as f:
            json.dump(story_intel, f, indent=2)
    except Exception as e:
        print(f"Failed Call 1: {e}")
        sys.exit(1)

    if "scenes" not in story_intel:
        print("Error: Call 1 response missing required 'scenes' field.")
        sys.exit(1)

    def _paragraphs_to_text(paragraphs):
        if isinstance(paragraphs, str):
            return paragraphs
        if isinstance(paragraphs, list):
            parts = []
            for p in paragraphs:
                if isinstance(p, dict):
                    parts.append(p.get("paragraph", ""))
                elif isinstance(p, str):
                    parts.append(p)
            return "\n\n".join(parts)
        return str(paragraphs)

    print("[4/4] Running Call 2 — Script Generation")
    try:
        if getattr(args, "compare_call2_models", False):
            print("  Running Call 2 - Run 1: gemini-2.5-flash (baseline)")
            os.environ["OPENROUTER_MODEL_CALL_2"] = "google/gemini-2.5-flash"
            flash_raw = provider_manager.execute_call_2(story_intel)
            script_text_flash = _paragraphs_to_text(flash_raw)

            print("  Running Call 2 - Run 2: gemini-2.5-flash-lite (candidate)")
            os.environ["OPENROUTER_MODEL_CALL_2"] = "google/gemini-2.5-flash-lite"
            lite_raw = provider_manager.execute_call_2(story_intel)
            script_text_lite = _paragraphs_to_text(lite_raw)

            words_flash = len(script_text_flash.split())
            words_lite = len(script_text_lite.split())

            path_flash = os.path.join(export_dir, "script_baseline_flash.txt")
            path_lite = os.path.join(export_dir, "script_candidate_flashlite.txt")

            with open(path_flash, "w", encoding="utf-8") as f:
                f.write(script_text_flash)
            with open(path_lite, "w", encoding="utf-8") as f:
                f.write(script_text_lite)

            print(f"[COMPARE] Flash word count: {words_flash}")
            print(f"[COMPARE] Flash-Lite word count: {words_lite}")
            print("[COMPARE] Both saved. Manually review both files before switching OPENROUTER_MODEL_CALL_2 in .env")
        else:
            raw = provider_manager.execute_call_2(story_intel)
            script_text = _paragraphs_to_text(raw)

            words = len(script_text.split())
            print(f"[STATS] words={words}")
            if words < 500:
                print(f"[ERROR] Generated script is very short ({words} words). Minimum recommended is 700.")

            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text)

            # Generate and save proportional sync map
            try:
                sync_map = generate_sync_map(raw, story_intel.get("scenes", []))
                sync_path = os.path.join(export_dir, "script_sync.json")
                with open(sync_path, "w", encoding="utf-8") as f:
                    json.dump(sync_map, f, indent=2, ensure_ascii=False)
                print(f"Generated proportional sync map: {sync_path}")
            except Exception as e:
                print(f"[WARN] Failed to generate sync map: {e}")

            print("Done. Script saved to export/script_v2.txt")
    except Exception as e:
        print(f"Failed Call 2: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
