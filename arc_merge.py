import os
import sys
import json

# Resolve base dir so output path works regardless of cwd
_MERGE_BASE = os.path.dirname(os.path.abspath(__file__))

from script_tool import ProviderManager

MERGE_PROMPT = """
You receive multiple sequential episode recap scripts from the
same manhwa story arc. Merge them into one unified, continuous
narration script.

CONTENT POLICY:
This is adult manhwa. Maintain ALL mature content as-is:
violence, blood, death, sexual situations, assault, threats.
Do NOT sanitize or soften anything from the source scripts.

MERGE RULES:
1. Remove every individual episode's opening hook
   Write ONE strong, tension-first opening for the full arc
2. Remove every individual episode's standalone ending
   Keep only the final episode's ending if it's a cliffhanger
3. Create smooth narrative transitions between episodes —
   no 'next episode' language, no episode numbers, no breaks
   The story should read as one continuous narrative
4. Fix character name inconsistencies across episodes —
   pick the most-used correct name, apply it everywhere
5. Remove repeated world-building explanations —
   if a term was explained in an earlier episode, skip re-explaining
6. Maintain strict chronological order of episodes as given
7. Apply the same dialogue rule — zero quotation marks
8. Vary pacing across the arc — let tension rise and fall naturally

LENGTH TARGET:
Preserve maximum content. Do NOT aggressively compress.
Target approximately 90% of total input word count.
Do not drop scenes or details to hit a word count target.

OUTPUT:
Plain narration text only. No episode markers.
No headers. One continuous script.
"""

def merge_episodes_to_arc(episode_script_paths, series_name, provider=None, output_filename="merged_script.txt"):
    """
    Merges all episode scripts for a series into one combined script.
    Output: {base_dir}/projects/{series_name}/script_merged/{output_filename}
    """

    if not episode_script_paths or not series_name:
        print("Error: episode_script_paths and series_name are required.")
        return None

    # Read all episode scripts
    user_text_blocks = []
    for ep_path in episode_script_paths:
        if not os.path.exists(ep_path):
            print(f"Warning: Episode script not found: {ep_path}")
            continue
        with open(ep_path, 'r', encoding='utf-8') as f:
            user_text_blocks.append(f.read().strip())

    if not user_text_blocks:
        print("Error: No valid episode scripts found to merge.")
        return None

    user_text = "\n\n---\n\n".join(user_text_blocks)

    print(f"[CHUNK] Merging {len(user_text_blocks)} episodes for '{series_name}'...")
    print(f"  Total input: {len(user_text.split())} words")

    pm = ProviderManager(provider_call2=provider)
    try:
        custom_merge = MERGE_PROMPT
        if os.path.exists("prompts.json"):
            try:
                with open("prompts.json", "r", encoding="utf-8") as pf:
                    pd = json.load(pf)
                    custom_merge = pd.get("MERGE_PROMPT", MERGE_PROMPT)
            except: pass
            
        merged_text, is_truncated = pm.generate_text(custom_merge, user_text)
    except Exception as e:
        print(f"[ERROR] Script merge failed: {e}")
        return None

    if not merged_text or not merged_text.strip():
        print("[ERROR] Merge returned empty output.")
        return None

    # Absolute output path — works regardless of cwd
    out_dir = os.path.join(_MERGE_BASE, "projects", series_name, "script_merged")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_filename)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(merged_text)

    words = len(merged_text.split())
    print(f"[STATS] words={words}")
    print(f"  ✅ Merged script saved → {out_path} ({words} words)")
    if is_truncated:
        print("Warning: Output may be truncated due to token limits.")

    return out_path
